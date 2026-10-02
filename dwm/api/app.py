"""FastAPI backend (Phase 8): read-only access to the results and the warehouse.

Design constraints, all of them deliberate:

**The API never recomputes a published number.** Everything under `/facts`,
`/report` and `/summary` is read from `facts.json`, which the inference stage
rendered. If this layer ran its own aggregate for a headline figure, the report
and the dashboard would be two unreviewed paths to the same number, and they
would drift.

**Read-only is enforced by the file, not by good intentions.** The DuckDB
handle is opened `read_only=True`, so no malformed request can write to the
warehouse even if validation were bypassed entirely.

**Every response that reports a rate also reports its denominator and its
name.** The project's central honesty rule is that a rate on unlabelled
headlines is a *risk-signal rate*, never a fake-news rate. An API that returned
`{"rate": 0.109}` would strip the word that makes it correct, so the responses
carry `metric_name`, `denominator` and `caution` alongside every value.

**A missing warehouse is 503, not 500.** "You have not built it yet" is a
different situation from "the server is broken", and the message says which
command to run.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from dwm.api import store
from dwm.api.store import DataUnavailable
from dwm.logging_utils import get
from dwm.olap.operations import OPERATIONS

log = get("dwm.api")

app = FastAPI(
    title="dwm-india-news",
    version="1.0.0",
    summary=(
        "Read-only access to a data warehouse built from 3.3M Times of India "
        "headlines, 57k labelled IFND statements and five years of Nifty 50 data."
    ),
    description=__doc__,
)

# The Streamlit dashboard runs on its own port and calls this API, so CORS has
# to be open to localhost. It is restricted to loopback rather than "*" because
# there is no authentication on this service and it holds a file handle open.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501", "http://127.0.0.1:8501",
        "http://localhost:8000", "http://127.0.0.1:8000",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(DataUnavailable)
async def _unavailable(_request, exc: DataUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _guard(fn, *args, **kwargs):
    """Run a store call, turning its failure modes into HTTP status codes."""
    try:
        return fn(*args, **kwargs)
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced to the client
        log.exception("endpoint failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
def health() -> dict[str, Any]:
    """Liveness, and whether the results are actually there.

    A bare `{"ok": true}` would be true on a server with no warehouse behind
    it, which is exactly when a client most needs to be told something is
    wrong.
    """
    state: dict[str, Any] = {
        "status": "ok", "facts": False, "warehouse": False, "snapshot": None,
    }
    try:
        store.load_facts()
        state["facts"] = True
    except DataUnavailable as exc:
        state["status"] = "degraded"
        state["detail"] = str(exc)
    try:
        store.table_counts()
        state["warehouse"] = True
        state["snapshot"] = str(store.snapshot_path())
    except DataUnavailable as exc:
        state["status"] = "degraded"
        state.setdefault("detail", str(exc))
    return state


@app.get("/operations", tags=["meta"])
def operations() -> dict[str, Any]:
    """The ten OLAP operations, with their default parameters."""
    from dwm.olap.operations import DEFAULT_PARAMS

    return {
        "operations": [
            {"name": name, "default_params": DEFAULT_PARAMS.get(name, {})}
            for name in OPERATIONS
        ]
    }


# ---------------------------------------------------------------------------
# the seven research questions
# ---------------------------------------------------------------------------


@app.get("/facts", tags=["facts"])
def all_facts() -> dict[str, Any]:
    """Everything `facts.json` holds. The report quotes this file."""
    return _guard(store.load_facts)


@app.get("/facts/{section}", tags=["facts"])
def fact_section(section: str) -> dict[str, Any]:
    """One section, so a dashboard can load a single panel cheaply."""
    facts = _guard(store.load_facts)
    if section not in facts:
        raise HTTPException(
            status_code=404,
            detail=f"no section {section!r}; available: {sorted(facts)}",
        )
    return {"section": section, "value": facts[section]}


@app.get("/summary", tags=["facts"])
def summary() -> dict[str, Any]:
    """The handful of numbers a reader wants first, with their cautions.

    Each entry keeps the `unit` and `caution` from the fact it came from.
    Dropping them here would be the single easiest way for this API to make
    the project dishonest, since a dashboard showing bare percentages is
    exactly where a risk-signal rate stops being called one.
    """
    facts = _guard(store.load_facts)
    wanted = [
        "corpus", "outcomes", "rq1_topic_mix", "rq2_bursts", "rq3_sensationalism",
        "rq4_clusters", "rq5_association_rules", "rq6_market_association",
        "rq7_classifier", "guards", "honesty_rules",
    ]
    out: dict[str, Any] = {}
    for key in wanted:
        block = facts.get(key)
        if block is None:
            continue
        # `outcomes` is a synthesis, not a measurement, so it has no single
        # fact header. It is returned as bare data and the dashboard renders
        # each outcome's own caution.
        if key == "outcomes":
            out[key] = block
            continue
        fact = block.get("fact") if isinstance(block, dict) else None
        out[key] = {
            "value": fact.get("value") if fact else None,
            "unit": fact.get("unit") if fact else None,
            "caution": fact.get("caution") if fact else None,
            "source": fact.get("source") if fact else "reports/facts.json",
            "data": block,
        }
    out["generated_at"] = facts.get("generated_at")
    out["mining_run_id"] = facts.get("mining_run_id")
    return out


@app.get("/report", response_class=PlainTextResponse, tags=["facts"])
def report_markdown() -> str:
    """The rendered report, exactly as `python -m dwm report` wrote it."""
    return _guard(store.load_report_markdown)


# ---------------------------------------------------------------------------
# warehouse queries
# ---------------------------------------------------------------------------


@app.get("/topics", tags=["query"])
def topic_list() -> dict[str, Any]:
    return {"topics": _guard(store.topics)}


@app.get("/headlines", tags=["query"])
def headlines(
    topic: str | None = Query(default=None, description="Exact topic name."),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """A page of in-window headlines, newest first.

    `limit` is capped at 500. The corpus holds 1.1M in-window rows, and an
    unbounded page would be a denial of service against the client rather than
    a convenience.
    """
    return _guard(store.headline_sample, topic, limit, offset)


@app.get("/series/monthly", tags=["query"])
def series_monthly(topic: str | None = None) -> dict[str, Any]:
    """Monthly counts and rates, for the trend chart.

    Rates are recomputed here as sum ÷ count from the cube's stored sums. The
    cube holds sums, never averages, precisely so this is possible.
    """
    rows = _guard(store.monthly_series, topic)
    return {"topic": topic, "months": len(rows), "rows": rows}


@app.get("/tables", tags=["query"])
def tables() -> dict[str, Any]:
    """Every table with its row count, for the warehouse browser."""
    rows = _guard(store.table_counts)
    return {"tables": rows, "total_rows": sum(r["rows"] for r in rows)}


@app.get("/market/daily", tags=["query"])
def market_daily(topic: str | None = None) -> dict[str, Any]:
    """Paired daily headline-volume and volatility points, for the RQ6 scatter.

    The correlation is the finding, but a coefficient alone hides the shape of
    the cloud behind it, and the shape is what makes the negative slope
    believable. 1,235 points is small enough to return whole.
    """
    return _guard(store.market_daily, topic)


@app.get("/audit", tags=["query"])
def audit(limit: int = Query(default=25, ge=1, le=200)) -> dict[str, Any]:
    """The ingest and ETL funnel, so row counts can be traced to a run."""
    return {"runs": _guard(store.audit_funnel, limit)}


@app.post("/query/reload", tags=["query"])
def reload_caches() -> dict[str, Any]:
    """Re-snapshot the warehouse and drop cached results.

    A POST because it mutates process state and touches the filesystem. It
    cannot write to the warehouse; it copies it and forgets what it had read.
    """
    store.reload()
    return {
        "reloaded": True,
        "snapshot": str(store.snapshot_path()),
        "detail": "warehouse re-snapshotted, cached facts and report dropped",
    }


@app.get("/query/{operation}", tags=["query"])
def run_olap_operation(
    operation: str,
    topic: str | None = None,
    year: int | None = None,
    topic_group: str | None = None,
    n: int = Query(default=10, ge=1, le=200),
) -> dict[str, Any]:
    """Run one of the ten Phase 4 OLAP operations.

    Whitelisted to the named operations. This is the only endpoint that
    executes SQL, and it executes only code this project wrote — the operation
    is never interpolated into a query.
    """
    if operation not in OPERATIONS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown operation {operation!r}; known: {sorted(OPERATIONS)}",
        )
    params: dict[str, Any] = {}
    if topic is not None:
        params["topic"] = topic
    if year is not None:
        params["year"] = year
    if topic_group is not None:
        params["topic_group"] = topic_group
    if operation == "top_months":
        params["n"] = n
    return _guard(store.execute, operation, params)
