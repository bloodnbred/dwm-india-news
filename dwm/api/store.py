"""The query layer behind the API and the dashboard (Phase 8).

**The API serves results; it does not recompute them.** Every figure it returns
comes from `facts.json`, which the inference stage rendered from the warehouse.
An endpoint that ran its own SQL would be a second, unreviewed path to the
same numbers, and the two would drift.

One exception, and it is deliberate: `/query` runs the Phase 4 OLAP operations
against the warehouse, because those exist precisely to answer ad-hoc slicing
questions. It is read-only, whitelisted to the ten named operations, and every
response states which operation ran.

**Read-only is a property of the file, not a promise.** The DuckDB file is
opened `read_only=True`, so a malformed parameter cannot write to the
warehouse even if validation were bypassed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from dwm.config import PROJECT_ROOT, default_db_path, reports_dir
from dwm.db import connect
from dwm.logging_utils import get

log = get("dwm.api.store")


# Resolved when used, not at import. A module-level constant froze the reports
# directory at import time, so redirection depended on whether this module
# happened to be imported before or after the environment was set — which
# produced a "results not found" 503 while the file was sitting on disk.
def facts_path() -> Path:
    return reports_dir() / "facts.json"


def report_path() -> Path:
    return reports_dir() / "report.md"


class DataUnavailable(RuntimeError):
    """Raised when the warehouse or the results file is not there yet.

    A distinct type so the API can answer 503 with an actionable message
    instead of a 500 that reads like a bug.
    """


def _read_only_settings():
    from dwm.config import Settings

    return Settings(
        db_path=PROJECT_ROOT / "warehouse" / default_db_path().name, read_only=True
    )


@lru_cache(maxsize=1)
def _open_connection():
    """One long-lived read-only handle on the warehouse.

    Cached because a serving process should not reopen the file per request,
    and read-only because the guarantee that no request can write to the
    warehouse should come from the handle rather than from validation.
    """
    path = default_db_path()
    if not path.exists():
        raise DataUnavailable(
            f"no warehouse at {path}. Run "
            "`powershell -ExecutionPolicy Bypass -File .\\run_all.ps1` first."
        )
    return connect(_read_only_settings())


def connection():
    return _open_connection()


def _load_facts() -> dict[str, Any]:
    path = facts_path()
    if not path.exists():
        raise DataUnavailable(
            f"{path} not found. Run `python -m dwm report` to build it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_report_markdown() -> str:
    path = report_path()
    if not path.exists():
        raise DataUnavailable(
            f"{path} not found. Run `python -m dwm report` to build it."
        )
    return path.read_text(encoding="utf-8")


# Cached, because re-reading a 72 KB file per request buys nothing while the
# results file cannot change underneath a running server. `reload()` drops
# them, so a rebuilt warehouse is picked up without a restart.
load_facts = lru_cache(maxsize=1)(_load_facts)
load_report_markdown = lru_cache(maxsize=1)(_load_report_markdown)


def reload() -> None:
    """Drop the caches, so a rebuilt warehouse is picked up without a restart."""
    _open_connection.cache_clear()
    load_facts.cache_clear()
    load_report_markdown.cache_clear()


# ---------------------------------------------------------------------------
# warehouse-backed queries, for the interactive part of the dashboard
# ---------------------------------------------------------------------------


def execute(operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one of the Phase 4 OLAP operations, read-only."""
    from dwm.olap import OPERATIONS, run_operation

    if operation not in OPERATIONS:
        raise KeyError(
            f"unknown operation {operation!r}; available: {sorted(OPERATIONS)}"
        )
    con = connection()
    return run_operation(con, operation, **(params or {}))


def topics() -> list[str]:
    con = connection()
    return [r[0] for r in con.execute(
        "SELECT topic_name FROM dim_topic ORDER BY topic_name"
    ).fetchall()]


def headline_sample(
    topic: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    """A page of headlines, for the dashboard's browse panel.

    Paged rather than returned whole: the corpus is 3.1 million rows, and an
    endpoint that tried to serialise it would exhaust memory in the client.
    """
    con = connection()
    where = "WHERE f.in_window"
    args: list[Any] = []
    if topic:
        # Bound parameter, never string-formatted into the SQL.
        where += " AND t.topic_name = ?"
        args.append(topic)
    total = con.execute(
        f"SELECT count(*) FROM fact_headline f "
        f"JOIN dim_topic t ON t.topic_key = f.topic_key {where}",
        args,
    ).fetchone()[0]
    rows = con.execute(
        f"""
        SELECT f.publish_date, t.topic_name, f.headline_text,
               f.sentiment_compound, f.sentiment_band, f.sensational_score,
               f.is_risk_signal, f.raw_category
        FROM fact_headline f
        JOIN dim_topic t ON t.topic_key = f.topic_key
        {where}
        ORDER BY f.publish_date DESC, f.headline_id
        LIMIT ? OFFSET ?
        """,
        [*args, limit, offset],
    ).fetchall()
    columns = [
        "publish_date", "topic", "headline_text", "sentiment_compound",
        "sentiment_band", "sensational_score", "is_risk_signal", "raw_category",
    ]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "rows": [dict(zip(columns, r, strict=True)) for r in rows],
    }


def monthly_series(topic: str | None = None) -> list[dict[str, Any]]:
    """Headline count and risk-signal rate per month, for the trend chart."""
    con = connection()
    where = "WHERE 1 = 1"
    args: list[Any] = []
    if topic:
        where += " AND t.topic_name = ?"
        args.append(topic)
    rows = con.execute(
        f"""
        SELECT c.year_month,
               sum(c.headline_count)                                  AS n,
               sum(c.risk_signal_count)                               AS risk,
               sum(c.sum_sentiment_compound)                          AS sent,
               sum(c.sum_sensational_score)                           AS sens
        FROM cube_month_topic c
        JOIN dim_topic t ON t.topic_key = c.topic_key
        {where}
        GROUP BY 1 ORDER BY 1
        """,
        args,
    ).fetchall()
    return [
        {
            "year_month": r[0],
            "headline_count": r[1],
            # Means recomputed from the stored sums, never averaged again.
            "risk_signal_rate": round(r[2] / r[1], 6) if r[1] else None,
            "mean_sentiment": round(r[3] / r[1], 6) if r[1] else None,
            "mean_sensational_score": round(r[4] / r[1], 6) if r[1] else None,
        }
        for r in rows
    ]


def table_counts() -> list[dict[str, Any]]:
    """Every table and its row count, for the warehouse browser."""
    con = connection()
    names = [
        r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
    ]
    out = []
    for name in names:
        count = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        out.append({"table": name, "rows": count})
    return out


def audit_funnel(limit: int = 25) -> list[dict[str, Any]]:
    con = connection()
    columns = [
        "run_id", "dataset_code", "step", "status",
        "rows_read", "rows_loaded", "rows_rejected", "started_at", "finished_at",
    ]
    present = {
        r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'etl_audit'"
        ).fetchall()
    }
    if not present:
        return []
    selected = [c for c in columns if c in present]
    rows = con.execute(
        f"SELECT {', '.join(selected)} FROM etl_audit "
        f"ORDER BY started_at DESC NULLS LAST LIMIT {int(limit)}"
    ).fetchall()
    return [dict(zip(selected, r, strict=True)) for r in rows]
