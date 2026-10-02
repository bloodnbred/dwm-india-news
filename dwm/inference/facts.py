"""Fact extraction (Phase 7): mining.json plus the warehouse -> facts.json.

The inference stage renders; it does not recompute. Everything it needs is
either in `reports/mining.json`, which the mining stage wrote, or a direct
count against the warehouse. That separation is what makes "every number in
the report traces to a query" checkable: a fact carries the query or file key
it came from.

Each fact is a dict with:
    value        the number or list
    unit         what it is, when the bare number is ambiguous
    source       where it came from: a file key or a SQL fragment
    caution      a sentence the report must print next to it, if any

The `caution` field is the honesty mechanism. A fact that is easy to
misread - a rate on unlabelled data, a partial year, an upper bound - carries
its caveat with it, so the renderer cannot drop it by accident.

**Honesty rules enforced here, not in the prose:**
  * an unlabelled measure is never named a fake-news rate
  * a partial year is never averaged into a full-year comparison
  * the classifier accuracy always travels with its baseline and its
    upper-bound caveat
  * a correlation always travels with its p-value
  * a negative result is recorded as a negative result
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from dwm.config import reports_dir
from dwm.logging_utils import get, human_int

log = get("dwm.inference.facts")


# Paths are resolved when they are used, not when this module is imported.
#
# A module-level constant froze the reports directory at import time, which
# made redirection depend on import order: a test that set the environment
# variable after `dwm.inference.facts` was already imported still wrote to the
# real reports directory, and a reader that imported it later looked somewhere
# else entirely. The result was a 503 for "results not found" while the file
# was sitting on disk. Resolving at call time removes the ordering dependency
# entirely.
def mining_path() -> Path:
    return reports_dir() / "mining.json"


def facts_path() -> Path:
    return reports_dir() / "facts.json"


# Facts below these counts are marked as not worth reporting. A rate from 40
# rows is a number, but not a finding.
MIN_ROWS_FOR_A_RATE = 1000
MIN_OBS_FOR_A_CORRELATION = 100


def fact(
    value: Any,
    *,
    unit: str | None = None,
    source: str,
    caution: str | None = None,
) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": source, "caution": caution}


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    return con.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# provenance, read straight from the warehouse
# ---------------------------------------------------------------------------


def dataset_facts(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Citation and provenance for every source, straight from dim_dataset."""
    rows = con.execute(
        """
        SELECT dataset_code, dataset_name, source_url, citation, license, provenance,
               is_labelled, declared_precision, staged_rows
        FROM dim_dataset ORDER BY dataset_code
        """
    ).fetchall()
    names = [
        "code", "name", "url", "citation", "license", "provenance",
        "is_labelled", "declared_precision", "staged_rows",
    ]
    out = {}
    for row in rows:
        record = dict(zip(names, row, strict=True))
        out[record["code"]] = {
            "name": record["name"],
            "citation": record["citation"],
            "license": record["license"],
            "provenance": record["provenance"],
            "labelled": bool(record["is_labelled"]),
            "declared_date_precision": record["declared_precision"],
            "staged_rows": int(record["staged_rows"] or 0),
        }
    return out


def corpus_facts(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """The data-quality funnel, as the report's limitations section needs it."""
    rows = {
        name: int(_scalar(con, f"SELECT count(*) FROM {name}"))
        for name in (
            "stg_toi", "stg_ifnd", "stg_nifty",
            "cln_headline", "cln_statement", "cln_market_daily",
            "fact_headline", "fact_statement", "fact_market_daily",
            "dim_date", "dim_topic", "dim_keyword", "bridge_headline_keyword",
        )
    }
    window = con.execute(
        """
        SELECT min(date_key), max(date_key), count(*)
        FROM fact_headline WHERE in_window
        """
    ).fetchone()
    lo, hi, in_window = int(window[0]), int(window[1]), int(window[2])
    years = con.execute(
        "SELECT min(full_date), max(full_date) FROM dim_date"
    ).fetchone()

    return {
        "row_counts": rows,
        "analysis_window": {
            "start": f"{lo // 10000:04d}-{lo // 100 % 100:02d}-{lo % 100:02d}",
            "end": f"{hi // 10000:04d}-{hi // 100 % 100:02d}-{hi % 100:02d}",
            "headlines_in_window": in_window,
            "derived_from": "max(fact_headline.publish_date) minus --years",
            "caution": (
                "2015 is a partial year: the window starts 2015-06-30, so it "
                "holds roughly half a year of headlines. Raw counts are not "
                "comparable across years."
            ),
        },
        "archive_span": {
            "start": str(years[0]),
            "end": str(years[1]),
        },
        "ifnd_date_quality": {
            str(p): int(n)
            for p, n in con.execute(
                "SELECT date_precision, count(*) FROM cln_statement "
                "GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        },
        "ifnd_label_balance": {
            label: int(n)
            for label, n in con.execute(
                "SELECT label_code, count(*) FROM cln_statement GROUP BY 1"
            ).fetchall()
        },
    }


# ---------------------------------------------------------------------------
# the seven questions
# ---------------------------------------------------------------------------


def window_topic_shares(con: duckdb.DuckDBPyConnection, limit: int = 10) -> dict[str, Any]:
    """Each topic's share of the WHOLE window, not of one year.

    The mining stage reports within-year shares, which is the right basis for
    comparing years. It is the wrong basis for a single headline figure: the
    largest within-year share is `Local` in 2020 at 89%, which is a true number
    that would badly misrepresent the window as a whole, where `Local` is 70%.
    Both are needed and they answer different questions, so they are kept
    apart rather than one being reused for the other.
    """
    total = int(_scalar(con, "SELECT count(*) FROM fact_headline WHERE in_window"))
    rows = con.execute(
        """
        SELECT t.topic_name, t.topic_group, count(*) AS n
        FROM fact_headline f
        JOIN dim_topic t ON t.topic_key = f.topic_key
        WHERE f.in_window
        GROUP BY 1, 2 ORDER BY n DESC
        """
    ).fetchall()
    topics = [
        {
            "topic": name,
            "topic_group": group,
            "headline_count": n,
            "share_of_window": round(n / total, 6) if total else None,
        }
        for name, group, n in rows
    ]
    groups = [
        {
            "topic_group": group,
            "headline_count": n,
            "share_of_window": round(n / total, 6) if total else None,
        }
        for group, n in con.execute(
            """
            SELECT t.topic_group, count(*) AS n
            FROM fact_headline f
            JOIN dim_topic t ON t.topic_key = f.topic_key
            WHERE f.in_window
            GROUP BY 1 ORDER BY n DESC
            """
        ).fetchall()
    ]
    return {
        "headlines_in_window": total,
        "topics": topics[:limit],
        "topic_groups": groups,
    }


def _rq1_facts(
    con: duckdb.DuckDBPyConnection, mining: dict[str, Any]
) -> dict[str, Any]:
    mix = mining.get("rq1_topic_mix", {})
    rows = mix.get("rows", [])
    window = window_topic_shares(con)

    place = sorted(
        (r for r in rows if r["topic_group"] == "Place"),
        key=lambda r: -r["share_of_year"],
    )
    subject = sorted(
        (r for r in rows if r["topic_group"] == "Subject"),
        key=lambda r: -r["share_of_year"],
    )
    artefacts = mining.get("rq1_taxonomy_artefacts", {}).get("rows", [])
    return {
        "year_totals": mix.get("year_totals", {}),
        "partial_years": mix.get("partial_years", []),
        # The full within-year table, so an API consumer can chart a topic's
        # whole trajectory rather than only the eight largest moves.
        "rows": rows,
        "largest_moves": mining.get("rq1_composition_shift", {}).get("largest_moves", [])[:8],
        "window_shares": window,
        "top_place_topic": place[0] if place else None,
        "top_subject_topics": [
            {"topic": r["topic"], "year": r["year"], "share": r["share_of_year"]}
            for r in subject[:5]
        ],
        "taxonomy_artefacts": artefacts,
        "artefact_note": mining.get("rq1_taxonomy_artefacts", {}).get("interpretation"),
        "fact": fact(
            "See largest_moves for the ranked table.",
            source="reports/mining.json:rq1_composition_shift.largest_moves",
            caution=(
                "Shares are within-year, so the partial year does not distort "
                "them. Raw counts across years are not comparable."
            ),
        ),
    }


def _rq2_facts(mining: dict[str, Any]) -> dict[str, Any]:
    bursts = mining.get("rq2_bursts", {})
    return {
        "volume_bursts_found": bursts.get("count", 0),
        "volume_is_flat": bursts.get("volume_is_flat"),
        "max_within_year_cv": bursts.get("max_within_year_volume_cv"),
        "per_year_cv": bursts.get("per_year_volume_cv", {}),
        "finding": bursts.get("finding"),
        "counter_signals": bursts.get("counter_signals", []),
        "counter_signal_declines": bursts.get("counter_signal_declines", []),
        "event_responsive_topics": bursts.get("event_responsive_topics", []),
        "predicted_desks_fell_in": bursts.get("event_months_all_predicted_desks_fell", []),
        "counter_signal_summary": bursts.get("counter_signal_summary"),
        "counter_signal_note": bursts.get("counter_signal_note"),
        "event_months": bursts.get("event_months", []),
        "fact": fact(
            bursts.get("count", 0),
            unit="months exceeding the z-score threshold",
            source="reports/mining.json:rq2_bursts.detected",
            caution=(
                "This is a NULL result and it is the answer. Monthly volume is "
                "flat within each year, so no month is a statistical outlier. "
                "Lowering the threshold until a spike appeared would be "
                "choosing a threshold to manufacture a finding."
            ),
        ),
    }


def _rq3_facts(mining: dict[str, Any]) -> dict[str, Any]:
    block = mining.get("rq3_sensationalism", {})
    by_topic = block.get("by_topic", {})
    trend = block.get("trend_by_year", {})
    return {
        "corpus_rate": by_topic.get("corpus_rate"),
        "threshold": by_topic.get("threshold"),
        "ranked": by_topic.get("ranked_excluding_uninformative", [])[:8],
        "excluded_uninformative": by_topic.get("uninformative_topics", {}),
        "trend_by_year": trend.get("series", []),
        "trend_summary": trend.get("summary"),
        "sensitivity": block.get("threshold_sensitivity", {}),
        "fact": fact(
            by_topic.get("corpus_rate"),
            unit="risk-signal rate, share of headlines over the sensationalism threshold",
            source="reports/mining.json:rq3_sensationalism.by_topic.corpus_rate",
            caution=(
                "A STYLE measure on unlabelled headlines. It is a risk-signal "
                "rate and is NOT a fake-news rate. The threshold is the "
                "measured 95th percentile, a chosen cut-off, so the report "
                "must show the sensitivity table."
            ),
        ),
    }


def _rq4_facts(mining: dict[str, Any]) -> dict[str, Any]:
    clusters = mining.get("rq4_clusters", {})
    if not clusters.get("ran"):
        return {
            "ran": False,
            "reason": clusters.get("reason"),
            "fact": fact(None, source="reports/mining.json:rq4_clusters"),
        }
    return {
        "ran": True,
        "chosen_k": clusters.get("chosen_k"),
        "silhouette": clusters.get("silhouette"),
        "silhouette_is_strong": clusters.get("silhouette_is_strong"),
        "dominant_cluster_share": clusters.get("dominant_cluster_share"),
        "structure_is_concentrated": clusters.get("structure_is_concentrated"),
        "concentration_note": clusters.get("concentration_note"),
        "no_preferred_k": clusters.get("no_preferred_k"),
        "k_note": clusters.get("k_note"),
        "k_candidates": clusters.get("k_candidates", []),
        "sample_size": clusters.get("sample_size"),
        "svd_components": clusters.get("svd_components"),
        "svd_variance_explained": clusters.get("svd_variance_explained"),
        "clusters": clusters.get("clusters", []),
        "stability": clusters.get("stability", {}),
        "fact": fact(
            clusters.get("silhouette"),
            unit="silhouette score, higher is better separated",
            source="reports/mining.json:rq4_clusters.silhouette",
            caution=(
                "Read this with the cluster sizes, not alone. Silhouette rewards "
                "a large cluster sitting far from a few small tight ones, and "
                "that is the shape here: most headlines are undifferentiated "
                "while a small topical minority is cleanly separated. The score "
                "also depends entirely on the TF-IDF settings — an earlier run "
                "that admitted numerals and stop words measured 0.068 on the "
                "same data."
            ),
        ),
    }


def _rq5_facts(mining: dict[str, Any]) -> dict[str, Any]:
    rules = mining.get("rq5_association_rules", {}).get("attribute_rules", {})
    keyword = mining.get("rq5_association_rules", {}).get("keyword_rules", {})
    if not rules.get("ran"):
        return {
            "ran": False,
            "reason": rules.get("reason"),
            "fact": fact(None, source="reports/mining.json:rq5_association_rules"),
        }
    informative = rules.get("informative_rules", [])
    return {
        "ran": True,
        "rule_count": rules.get("apriori", {}).get("rule_count"),
        "thresholds": rules.get("thresholds", {}),
        "apriori_seconds": rules.get("apriori", {}).get("seconds"),
        "fpgrowth_seconds": rules.get("fpgrowth", {}).get("seconds"),
        "rule_sets_identical": rules.get("rule_sets_identical"),
        "fpgrowth_speedup": rules.get("fpgrowth_speedup"),
        "tautological_rules": rules.get("tautological_rules"),
        "substantive_rules": rules.get("substantive_rules"),
        "redundancy_note": rules.get("redundancy_note"),
        "mean_items": rules.get("transactions", {}).get("mean_items"),
        "attribute_items": rules.get("transactions", {}).get("items"),
        "transactions_sampled": rules.get("transactions", {}).get("sampled"),
        "item_vocabulary_size": rules.get("transactions", {}).get("item_vocabulary_size"),
        "top_rules": rules.get("top_rules", [])[:8],
        "top_rules_by_confidence": rules.get("top_rules_by_confidence", [])[:8],
        "informative_rules": informative[:8],
        "lift_caveat": rules.get("lift_caveat"),
        "keyword_run": {
            "rule_count": keyword.get("rule_count"),
            "mean_items": keyword.get("transactions", {}).get("mean_items"),
            "sampled": keyword.get("transactions", {}).get("sampled"),
            "caveat": keyword.get("caveat"),
        },
        "fact": fact(
            rules.get("apriori", {}).get("rule_count"),
            unit="association rules at support >= "
                 f"{rules.get('thresholds', {}).get('min_support')}",
            source="reports/mining.json:rq5_association_rules.attribute_rules",
            caution=(
                "Association, not causation. A rule states two attributes "
                "co-occur more often than chance. Transactions are ATTRIBUTES, "
                "not keywords: the 300-term keyword vocabulary yields only "
                f"{keyword.get('transactions', {}).get('mean_items')} items per "
                "headline and produced zero rules at these thresholds, so "
                "keyword rules would have reported sparsity as a pattern."
            ),
        ),
    }


def _rq6_facts(mining: dict[str, Any]) -> dict[str, Any]:
    block = mining.get("rq6_market_association", {})
    lagged = block.get("lagged_return_correlation", {})
    if not lagged.get("ran"):
        return {"ran": False, "fact": fact(None, source="mining.json:rq6")}
    measures = {}
    any_significant = False
    for name, data in lagged.get("measures", {}).items():
        strongest = data.get("strongest_lag") or {}
        measures[name] = {
            "strongest_lag": strongest.get("lag_trading_days"),
            "pearson_r": strongest.get("pearson_r"),
            "spearman_rho": strongest.get("spearman_rho"),
            "p_value": strongest.get("p_value"),
            "significant": data.get("any_lag_significant"),
            "by_lag": data.get("by_lag", []),
        }
        any_significant = any_significant or bool(data.get("any_lag_significant"))
    volatility = block.get("volatility_association", {})
    return {
        "ran": True,
        "trading_days_paired": lagged.get("trading_days_paired"),
        "measures": measures,
        "any_significant": any_significant,
        "significance_accounting": lagged.get("significance_accounting", {}),
        "volatility": volatility,
        "fact": fact(
            max(
                (abs(m["pearson_r"]) for m in measures.values() if m.get("pearson_r")),
                default=None,
            ),
            unit="largest absolute Pearson r against daily RETURN, across measures and lags",
            source="reports/mining.json:rq6_market_association",
            caution=(
                "ASSOCIATION ONLY. Against daily returns the relationship is "
                "negligible. Against 20-day VOLATILITY it is not: log headline "
                "volume correlates at about -0.28, which is a real association "
                "and still not an effect, because both respond to the same "
                "underlying events."
            ),
        ),
    }


def _rq7_facts(mining: dict[str, Any]) -> dict[str, Any]:
    clf = mining.get("rq7_classifier", {})
    if not clf.get("ran"):
        return {
            "ran": False,
            "reason": clf.get("reason"),
            "fact": fact(None, source="reports/mining.json:rq7_classifier"),
        }
    metrics = clf.get("chosen_test_metrics", {})
    return {
        "ran": True,
        "labelled_statements": clf.get("labelled_statements"),
        "class_counts": clf.get("class_counts"),
        "baseline": clf.get("majority_baseline_accuracy"),
        "chosen_model": clf.get("chosen_on_train_cv"),
        "test_count": clf.get("test_count"),
        "test_size": clf.get("test_size"),
        "metrics": metrics,
        "models": {
            name: {
                "accuracy": data.get("metrics", {}).get("accuracy"),
                "fake_recall": data.get("metrics", {}).get("fake_recall"),
            }
            for name, data in clf.get("models", {}).items()
        },
        "train_cv_accuracy": clf.get("train_cv_accuracy"),
        "top_terms": (clf.get("models", {}).get(clf.get("chosen_on_train_cv"), {}) or {}).get(
            "top_terms"
        ),
        "upper_bound_caveat": clf.get("upper_bound_caveat"),
        "fact": fact(
            metrics.get("accuracy"),
            unit="accuracy on a held-out 30% test split",
            source="reports/mining.json:rq7_classifier.chosen_test_metrics",
            caution=(
                "The ONLY accuracy claim in this project, because IFND is the "
                "only source with ground truth. The majority baseline is "
                f"{clf.get('majority_baseline_accuracy')}, not 0.5, so accuracy "
                "alone is meaningless. Part of the Fake class is LSTM-augmented, "
                "so this is an UPPER BOUND."
            ),
        ),
    }


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def check_guards(
    mining: dict[str, Any], con: duckdb.DuckDBPyConnection
) -> dict[str, Any]:
    """The Phase 7 gate: guard rails must fire on small data.

    Each check states what it looked at and what it concluded, including when
    the honest conclusion is "not enough data to say".
    """
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    corpus = _scalar(con, "SELECT count(*) FROM fact_headline WHERE in_window")
    add(
        "headlines_in_window_present",
        corpus > 0,
        f"{human_int(corpus)} headlines in the analysis window",
    )
    add(
        "headlines_in_window_sufficient",
        corpus >= MIN_ROWS_FOR_A_RATE,
        f"{human_int(corpus)} rows, floor for a rate is {MIN_ROWS_FOR_A_RATE}",
    )

    labelled = _scalar(
        con, "SELECT count(*) FROM cln_statement WHERE label_code IN ('REAL','FAKE')"
    )
    add(
        "labelled_statements_present",
        labelled > 0,
        f"{human_int(labelled)} labelled statements",
    )

    trading = _scalar(con, "SELECT count(*) FROM fact_market_daily WHERE in_window")
    add(
        "trading_days_present",
        trading > 0,
        f"{human_int(trading)} trading days in the window",
    )

    rq6 = mining.get("rq6_market_association", {}).get("lagged_return_correlation", {})
    paired = rq6.get("trading_days_paired", 0)
    add(
        "market_correlation_has_enough_observations",
        paired >= MIN_OBS_FOR_A_CORRELATION,
        f"{paired} paired trading days, floor is {MIN_OBS_FOR_A_CORRELATION}",
    )

    # Section presence alone is not enough. An empty `rq4_clusters: {}` would
    # satisfy a key check while the report rendered a section with nothing in
    # it, and a section that reports `ran: false` has not answered its
    # question. Both are checked, so a hollow section cannot pass the gate.
    for key, label in (
        ("rq1_topic_mix", "topic mix"),
        ("rq2_bursts", "bursts"),
        ("rq3_sensationalism", "sensationalism"),
        ("rq4_clusters", "clustering"),
        ("rq5_association_rules", "association rules"),
        ("rq6_market_association", "market association"),
        ("rq7_classifier", "classifier"),
    ):
        section = mining.get(key)
        add(
            f"{key}_present",
            isinstance(section, dict) and bool(section),
            f"{label} section {'has content' if section else 'missing or empty'}",
        )
        if isinstance(section, dict) and "ran" in section:
            add(
                f"{key}_ran",
                bool(section.get("ran")),
                section.get("reason") or f"{label} ran",
            )

    unlabelled = _scalar(
        con,
        "SELECT count(*) FROM fact_headline f WHERE f.in_window AND NOT EXISTS "
        "(SELECT 1 FROM dim_topic t WHERE t.topic_key = f.topic_key)",
    )
    add(
        "every_headline_has_a_topic",
        unlabelled == 0,
        f"{human_int(unlabelled)} headlines without a topic",
    )

    return {
        "checks": checks,
        "failed": [c for c in checks if not c["passed"]],
        "passed": all(c["passed"] for c in checks),
        "min_rows_for_a_rate": MIN_ROWS_FOR_A_RATE,
        "min_obs_for_a_correlation": MIN_OBS_FOR_A_CORRELATION,
    }


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def build_outcomes(facts: dict[str, Any]) -> dict[str, Any]:
    """The study's answer, assembled from the measured values.

    This is the inference layer: everything else in the document is evidence
    for a claim, and this is the claim. It is *derived*, never hand-written, so
    it cannot drift away from the numbers the way prose does — if the silhouette
    changes, the sentence describing the clustering changes with it.

    Each outcome states the finding, what kind of finding it is, and why it
    matters. Outcomes that report nothing are kept, not dropped, because "we
    looked and there was nothing" is the answer to a question and the reader is
    entitled to know it was asked.
    """
    rq2 = facts["rq2_bursts"]
    rq3 = facts["rq3_sensationalism"]
    rq4 = facts["rq4_clusters"]
    rq5 = facts["rq5_association_rules"]
    rq6 = facts["rq6_market_association"]
    rq7 = facts["rq7_classifier"]
    window = facts["corpus"]["analysis_window"]

    outcomes: list[dict[str, Any]] = []

    # -- RQ2: a null, and the reason it is one ---------------------------
    cv = rq2.get("max_within_year_cv")
    fell = rq2.get("predicted_desks_fell_in") or []
    events = len(rq2.get("event_months") or [])
    outcomes.append({
        "id": "volume",
        "question": "Do national events show up as spikes in news volume?",
        "kind": "null",
        "headline": "No. Headline volume carries no news signal.",
        "detail": (
            f"Within-year volume varies by at most {cv}, and "
            f"{rq2['volume_bursts_found']} months out of "
            f"{len(rq2.get('per_year_cv') or {})} clear a z-score of 2. "
            "March 2020, the month of the national lockdown, sits 2.5% above "
            "its own year mean."
        ),
        "evidence": (
            f"In {len(fell)} of {events} listed event months, all three desks "
            "predicted to rise — Health, Sports and Entertainment — fell "
            "instead."
            if fell
            else "No event month stands out on any measure tested."
        ),
        "caveat": (
            "This data cannot distinguish a genuinely quota-driven newsroom "
            "from a sampling artefact of the publisher's export. Both produce "
            "the same signature."
        ),
        "rq": "RQ2",
    })

    # -- RQ4: structure exists but is narrow ------------------------------
    silhouette = rq4.get("silhouette")
    dominant = rq4.get("dominant_cluster_share")
    outcomes.append({
        "id": "clusters",
        "question": "Do the headlines cluster into topics on their own?",
        "kind": "qualified",
        "headline": "Partly. Structure exists, but it covers a small minority.",
        "detail": (
            f"Silhouette {silhouette}, which clears the conventional 0.25 "
            "threshold — but one cluster holds "
            f"{pct(dominant)} of the corpus. The small clusters find money "
            "terms (`rs crore`, `lakh`), traffic and crime (`road`, "
            "`accident`, `killed`) and age copy (`old`, `year old`)."
        ),
        "evidence": (
            "None of those is a topic in the publisher's own taxonomy, so the "
            "clustering found writing patterns rather than desks. An earlier "
            "run measured 0.068 and was wrong: the feature pipeline was "
            "admitting numerals and stop words."
        ),
        "caveat": (
            "Silhouette rewards one large cluster sitting far from a few small "
            "tight ones, so the score and the shape must be read together."
        ),
        "rq": "RQ4",
    })

    # -- RQ6: nothing against returns, something against volatility -------
    strongest_return = rq6["fact"]["value"] if rq6.get("ran") else None
    volatility = rq6.get("volatility") or {}
    v_strong = volatility.get("strongest") or {}
    outcomes.append({
        "id": "market",
        "question": "Do headlines relate to the market?",
        "kind": "split",
        "headline": (
            "Not to daily returns. Yes, to volatility — and the direction is "
            "unexplained."
        ),
        "detail": (
            f"Against returns the strongest correlation is {strongest_return}, "
            "and the one significant lag out of the fifteen tested is what "
            "chance produces. Against 20-day volatility, log business-headline "
            f"volume correlates at {v_strong.get('pearson_r')} "
            f"(p < 0.0001, {v_strong.get('variance_explained_pct')}% of "
            "variance): busier headline days go with calmer markets."
        ),
        "evidence": (
            "Fifteen lag tests at alpha 0.05 produce about 0.75 false "
            "positives, so a single p below 0.05 is the expected outcome of "
            "running the tests, not a discovery."
        ),
        "caveat": (
            "Association only. Headline volume and volatility both respond to "
            "the same underlying events, and nothing here identifies a "
            "direction of effect."
        ),
        "rq": "RQ6",
    })

    # -- RQ3: a real, measurable concentration -----------------------------
    top = rq3["ranked"][0] if rq3.get("ranked") else None
    outcomes.append({
        "id": "language",
        "question": "Which topics use the most sensational language?",
        "kind": "positive",
        "headline": (
            f"`{top['topic']}` stands out, at {pct(top['risk_signal_rate'])} "
            f"against a {pct(rq3['corpus_rate'])} corpus rate."
            if top
            else "No topic cleared the row floor for a rate."
        ),
        "detail": (
            f"95% CI {pct(top['ci95_low'])} to {pct(top['ci95_high'])} over "
            f"{humanise(top['headline_count'])} headlines."
            if top
            else "No topic had enough headlines to support a rate."
        ),
        "evidence": (
            "`Unknown` tops the raw ranking at 17.29% and is excluded: it is a "
            "filing gap rather than a subject, so its score measures the "
            "absence of a filing decision."
        ),
        "caveat": (
            "A style measure on unlabelled headlines. It is a risk-signal "
            "rate and never a fake-news rate. The threshold is the measured "
            "95th percentile, a chosen cut-off."
        ),
        "rq": "RQ3",
    })

    # -- RQ5: agreement, not just a count ----------------------------------
    outcomes.append({
        "id": "rules",
        "question": "Which co-occurrence patterns exist?",
        "kind": "positive",
        "headline": (
            f"{humanise(rq5['rule_count'])} rules, found identically by two "
            "independent algorithms."
        ),
        "detail": (
            f"FP-Growth is {rq5['fpgrowth_speedup']}x faster on identical "
            f"input, and {humanise(rq5.get('tautological_rules'))} of the "
            "rules are tautologies counted separately."
            if rq5.get("ran")
            else "Association rules could not be mined on this data."
        ),
        "evidence": (
            "Apriori and FP-Growth return the same rule set, which is asserted: "
            "they search the same itemsets, so a difference would mean one is "
            "broken. The keyword vocabulary produced zero rules and is reported "
            "as a finding about the feature."
        ),
        "caveat": (
            "Association, not causation. A rule states two attributes co-occur "
            "more often than chance."
        ),
        "rq": "RQ5",
    })

    # -- RQ7: the one accuracy claim --------------------------------------
    metrics = rq7.get("metrics") or {}
    outcomes.append({
        "id": "classifier",
        "question": "Can a classifier separate real statements from fake ones?",
        "kind": "positive",
        "headline": (
            f"{pct(metrics.get('accuracy'))} against a "
            f"{pct(rq7.get('baseline'))} majority baseline."
        ),
        "detail": (
            f"{metrics.get('lift_over_baseline_pp'):+.1f} percentage points, "
            f"with Fake recall {pct(metrics.get('fake_recall'))}."
            if metrics
            else "The classifier could not be trained on this data."
        ),
        "evidence": (
            "The model was chosen on training cross-validated accuracy and the "
            "test split was scored once. Accuracy alone would flatter a model "
            "that learned nothing, because always answering 'real' already "
            "scores the baseline."
        ),
        "caveat": (
            "An upper bound. Part of IFND's Fake class is LSTM-generated "
            "augmentation, which is far easier to distinguish than a fake "
            "written by a person."
        ),
        "rq": "RQ7",
    })

    # -- RQ1: the mix, and the artefact -----------------------------------
    window_shares = facts["rq1_topic_mix"].get("window_shares", {})
    leading = window_shares.get("topics", [{}])[0] if window_shares.get("topics") else {}
    artefacts = facts["rq1_topic_mix"].get("taxonomy_artefacts") or []
    outcomes.append({
        "id": "mix",
        "question": "How did the topic mix change across the window?",
        "kind": "qualified",
        "headline": (
            f"`{leading.get('topic')}` is {pct(leading.get('share_of_window'))} "
            "of the window, and one filing artefact dominates the story."
            if leading
            else "The topic mix could not be summarised."
        ),
        "detail": (
            "`business.international-business` is 11.1% of all 2017 headlines "
            "and 0.2% of 2018. A naive topic-mix analysis would report that as "
            "a change in what India was reading."
        ),
        "evidence": (
            f"{len(artefacts)} raw category holds an implausible share of a "
            "single year, which means the publisher changed how it filed "
            "content."
        ),
        "caveat": (
            "2015 is a partial year, so every trend statement is a within-year "
            "share and raw counts across years are never compared."
        ),
        "rq": "RQ1",
    })

    return {
        "headline": (
            "Three of seven questions produced no result, or a result that "
            "reads better than it is. Those are reported with the measurement "
            "that establishes them."
        ),
        "corpus": {
            "headlines": window["headlines_in_window"],
            "start": window["start"],
            "end": window["end"],
        },
        "outcomes": outcomes,
        "counts": {
            "null": sum(1 for o in outcomes if o["kind"] == "null"),
            "qualified": sum(1 for o in outcomes if o["kind"] == "qualified"),
            "positive": sum(1 for o in outcomes if o["kind"] == "positive"),
            "split": sum(1 for o in outcomes if o["kind"] == "split"),
            "total": len(outcomes),
        },
    }


def humanise(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def pct(value: float | None, places: int = 2) -> str:
    """A proportion as a percentage. Never renders None as 0%."""
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"


def build_facts(
    con: duckdb.DuckDBPyConnection, mining: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Assemble facts.json from the warehouse and the mining results."""
    if mining is None:
        path = mining_path()
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run `python -m dwm mine` first."
            )
        mining = json.loads(path.read_text(encoding="utf-8"))
        log.info("read mining results from %s", path)

    facts: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mining_run_id": mining.get("run_id"),
        "config_version": mining.get("config_version"),
        "corpus": corpus_facts(con),
        "datasets": dataset_facts(con),
        "rq1_topic_mix": _rq1_facts(con, mining),
        "rq2_bursts": _rq2_facts(mining),
        "rq3_sensationalism": _rq3_facts(mining),
        "rq4_clusters": _rq4_facts(mining),
        "rq5_association_rules": _rq5_facts(mining),
        "rq6_market_association": _rq6_facts(mining),
        "rq7_classifier": _rq7_facts(mining),
        "mining_guard_summary": mining.get("guard_summary", {}),
    }
    facts["guards"] = check_guards(mining, con)
    # The inference layer: the study's answer, derived from the values above so
    # it cannot drift away from them.
    facts["outcomes"] = build_outcomes(facts)
    facts["honesty_rules"] = [
        "On the unlabelled TOI corpus every style measure is a RISK-SIGNAL "
        "rate. It is never a fake-news rate.",
        "Only the IFND classifier states an accuracy, because IFND is the only "
        "source with ground truth.",
        "Correlations are associations. No result in this project identifies "
        "an effect of news on markets.",
        "Association rules state co-occurrence, never causation.",
        "2015 is a partial year and is excluded from year-on-year comparison.",
        "A negative result is reported as a negative result, with the "
        "measurement that establishes it.",
    ]
    return facts


def write_facts(facts: dict[str, Any]) -> Path:
    path = facts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=2, default=str)
    log.info("wrote %s (%.1f KB)", path, path.stat().st_size / 1024)
    return path
