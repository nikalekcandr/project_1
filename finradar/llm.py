"""Optional Claude pass: structured re-extraction + fit-to-resume scoring.

Rule-based parsing is fast and free but struggles with free-form Telegram posts
and digests. For the best-ranked new postings this module asks Claude to:
  * extract company / salary / seniority / format / skills reliably,
  * confirm the finance/economics/analytics domain,
  * score the fit against your resume (``config/resume.txt``) with reasons and red flags,
  * write a one-line Russian summary for the digest.

Requires ``pip install anthropic`` and ANTHROPIC_API_KEY (or an ``ant auth login`` profile).
Only ``max_per_run`` postings are processed per run to keep the cost predictable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from finradar.models import KINDS, SENIORITIES, dumps
from finradar.storage import Store
from finradar.taxonomy import DOMAIN_LABELS

log = logging.getLogger(__name__)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_relevant": {"type": "boolean"},
        "primary_domain": {"type": "string", "enum": list(DOMAIN_LABELS)},
        "kind": {"type": "string", "enum": list(KINDS)},
        "seniority": {"type": "string", "enum": [*SENIORITIES, "unknown"]},
        "company": {"type": "string"},
        "salary_min": {"type": "number"},
        "salary_max": {"type": "number"},
        "salary_currency": {"type": "string"},
        "salary_period": {"type": "string", "enum": ["month", "year", "day", "hour", "unknown"]},
        "work_format": {"type": "string", "enum": ["remote", "hybrid", "office", "unknown"]},
        "location": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "summary_ru": {"type": "string"},
        "fit_score": {"type": "integer"},
        "fit_reasons": {"type": "array", "items": {"type": "string"}},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "is_relevant", "primary_domain", "kind", "seniority", "company", "salary_min", "salary_max",
        "salary_currency", "salary_period", "work_format", "location", "skills", "summary_ru",
        "fit_score", "fit_reasons", "red_flags",
    ],
    "additionalProperties": False,
}


def _system_prompt(profile: dict[str, Any], resume: str) -> str:
    domains = "\n".join(f"- {k}: {v}" for k, v in DOMAIN_LABELS.items())
    return (
        "You read job postings and opportunities (vacancies, internships, fellowships, grants, case "
        "competitions) in finance, economics and analytics, published in Russian or English, and return "
        "structured data for a personal job-search aggregator.\n\n"
        "Extraction rules:\n"
        "- Use only what the posting says. Unknown text fields are an empty string, unknown numbers are 0, "
        "unknown enums are 'unknown'.\n"
        "- Salary: numbers as written, ISO currency code (RUB, USD, EUR, ...), and the period they refer to.\n"
        "- is_relevant is false when the role is outside finance, economics and analytics (e.g. a software "
        "engineer at a bank, a sales rep, an HR role).\n"
        f"- primary_domain is one of these keys:\n{domains}\n\n"
        "Fit scoring: fit_score (0-100) is how well this posting matches the candidate below — role, "
        "level, skills, salary expectations, location and language. Give 2-4 short fit_reasons and any "
        "red_flags (unrealistic requirements, no salary for senior roles, vague employer, signs of a scam). "
        "summary_ru is one plain Russian sentence describing the role.\n\n"
        f"Candidate preferences (YAML-derived):\n{json.dumps(profile, ensure_ascii=False, sort_keys=True)}\n\n"
        f"Candidate resume:\n{resume.strip() or '(not provided — score against the preferences only)'}"
    )


def _posting_text(row: Any) -> str:
    parts = [
        f"Title: {row['title']}",
        f"Company: {row['company'] or ''}",
        f"Location: {row['location'] or ''}",
        f"Salary (as published): {row['salary_text'] or ''}",
        f"Source: {row['source']}  URL: {row['url']}",
        "",
        (row["description"] or "")[:12000],
    ]
    return "\n".join(parts)


def enrich_store(store: Store, settings: dict[str, Any], profile: dict[str, Any],
                 resume_path: str | Path | None = None, limit: int | None = None) -> dict[str, int]:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the optional dependency: pip install 'finradar[llm]'") from exc

    llm_cfg = settings.get("llm") or {}
    model = llm_cfg.get("model", "claude-opus-5-5")
    effort = llm_cfg.get("effort", "low")
    limit = limit or int(llm_cfg.get("max_per_run", 50))
    min_score = float(llm_cfg.get("min_score", 40))
    resume = Path(resume_path).read_text(encoding="utf-8") if resume_path and Path(resume_path).exists() else ""
    system = [{"type": "text", "text": _system_prompt(profile, resume), "cache_control": {"type": "ephemeral"}}]

    rows = list(store.iter_rows(
        "is_active=1 AND is_canonical=1 AND llm IS NULL AND COALESCE(score,0) >= ?", (min_score,),
        order="score DESC, first_seen DESC", limit=limit,
    ))
    client = anthropic.Anthropic()
    stats = {"processed": 0, "refused": 0, "failed": 0, "irrelevant": 0}
    for row in rows:
        try:
            resp = client.beta.messages.create(
                model=model,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": _posting_text(row)}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError:
            log.warning("LLM: rate limited, stopping this run")
            break
        except anthropic.APIConnectionError as exc:
            log.warning("LLM: connection error (%s), stopping this run", exc)
            break
        except anthropic.APIStatusError as exc:
            log.warning("LLM: API error %s for %s", exc.status_code, row["uid"])
            stats["failed"] += 1
            continue
        if resp.stop_reason == "refusal":
            stats["refused"] += 1
            store.update_fields(row["uid"], llm=dumps({"error": "refusal"}))
            continue
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if resp.stop_reason == "max_tokens" or not text:
            stats["failed"] += 1
            continue
        try:
            data = json.loads(text)
        except ValueError:
            stats["failed"] += 1
            continue
        apply_llm(store, row, data)
        stats["processed"] += 1
        stats["irrelevant"] += int(not data.get("is_relevant", True))
    return stats


def apply_llm(store: Store, row: Any, data: dict[str, Any]) -> None:
    """Store the LLM view and fill gaps the rules could not resolve (never overwrite good data)."""
    fields: dict[str, Any] = {"llm": dumps(data)}
    if not row["company"] and data.get("company"):
        fields["company"] = data["company"][:200]
    if not row["seniority"] and data.get("seniority") not in (None, "", "unknown"):
        fields["seniority"] = data["seniority"]
    if not row["work_format"] and data.get("work_format") not in (None, "", "unknown"):
        fields["work_format"] = data["work_format"]
    if row["primary_domain"] in (None, "other") and data.get("primary_domain"):
        fields["primary_domain"] = data["primary_domain"]
    if row["kind"] == "vacancy" and data.get("kind") and data["kind"] != "vacancy":
        fields["kind"] = data["kind"]
    if data.get("is_relevant") is False:
        fields["relevance"] = 0.0
    store.update_fields(row["uid"], **fields)
