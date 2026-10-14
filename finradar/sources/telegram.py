"""Public Telegram channels via the web preview (https://t.me/s/<channel>).

No account or API key is needed. In the Russian finance market a large share of
roles (investment banking, PE/VC, Big4, buy-side) is published *only* in channels
such as @Perforum_jobs or @finexecutive, so this connector matters a lot.

Each post is parsed with heuristics: title/company/salary/location lines, hashtags,
and digest posts (one line + link per role) are split into separate items.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup, Tag

from finradar.models import Vacancy
from finradar.sources.base import Source, register
from finradar.textutil import clean_ws, parse_date

_POSITIVE = re.compile(
    r"#ваканси\w*|#vacanc\w*|#job\w*|#hiring|#работа|ваканси[яи]|ищем|ищу\s+(?:в\s+команду|аналитик|финанс)|требуется|"
    r"в\s+команду|hiring|we\s*(?:'re|\s+are)\s+looking|открыт\w*\s+позици|обязанности|требования|responsibilities|"
    r"requirements|условия|зарплат|з/п|\bзп\b|вилка|salary|стажировк|internship",
    re.I,
)
_NEGATIVE = re.compile(r"#резюме|#resume|#ищу_?работу|#ищуработу|#cv\b|#реклама|#ad\b|erid|#промо", re.I)
_FIELD = r"^\s*[^\wа-яё]*\s*(?:{names})\s*[:\-—–]\s*(.+)$"
_TITLE_LINE = re.compile(_FIELD.format(names=r"вакансия|должность|позиция|position|role|title|job title|job|кого\s+ищем"), re.I | re.M)
_COMPANY_LINE = re.compile(_FIELD.format(names=r"компания|company|работодатель|employer|организация|банк|фонд"), re.I | re.M)
_LOCATION_LINE = re.compile(_FIELD.format(names=r"локация|город|location|место\s+работы|офис|где"), re.I | re.M)
_FORMAT_LINE = re.compile(_FIELD.format(names=r"формат(?:\s+работы)?|format|график|режим\s+работы|work\s+mode"), re.I | re.M)
_SALARY_LINE = re.compile(_FIELD.format(names=r"зп|з/п|зарплата|заработная\s+плата|вилка|оклад|доход|salary|compensation|компенсация|вознаграждение"), re.I | re.M)
_TITLE_AT = re.compile(r"^(?P<title>.{4,120}?)\s+(?:в|at|@|—|–|-|\|)\s+(?P<company>[A-ZА-ЯЁ«\"][^\n]{1,60})$")
_HASHTAG = re.compile(r"#[\w\d_]+", re.U)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿⌀-⏿■-◿]+"
)
_JOB_LINK = re.compile(r"job|vacanc|career|ваканс|hh\.ru/vacancy|perforum\.io|getmatch|lever\.co|greenhouse|ashbyhq|workday|forms\.", re.I)


def _strip_decor(line: str) -> str:
    line = _EMOJI.sub(" ", line)
    line = _HASHTAG.sub(" ", line)
    return clean_ws(line).strip(" -–—•*|:!.")


@register("telegram")
class TelegramSource(Source):
    complete_listing = False
    default_ttl_days = 30

    def __init__(self, name, cfg, http):
        super().__init__(name, cfg, http)
        self.channels = [c.lstrip("@").strip() for c in (cfg.get("channels") or [])]
        self.pages = int(cfg.get("pages", 3))
        self.require_markers = bool(cfg.get("require_markers", True))
        self.split_digests = bool(cfg.get("split_digests", True))
        self.min_length = int(cfg.get("min_length", 60))

    def fetch(self) -> Iterator[Vacancy]:
        count = 0
        for channel in self.channels:
            try:
                for v in self._channel(channel):
                    yield v
                    count += 1
                    if count >= self.max_items:
                        return
            except Exception as exc:  # one broken channel must not stop the others
                self.warn(f"@{channel}: {exc}")

    def _channel(self, channel: str) -> Iterator[Vacancy]:
        before: int | None = None
        for _ in range(self.pages):
            params = {"before": before} if before else None
            html = self.http.get_text(f"https://t.me/s/{channel}", params=params)
            posts = self.parse_page(html, channel)
            if not posts:
                break
            stop = False
            for post in posts:
                if self.too_old(post["published_at"]):
                    stop = True
                    continue
                yield from self.post_to_vacancies(post, channel)
            ids = [p["id"] for p in posts if p["id"]]
            if stop or not ids:
                break
            before = min(ids)

    @staticmethod
    def parse_page(html: str, channel: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        posts = []
        for msg in soup.select("div.tgme_widget_message[data-post]"):
            data_post = msg.get("data-post", "")
            try:
                post_id = int(data_post.rsplit("/", 1)[-1])
            except ValueError:
                continue
            text_el = msg.select_one(".tgme_widget_message_text")
            if text_el is None:
                continue
            time_el = msg.select_one(".tgme_widget_message_date time") or msg.select_one("time[datetime]")
            links = [(clean_ws(a.get_text(" ")), a["href"]) for a in text_el.find_all("a", href=True)]
            posts.append(
                {
                    "id": post_id,
                    "text": _message_text(text_el),
                    "links": links,
                    "published_at": parse_date(time_el.get("datetime")) if time_el else None,
                    "url": f"https://t.me/{channel}/{post_id}",
                }
            )
        return posts

    def is_vacancy_post(self, text: str) -> bool:
        if len(text) < self.min_length or _NEGATIVE.search(text):
            return False
        return bool(_POSITIVE.search(text)) or not self.require_markers

    def post_to_vacancies(self, post: dict[str, Any], channel: str) -> Iterator[Vacancy]:
        text: str = post["text"]
        if not self.is_vacancy_post(text):
            return
        hashtags = [h.lstrip("#") for h in _HASHTAG.findall(text)]
        digest = self._digest_items(post) if self.split_digests else []
        if digest:
            for n, (title, url, line) in enumerate(digest, 1):
                yield self.vacancy(
                    f"{channel}/{post['id']}-{n}", url, title,
                    description=line, published_at=post["published_at"], tags=hashtags,
                    raw={"channel": channel, "post": post["url"], "digest": True},
                )
            return
        title, company = self._title_company(text)
        if not title:
            return
        salary = _SALARY_LINE.search(text)
        location = _LOCATION_LINE.search(text)
        fmt = _FORMAT_LINE.search(text)
        job_links = [href for _, href in post["links"] if _JOB_LINK.search(href) and "t.me/" not in href]
        yield self.vacancy(
            f"{channel}/{post['id']}",
            post["url"],
            title,
            company=company,
            description=text,
            location=clean_ws(" ".join(filter(None, [location and location.group(1), fmt and fmt.group(1)]))) or None,
            salary_text=salary.group(1)[:200] if salary else None,
            published_at=post["published_at"],
            tags=hashtags,
            raw={"channel": channel, "apply_url": job_links[0] if job_links else None},
        )

    @staticmethod
    def _title_company(text: str) -> tuple[str | None, str | None]:
        company_m = _COMPANY_LINE.search(text)
        company = _strip_decor(company_m.group(1)) if company_m else None
        title_m = _TITLE_LINE.search(text)
        if title_m:
            title = _strip_decor(title_m.group(1))
        else:
            title = ""
            for line in text.split("\n"):
                cand = _strip_decor(line)
                if len(cand) >= 4 and not re.fullmatch(r"(?:ваканси[яи]|vacancy|job|hiring|новая вакансия)", cand, re.I):
                    title = cand
                    break
        if title and not company:
            m = _TITLE_AT.match(title)
            if m:
                title, company = m.group("title").strip(), m.group("company").strip(" «»\"")
        title = re.sub(r"^(?:ваканси[яи]|vacancy|новая вакансия)\s*[:\-—–]?\s*", "", title, flags=re.I)
        return (title[:160] or None), (company[:100] if company else None)

    @staticmethod
    def _digest_items(post: dict[str, Any]) -> list[tuple[str, str, str]]:
        """Split posts like '1. FP&A analyst — Company (link)\\n2. ...' into separate roles."""
        text = post["text"]
        if re.search(r"обязанности|требования|responsibilities|requirements", text, re.I):
            return []
        items = []
        lines = text.split("\n")
        for anchor, href in post["links"]:
            if "t.me/" in href or not _JOB_LINK.search(href):
                continue
            line = next((ln for ln in lines if anchor and anchor in ln), anchor)
            title = _strip_decor(re.sub(r"^\s*\d+[.)]\s*", "", line))
            if len(title) >= 4 and not re.fullmatch(r"(?:подробнее|откликнуться|apply|ссылка|link|here|тут|здесь)", title, re.I):
                items.append((title[:160], href, line))
        return items if len(items) >= 3 else []


def _message_text(el: Tag) -> str:
    for br in el.find_all("br"):
        br.replace_with("\n")
    return clean_ws(el.get_text())

