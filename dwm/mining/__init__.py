"""Mining stage (Phases 5-6): the seven research questions.

Each question maps to one module:

    RQ1  topic mix over the window        trends.topic_mix_by_year
    RQ2  which months spike               trends.detect_bursts
    RQ3  which categories sensational     sensationalism.run_sensationalism
    RQ4  natural topic clusters           clustering.run_clustering
    RQ5  co-occurrence rules              rules.run_rules
    RQ6  headlines vs Nifty               market.run_market
    RQ7  Real vs Fake classifier          classifier.run_classifier

Results are written to `reports/mining.json` and summarised in the returned
dict, so the inference stage can quote every number from a file rather than
recomputing it.

Rules held across every module:

  * a rate is never reported without its denominator
  * a statistic from too few observations is refused, with a stated reason
  * unlabelled measures are never called a fake-news rate
  * correlations are associations, never effects
  * every seed is fixed, so a re-run reproduces the same numbers
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from dwm.config import PROJECT_ROOT, Settings
from dwm.db import connect
from dwm.ingest.audit import ensure_audit_table, new_run_id, record
from dwm.logging_utils import get, human_int, step
from dwm.mining import (
    classifier,
    clustering,
    market,
    rules,
    sensationalism,
    trends,
)

__all__ = ["run_mining", "MINING_YAML", "load_mining_config"]

log = get("dwm.mining")

MINING_YAML = PROJECT_ROOT / "config" / "mining.yaml"
OUTPUT_PATH = PROJECT_ROOT / "reports" / "mining.json"

# Which research question each section answers, and which module owns it.
SECTIONS = {
    "rq1_topic_mix": "How did the topic mix of Indian headlines change over the five-year window?",
    "rq2_bursts": "Which months spike in volume, and which known events do they coincide with?",
    "rq3_sensationalism": "Which categories use the most sensational or negative language, and how did that trend?",
    "rq4_clusters": "What natural topic clusters exist in the headlines?",
    "rq5_association_rules": "Which co-occurrence patterns exist in the headlines?",
    "rq6_market_association": "Does business headline sentiment or volume relate to Nifty returns or volatility?",
    "rq7_classifier": "How well does a classifier separate Real from Fake, compared with the majority baseline?",
}


def load_mining_config(path: Path | None = None) -> dict[str, Any]:
    import yaml

    path = path or MINING_YAML
    if not path.exists():
        raise FileNotFoundError(f"missing mining config: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _facts_ready(con: duckdb.DuckDBPyConnection) -> None:
    needed = ("fact_headline", "fact_statement", "fact_market_daily", "cube_month_topic")
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    missing = [t for t in needed if t not in present]
    if missing:
        raise RuntimeError(
            f"missing {missing}. Run `python -m dwm build` before `python -m dwm mine`."
        )


def _in_window_rows(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {
        "headline_in_window": int(
            con.execute("SELECT count(*) FROM fact_headline WHERE in_window").fetchone()[0]
        ),
        "statement_labelled": int(
            con.execute(
                "SELECT count(*) FROM fact_statement WHERE label_code IN ('REAL','FAKE')"
            ).fetchone()[0]
        ),
        "market_in_window": int(
            con.execute("SELECT count(*) FROM fact_market_daily WHERE in_window").fetchone()[0]
        ),
    }


def run_mining(
    settings: Settings, *, con: duckdb.DuckDBPyConnection | None = None
) -> dict[str, Any]:
    """Run every mining module and write reports/mining.json.

    Pass `con` to reuse an existing connection; DuckDB allows one writer per
    file, so a second connection to the warehouse will fail.
    """
    owned = con is None
    if owned:
        con = connect(settings)
    started = datetime.now(UTC).replace(tzinfo=None)
    try:
        _facts_ready(con)
        ensure_audit_table(con)
        config = load_mining_config()
        run_id = new_run_id()

        corpus = _in_window_rows(con)
        log.info(
            "mining over %s in-window headlines, %s labelled statements, %s trading days",
            human_int(corpus["headline_in_window"]),
            human_int(corpus["statement_labelled"]),
            human_int(corpus["market_in_window"]),
        )

        with step("RQ1-RQ2 trends and bursts"):
            trend_results = trends.run_trends(con, config)

        with step("RQ3 sensationalism by category"):
            sens_results = sensationalism.run_sensationalism(con, config)

        with step("RQ4 clustering"):
            cluster_results = clustering.run_clustering(con, config)

        with step("RQ5 association rules"):
            rule_results = rules.run_rules(con, config)

        with step("RQ6 headline-market association"):
            market_results = market.run_market(con, config)

        with step("RQ7 classifier"):
            classifier_results = classifier.run_classifier(con, config)

        results: dict[str, Any] = {
            "run_id": run_id,
            "generated_at": started.isoformat(),
            "config_version": config.get("version"),
            "corpus": corpus,
            "questions": SECTIONS,
            "rq1_topic_mix": trend_results["topic_mix"],
            "rq1_composition_shift": trend_results["composition_shift"],
            "rq1_taxonomy_artefacts": trend_results["taxonomy_artefacts"],
            "rq2_monthly_series": trend_results["monthly_series"],
            "rq2_bursts": trend_results["bursts"],
            "rq3_sensationalism": sens_results,
            "rq4_clusters": cluster_results,
            "rq5_association_rules": rule_results,
            "rq6_market_association": market_results,
            "rq7_classifier": classifier_results,
        }
        results["guard_summary"] = _guard_summary(results)

        _write(results, settings)
        info = {
            "rows_read": sum(corpus.values()),
            "rows_loaded": sum(corpus.values()),
            "rows_rejected": 0,
            "sections": len(SECTIONS),
            "guards_failed": len(results["guard_summary"]["failed"]),
        }
        record(
            con, run_id=run_id, dataset_code="all", step="mining.run",
            info=info, status="ok", started_at=started,
        )
        return {
            "run_id": run_id,
            "corpus": corpus,
            "sections": len(SECTIONS),
            "guard_summary": results["guard_summary"],
            "headline_findings": _headlines(results),
            "output": str(settings.reports_dir() / "mining.json")
            if hasattr(settings, "reports_dir")
            else str(OUTPUT_PATH),
        }
    finally:
        if owned:
            con.close()


def _guard_summary(results: dict[str, Any]) -> dict[str, Any]:
    """Collect every guard check across the sections into one place.

    A failed guard is not necessarily an error: clustering refusing to run on
    too little data is the guard working. What matters is that a reader can
    see which results are conditional.
    """
    checks: list[dict[str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "check" in node and "passed" in node:
                checks.append({**node, "path": path})
                return
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node[:50]):
                walk(value, f"{path}[{i}]")

    for key, value in results.items():
        if key in ("questions", "guard_summary"):
            continue
        walk(value, key)
    return {
        "total": len(checks),
        "passed": sum(1 for c in checks if c["passed"]),
        "failed": [c for c in checks if not c["passed"]],
    }


def _headlines(results: dict[str, Any]) -> dict[str, Any]:
    """The few numbers the report will lead with, extracted for the CLI."""
    out: dict[str, Any] = {}
    sens = results["rq3_sensationalism"]["by_topic"]
    out["risk_signal_rate_corpus"] = sens["corpus_rate"]
    # The headline uses the ranking with the uninformative topics removed:
    # `Unknown` tops the raw list because it is a filing gap, not a subject.
    candidates = sens["distinguishable_excluding_uninformative"] or sens[
        "distinguishable_from_corpus"
    ]
    if candidates:
        top = candidates[0]
        out["most_sensational_topic"] = {
            "topic": top["topic"],
            "rate": top["risk_signal_rate"],
            "ci95": [top["ci95_low"], top["ci95_high"]],
            "n": top["headline_count"],
        }
    bursts = results["rq2_bursts"]
    out["volume_bursts"] = bursts["count"]
    out["volume_is_flat"] = bursts["volume_is_flat"]
    out["max_within_year_volume_cv"] = bursts["max_within_year_volume_cv"]
    out["event_counter_signals"] = len(bursts["counter_signals"])
    clusters = results.get("rq4_clusters", {})
    if clusters.get("ran"):
        out["clusters"] = {
            "k": clusters["chosen_k"],
            "silhouette": clusters["silhouette"],
            "strong": clusters["silhouette_is_strong"],
        }
    rules = results.get("rq5_association_rules", {}).get("attribute_rules", {})
    if rules.get("ran"):
        out["association_rules"] = {
            "count": rules["apriori"]["rule_count"],
            "identical_across_algorithms": rules["rule_sets_identical"],
            "fpgrowth_speedup": rules["fpgrowth_speedup"],
        }
    clf = results.get("rq7_classifier", {})
    if clf.get("ran"):
        out["classifier"] = {
            "model": clf["chosen_on_train_cv"],
            "accuracy": clf["chosen_test_metrics"]["accuracy"],
            "baseline": clf["majority_baseline_accuracy"],
            "lift_pp": clf["chosen_test_metrics"]["lift_over_baseline_pp"],
            "fake_recall": clf["chosen_test_metrics"]["fake_recall"],
        }
    return out


def _write(results: dict[str, Any], settings: Settings) -> Path:
    """Persist results so the report quotes a file rather than recomputing."""
    from dwm.config import reports_dir

    directory = reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "mining.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)
    log.info("wrote %s (%.1f KB)", path, path.stat().st_size / 1024)
    return path
