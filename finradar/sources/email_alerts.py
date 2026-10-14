"""Job-alert e-mails (IMAP) as a data source.

Closed platforms such as LinkedIn, Indeed, Glassdoor or eFinancialCareers do not
offer a public search API and forbid scraping, but all of them e-mail you job
alerts for saved searches. Reading your own mailbox is the clean way to bring
them into the aggregator: subscribe to alerts there, point this connector at a
mailbox folder, and every alert becomes structured postings.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from finradar.models import Vacancy
from finradar.sources.base import Source, SourceConfigError, as_list, register
from finradar.sources.htmlutil import card_for
from finradar.textutil import clean_ws

DEFAULT_LINK_PATTERNS = {
    "linkedin": r"linkedin\.com/(?:comm/)?jobs/view/(\d+)",
    "indeed": r"indeed\.[a-z.]+/(?:rc/clk|viewjob|pagead/clk)\?[^\"'\s]*?jk=([0-9a-f]+)",
    "efinancialcareers": r"efinancialcareers\.[a-z.]+/jobs-[^\"'\s]*?\.id(\d+)",
    "glassdoor": r"glassdoor\.[a-z.]+/[^\"'\s]*?(?:jobListingId|jl)=(\d+)",
    "hh": r"hh\.(?:ru|kz)/vacancy/(\d+)",
}
_SKIP_TEXT = re.compile(r"^(?:view|apply|see|посмотреть|откликнуться|подробнее|easy apply|new|новая)\b", re.I)


@register("email_alerts")
class EmailAlertsSource(Source):
    complete_listing = False
    default_ttl_days = 30

    def __init__(self, name, cfg, http):
        super().__init__(name, cfg, http)
        patterns = cfg.get("link_patterns") or DEFAULT_LINK_PATTERNS
        if isinstance(patterns, list):
            patterns = {f"p{i}": p for i, p in enumerate(patterns)}
        self.patterns = {label: re.compile(p, re.I) for label, p in patterns.items()}

    def fetch(self) -> Iterator[Vacancy]:
        host = self.cfg.get("host", "imap.gmail.com")
        user = self.cfg.get("user") or os.environ.get("IMAP_USER")
        password = os.environ.get(self.cfg.get("password_env", "IMAP_PASSWORD"))
        if not (user and password):
            raise SourceConfigError(f"{self.name}: IMAP user/password not configured")
        since = (datetime.now(timezone.utc) - timedelta(days=int(self.cfg.get("days", 7)))).strftime("%d-%b-%Y")
        with imaplib.IMAP4_SSL(host) as box:
            box.login(user, password)
            box.select(self.cfg.get("folder", "INBOX"), readonly=True)
            senders = as_list(self.cfg.get("senders")) or [None]
            msg_ids: list[bytes] = []
            for sender in senders:
                criteria = ["SINCE", since] + (["FROM", f'"{sender}"'] if sender else [])
                status, data = box.search(None, *criteria)
                if status == "OK" and data and data[0]:
                    msg_ids += data[0].split()
            for mid in dict.fromkeys(msg_ids):
                status, parts = box.fetch(mid, "(RFC822)")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                yield from self.parse_message(parts[0][1])

    def parse_message(self, raw: bytes) -> Iterator[Vacancy]:
        msg = email.message_from_bytes(raw)
        subject = str(make_header(decode_header(msg.get("Subject", ""))))
        try:
            sent = parsedate_to_datetime(msg.get("Date"))
        except (TypeError, ValueError):
            sent = None
        html = None
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
        if html:
            yield from self.parse_html(html, published_at=sent, subject=subject)

    def parse_html(self, html: str, *, published_at=None, subject: str = "") -> Iterator[Vacancy]:
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            for label, rx in self.patterns.items():
                m = rx.search(a["href"])
                if not m:
                    continue
                key = f"{label}-{m.group(1)}"
                if key in seen:
                    break
                card = card_for(a, rx, max_up=5)
                lines = [ln for ln in (clean_ws(t) for t in card.get_text("\n").split("\n")) if ln and not _SKIP_TEXT.match(ln)]
                title = clean_ws(a.get_text(" "))
                if not title or _SKIP_TEXT.match(title) or len(title) < 4:
                    title = lines[0] if lines else ""
                if not title:
                    break
                seen.add(key)
                rest = [ln for ln in lines if ln != title][:3]
                url = a["href"] if label != "linkedin" else f"https://www.linkedin.com/jobs/view/{m.group(1)}"
                yield self.vacancy(
                    key, url, title,
                    company=rest[0] if rest else None,
                    location=rest[1] if len(rest) > 1 else None,
                    description="\n".join(lines[:8]),
                    published_at=published_at,
                    tags=[label, subject[:80]] if subject else [label],
                )
                break
