"""Generic connectors that turn almost any job site into a source without code.

* ``rss``            — RSS 2.0 / Atom feeds (company career feeds, YM Careers boards, WWR, ...)
* ``jsonld_crawler`` — listing page(s) or sitemap -> vacancy pages -> schema.org JobPosting
                       (Google for Jobs markup that most job sites embed), with OpenGraph fallback
* ``html_list``      — declarative CSS selectors for listing pages
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from lxml import etree

from finradar.http import HttpError
from finradar.models import Vacancy
from finradar.sources.base import Source, as_list, register
from finradar.sources.htmlutil import card_for, find_job_postings, guess_card_fields, jobposting_fields, meta_content
from finradar.textutil import clean_ws, html_to_text, parse_date

_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"


@register("rss")
class RSSSource(Source):
    """Options: ``feeds`` (list of URLs), ``title_regex`` with named groups
    ``title``/``company``/``location`` to split titles like "Company: Role"."""

    complete_listing = False
    default_ttl_days = 30

    def fetch(self) -> Iterator[Vacancy]:
        rx = re.compile(self.cfg["title_regex"]) if self.cfg.get("title_regex") else None
        for feed in as_list(self.cfg.get("feeds")):
            try:
                content = self.http.get(feed).content
            except HttpError as exc:
                self.warn(f"{feed}: {exc}")
                self.partial = True
                continue
            for entry in self.parse_feed(content):
                if self.too_old(entry["published_at"]):
                    continue
                title, company, location = entry["title"], entry.get("author"), None
                if rx and (m := rx.match(title)):
                    groups = m.groupdict()
                    title = groups.get("title") or title
                    company = groups.get("company") or company
                    location = groups.get("location")
                yield self.vacancy(
                    entry["id"], entry["link"], title,
                    company=company or self.cfg.get("company"),
                    description=entry["description"],
                    location=location or self.cfg.get("location"),
                    published_at=entry["published_at"],
                    tags=entry["categories"],
                )

    @staticmethod
    def parse_feed(content: bytes) -> list[dict[str, Any]]:
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(content, parser=parser)
        if root is None:
            return []
        out = []
        items = root.findall(".//item")
        if items:
            for it in items:
                link = (it.findtext("link") or "").strip()
                out.append({
                    "id": (it.findtext("guid") or link).strip(),
                    "title": clean_ws(it.findtext("title")),
                    "link": link,
                    "description": html_to_text(it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or it.findtext("description") or ""),
                    "published_at": parse_date(it.findtext("pubDate") or it.findtext(f"{_DC}date")),
                    "author": clean_ws(it.findtext(f"{_DC}creator") or it.findtext("author")) or None,
                    "categories": [clean_ws(c.text) for c in it.findall("category") if c.text],
                })
            return out
        for e in root.findall(f".//{_ATOM}entry"):
            link_el = e.find(f"{_ATOM}link[@rel='alternate']")
            if link_el is None:  # lxml elements without children are falsy: no `or` here
                link_el = e.find(f"{_ATOM}link")
            link = link_el.get("href") if link_el is not None else ""
            out.append({
                "id": (e.findtext(f"{_ATOM}id") or link).strip(),
                "title": clean_ws(e.findtext(f"{_ATOM}title")),
                "link": link,
                "description": html_to_text(e.findtext(f"{_ATOM}content") or e.findtext(f"{_ATOM}summary") or ""),
                "published_at": parse_date(e.findtext(f"{_ATOM}published") or e.findtext(f"{_ATOM}updated")),
                "author": clean_ws(e.findtext(f"{_ATOM}author/{_ATOM}name")) or None,
                "categories": [c.get("term") for c in e.findall(f"{_ATOM}category") if c.get("term")],
            })
        return out


@register("jsonld_crawler")
class JsonLdCrawlerSource(Source):
    """Crawl listing pages (or a sitemap), follow vacancy links, read JobPosting markup.

    Config::

        start_urls: ["https://perforum.io/jobs"]
        link_pattern: "/jobs/[\\\\w-]+/?$"         # regex for vacancy URLs
        pagination: {param: page, start: 1, max_pages: 5}   # optional
        sitemap: https://site/sitemap.xml          # optional alternative to start_urls
        max_details: 150                           # vacancy pages per run
    """

    complete_listing = False

    def __init__(self, name, cfg, http):
        super().__init__(name, cfg, http)
        self.link_re = re.compile(cfg.get("link_pattern", r"/(?:jobs?|vacanc\w*|ваканси\w*|careers?)/[^/?#]+/?$"), re.I)
        self.max_details = int(cfg.get("max_details", 150))
        self.min_interval = float(cfg.get("min_interval", 1.5))

    def fetch(self) -> Iterator[Vacancy]:
        links = self.collect_links()
        if not links:
            self.warn("no vacancy links found — check start_urls / link_pattern")
            return
        for url, hint in list(links.items())[: self.max_details]:
            try:
                html = self.http.get_text(url, robots=True, min_interval=self.min_interval)
            except HttpError as exc:
                self.warn(f"{url}: {exc}")
                self.partial = True
                continue
            v = self.parse_detail(url, html, hint)
            if v and not self.too_old(v.published_at):
                yield v

    def collect_links(self) -> dict[str, dict[str, Any]]:
        links: dict[str, dict[str, Any]] = {}
        if self.cfg.get("sitemap"):
            for url in self._sitemap_urls(self.cfg["sitemap"]):
                links.setdefault(url, {})
            return links
        pag = self.cfg.get("pagination") or {}
        for start in as_list(self.cfg.get("start_urls")):
            pages = range(int(pag.get("start", 1)), int(pag.get("start", 1)) + int(pag.get("max_pages", 1))) if pag else [None]
            for page in pages:
                params = {pag.get("param", "page"): page} if page is not None else None
                try:
                    html = self.http.get_text(start, params=params, robots=True, min_interval=self.min_interval)
                except HttpError as exc:
                    self.warn(f"{start}: {exc}")
                    self.partial = True
                    break
                found = self.extract_links(start, html)
                new = {u: h for u, h in found.items() if u not in links}
                links.update(new)
                if not new:
                    break
        return links

    def extract_links(self, base: str, html: str) -> dict[str, dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        out: dict[str, dict[str, Any]] = {}
        base_host = urlsplit(base).netloc
        for a in soup.find_all("a", href=True):
            url = urljoin(base, a["href"]).split("#")[0]
            if urlsplit(url).netloc != base_host or not self.link_re.search(urlsplit(url).path):
                continue
            if url in out:
                continue
            card = card_for(a, self.link_re)
            hint = guess_card_fields(card)
            hint["title"] = clean_ws(a.get_text(" ")) or None
            out[url] = hint
        return out

    def _sitemap_urls(self, sitemap_url: str, depth: int = 0) -> list[str]:
        try:
            content = self.http.get(sitemap_url, robots=True).content
        except HttpError as exc:
            self.warn(f"sitemap {sitemap_url}: {exc}")
            return []
        root = etree.fromstring(content, parser=etree.XMLParser(recover=True, no_network=True, resolve_entities=False))
        if root is None:
            return []
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls: list[tuple[str, str]] = []
        for sm in root.findall("s:sitemap", ns):
            loc = sm.findtext("s:loc", namespaces=ns)
            if loc and depth < 2 and re.search(self.cfg.get("sitemap_filter", r"job|vacanc|ваканс"), loc, re.I):
                urls += [(u, "") for u in self._sitemap_urls(loc.strip(), depth + 1)]
        for u in root.findall("s:url", ns):
            loc = (u.findtext("s:loc", namespaces=ns) or "").strip()
            if loc and self.link_re.search(urlsplit(loc).path):
                urls.append((loc, u.findtext("s:lastmod", namespaces=ns) or ""))
        urls.sort(key=lambda x: x[1], reverse=True)  # freshest first
        return [u for u, _ in urls]

    def parse_detail(self, url: str, html: str, hint: dict[str, Any] | None = None) -> Vacancy | None:
        hint = hint or {}
        soup = BeautifulSoup(html, "lxml")
        postings = find_job_postings(soup)
        ext_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] or url
        if postings:
            f = jobposting_fields(postings[0])
            f.pop("url", None)
            ident = f.pop("identifier", None)
            country_raw = f.pop("country_raw", None)
            title = f.pop("title") or hint.get("title") or ""
            if not f.get("company"):
                f["company"] = hint.get("company") or self.cfg.get("company")
            if not f.get("location"):
                f["location"] = hint.get("location") or country_raw
            v = self.vacancy(ident or ext_id, url, title, **f)
            if not (v.salary_min or v.salary_max) and hint.get("salary_text"):
                v.salary_text = hint["salary_text"]
            return v
        # Fallback: OpenGraph / headings / main text
        title = hint.get("title") or meta_content(soup, "og:title") or (soup.h1.get_text(" ") if soup.h1 else "")
        if not title:
            return None
        main = soup.find("main") or soup.find("article") or soup.body
        description = html_to_text(str(main)) if main else (meta_content(soup, "og:description", "description") or "")
        return self.vacancy(
            ext_id, url, clean_ws(title),
            company=hint.get("company") or self.cfg.get("company"),
            description=description[:15000],
            location=hint.get("location"),
            salary_text=hint.get("salary_text"),
            published_at=parse_date(hint.get("date")) or parse_date(meta_content(soup, "article:published_time")),
        )


@register("html_list")
class HtmlListSource(Source):
    """Declarative listing parser.

    Config::

        url_template: "https://site/vacancies?page={page}"
        pages: 3
        item: ".vacancy-card"
        fields: {title: "a.title", link: "a.title@href", company: ".company", salary: ".salary",
                 location: ".city", date: "time@datetime", description: ".snippet"}
    """

    complete_listing = False

    def fetch(self) -> Iterator[Vacancy]:
        template = self.cfg["url_template"]
        seen: set[str] = set()
        for page in range(int(self.cfg.get("first_page", 1)), int(self.cfg.get("first_page", 1)) + int(self.cfg.get("pages", 1))):
            url = template.format(page=page)
            html = self.http.get_text(url, robots=True, min_interval=float(self.cfg.get("min_interval", 1.5)))
            items = list(self.parse(url, html))
            fresh = [v for v in items if v.external_id not in seen]
            if not fresh:
                break
            for v in fresh:
                seen.add(v.external_id)
                yield v

    def parse(self, base: str, html: str) -> Iterator[Vacancy]:
        soup = BeautifulSoup(html, "lxml")
        fields: dict[str, str] = self.cfg.get("fields", {})
        for node in soup.select(self.cfg["item"]):
            values = {k: _select(node, sel) for k, sel in fields.items()}
            link = values.get("link") or values.get("title_link")
            if not values.get("title") or not link:
                continue
            url = urljoin(base, link)
            yield self.vacancy(
                urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] or url, url, values["title"],
                company=values.get("company") or self.cfg.get("company"),
                salary_text=values.get("salary"),
                location=values.get("location"),
                description=values.get("description") or "",
                published_at=parse_date(values.get("date")),
            )


def _select(node, selector: str) -> str | None:
    attr = None
    if "@" in selector:
        selector, attr = selector.rsplit("@", 1)
    el = node.select_one(selector) if selector else node
    if el is None:
        return None
    if attr:
        return el.get(attr)
    return clean_ws(el.get_text(" ")) or None
