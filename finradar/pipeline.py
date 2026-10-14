"""Collection pipeline: sources -> enrich -> relevance gate -> store -> dedup -> score."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from finradar import dedup, fx
from finradar.config import Config
from finradar.enrich import enrich
from finradar.http import BlockedError, HttpClient
from finradar.models import Vacancy
from finradar.scoring import Profile, rescore
from finradar.sources import FAMILY, REGISTRY, Source, SourceConfigError
from finradar.storage import Store

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    name: str
    status: str = "ok"  # ok / partial / blocked / error / skipped
    fetched: int = 0
    kept: int = 0
    new: int = 0
    updated: int = 0
    closed: int = 0
    seconds: float = 0.0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def build_http(cfg: Config) -> HttpClient:
    s = cfg.settings
    return HttpClient(
        user_agent=s["user_agent"],
        timeout=float(s["timeout"]),
        min_interval=float(s["min_interval"]),
        respect_robots=bool(s["respect_robots"]),
        host_intervals=s.get("host_intervals") or {},
    )


def build_source(item: dict, http: HttpClient) -> Source:
    cls = REGISTRY.get(item["type"])
    if cls is None:
        raise SourceConfigError(f"unknown source type '{item['type']}' (known: {', '.join(sorted(REGISTRY))})")
    return cls(item["name"], item, http)


def collect(source: Source, rates: dict[str, float], min_relevance: float) -> tuple[list[Vacancy], int, str, str | None]:
    """Run one source. Keeps everything collected before an error (status 'partial')."""
    items: list[Vacancy] = []
    fetched = 0
    status, error = "ok", None
    try:
        for v in source.fetch():
            fetched += 1
            enrich(v, rates)
            if v.relevance >= min_relevance or source.cfg.get("keep_all"):
                items.append(v)
            if fetched >= source.max_items * 3:
                break
    except BlockedError as exc:
        status, error = "blocked", str(exc)
    except SourceConfigError as exc:
        status, error = "skipped", str(exc)
    except Exception as exc:  # a broken source must never kill the run
        log.exception("[%s] failed", source.name)
        status, error = ("partial" if fetched else "error"), f"{type(exc).__name__}: {exc}"
    if status == "ok" and source.partial:
        status = "partial"
    return items, fetched, status, error


def run(cfg: Config, store: Store, only: list[str] | None = None, *, dry_run: bool = False) -> list[SourceResult]:
    http = build_http(cfg)
    rates = fx.load_rates(http, store, overrides=cfg.settings["fx"].get("rates"), live=bool(cfg.settings["fx"].get("live", True)))
    min_rel = float(cfg.settings["min_relevance"])
    results: list[SourceResult] = []
    sources: list[Source] = []
    for item in cfg.enabled_sources(only):
        try:
            sources.append(build_source(item, http))
        except SourceConfigError as exc:
            results.append(SourceResult(item.get("name", "?"), status="skipped", error=str(exc)))

    def work(src: Source) -> SourceResult:
        t0 = time.monotonic()
        res = SourceResult(src.name)
        run_id = None if dry_run else store.start_run(src.name)
        items, res.fetched, res.status, res.error = collect(src, rates, min_rel)
        res.kept = len(items)
        res.warnings = list(src.warnings)
        if not dry_run:
            res.new, res.updated, seen = store.upsert(items)
            if src.complete_listing and res.status == "ok":
                res.closed = store.close_missing(src.name, seen)
            elif not src.complete_listing:
                res.closed = store.expire(src.name, src.ttl_days)
            store.finish_run(
                run_id, res.status, res.error,
                fetched=res.fetched, kept=res.kept, new=res.new, updated=res.updated, closed=res.closed,
            )
        res.seconds = round(time.monotonic() - t0, 1)
        return res

    workers = max(1, int(cfg.settings["max_workers"]))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, s): s for s in sources}
        for fut in as_completed(futures):
            results.append(fut.result())

    if not dry_run:
        postprocess(cfg, store)
    return sorted(results, key=lambda r: r.name)


def postprocess(cfg: Config, store: Store) -> dict[str, int]:
    types = {s["name"]: FAMILY.get(s["type"], s["type"]) for s in cfg.sources}
    stats = dedup.recluster(store, source_types=types, priority=cfg.settings.get("dedup_priority"))
    stats["scored"] = rescore(store, Profile.from_dict(cfg.profile))
    return stats
