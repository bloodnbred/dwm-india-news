"""Inference stage (Phase 7): mining.json -> facts.json -> report.md.

This stage renders. It does not mine, and it does not decide. Its job is to
take results that were computed once, attach to each one the source it came
from and the caution that must travel with it, and then lay them out.

**There is no language model anywhere in this path.** Every sentence in
`report.md` is a template in `dwm/inference/report.py` and every number is a
value in `facts.json`. That is what makes "each number traces to a query"
checkable: a reader who distrusts a number can open the fact, read its
`source`, and run the query.

The gate. The blueprint requires that guard rails fire on small data, so
`check_guards` is not a formality. A missing section, a corpus too small to
support a rate, or a correlation with too few observations is reported as a
failure with its numbers attached, and the CLI prints them. The stage still
writes a report, because a report that says "this could not be measured, and
here is why" is more useful than no report, but it exits non-zero so a
pipeline cannot pass silently on a broken warehouse.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from dwm.config import Settings
from dwm.db import connect
from dwm.inference.facts import build_facts, facts_path, mining_path, write_facts
from dwm.inference.report import render_report, report_path, write_report
from dwm.ingest.audit import ensure_audit_table, new_run_id, record
from dwm.logging_utils import get, step

__all__ = ["run_inference", "load_facts", "mining_path", "facts_path", "report_path"]

log = get("dwm.inference")


def load_facts(path: Any = None) -> dict[str, Any]:
    """Read facts.json back, for the API and the dashboard."""
    target = Path(path) if path else facts_path()
    if not target.exists():
        raise FileNotFoundError(
            f"{target} not found. Run `python -m dwm report` first."
        )
    return json.loads(target.read_text(encoding="utf-8"))


def _mining_ready() -> None:
    path = mining_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m dwm mine` first."
        )


def run_inference(
    settings: Settings, *, con: duckdb.DuckDBPyConnection | None = None
) -> dict[str, Any]:
    """Build facts.json and report.md, then evaluate the gate.

    Pass `con` to reuse an open connection; DuckDB permits one writer per
    file, so a second connection to the warehouse will fail while the first
    is held.
    """
    _mining_ready()
    owned = con is None
    if owned:
        con = connect(settings)
    run_id = new_run_id()
    started = datetime.now(UTC).replace(tzinfo=None)
    try:
        ensure_audit_table(con)

        with step("reading mining results"):
            mining = json.loads(mining_path().read_text(encoding="utf-8"))

        with step("extracting facts"):
            facts = build_facts(con, mining)
            facts_path = write_facts(facts)

        with step("rendering report"):
            report_path = write_report(render_report(facts))

        guards = facts["guards"]
        failed = guards["failed"]
        for check in failed:
            # Loud, not silent. The blueprint's gate exists to make exactly
            # this visible.
            log.warning("guard FAILED %s: %s", check["check"], check["detail"])
        log.info(
            "inference gate: %s of %s checks passed",
            len(guards["checks"]) - len(failed), len(guards["checks"]),
        )

        record(
            con,
            run_id=run_id,
            dataset_code="all",
            step="inference.run",
            info={
                "rows_read": facts["corpus"]["analysis_window"]["headlines_in_window"],
                "rows_loaded": facts["corpus"]["analysis_window"]["headlines_in_window"],
                "rows_rejected": 0,
                "sections": 11,
                "guards_failed": len(failed),
            },
            status="ok" if guards["passed"] else "guard_failed",
            started_at=started,
        )

        return {
            "run_id": run_id,
            "facts_path": str(facts_path),
            "report_path": str(report_path),
            "report_bytes": report_path.stat().st_size,
            "gate_passed": guards["passed"],
            "checks_run": len(guards["checks"]),
            "checks_failed": [c["check"] for c in failed],
            "headline_findings": _headlines(facts),
        }
    finally:
        if owned:
            con.close()


def _headlines(facts: dict[str, Any]) -> dict[str, Any]:
    """The numbers the CLI prints, for a quick check without opening the report."""
    rq2 = facts["rq2_bursts"]
    rq4 = facts["rq4_clusters"]
    rq6 = facts["rq6_market_association"]
    rq7 = facts["rq7_classifier"]
    rq3 = facts["rq3_sensationalism"]
    top = rq3["ranked"][0] if rq3.get("ranked") else None
    return {
        "corpus_headlines": facts["corpus"]["analysis_window"]["headlines_in_window"],
        "volume_bursts": rq2["volume_bursts_found"],
        "max_volume_cv": rq2.get("max_within_year_cv"),
        "cluster_silhouette": rq4.get("silhouette"),
        "association_rules": facts["rq5_association_rules"].get("rule_count"),
        "strongest_market_correlation": (
            rq6["fact"]["value"] if rq6.get("ran") else None
        ),
        "top_risk_topic": top["topic"] if top else None,
        "top_risk_rate": top["risk_signal_rate"] if top else None,
        "classifier_accuracy": rq7.get("metrics", {}).get("accuracy"),
        "classifier_baseline": rq7.get("baseline"),
    }
