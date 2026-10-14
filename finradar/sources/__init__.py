"""Importing this package registers every connector in :data:`REGISTRY`."""

from finradar.sources import (  # noqa: F401
    ats,
    boards,
    email_alerts,
    generic,
    getmatch,
    habr,
    hh,
    keyed,
    telegram,
)
from finradar.sources.base import REGISTRY, Source, SourceConfigError

# Coarse family of each connector type — used for dedup priority and reporting.
FAMILY = {
    "hh": "hh", "habr": "habr", "getmatch": "getmatch", "superjob": "superjob", "trudvsem": "trudvsem",
    "telegram": "telegram", "email_alerts": "email_alerts", "rss": "rss",
    "greenhouse": "ats", "lever": "ats", "ashby": "ats", "smartrecruiters": "ats", "workday": "ats",
    "remotive": "remote_board", "remoteok": "remote_board", "arbeitnow": "remote_board",
    "himalayas": "remote_board", "jobicy": "remote_board", "themuse": "remote_board",
    "adzuna": "keyed_api", "usajobs": "keyed_api", "reed": "keyed_api", "jooble": "keyed_api", "reliefweb": "keyed_api",
    "jsonld_crawler": "jsonld_crawler", "html_list": "html_list",
}

__all__ = ["REGISTRY", "Source", "SourceConfigError", "FAMILY"]
