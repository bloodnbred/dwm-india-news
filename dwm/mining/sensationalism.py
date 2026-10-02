"""Sensationalism by category (RQ3).

Asks which topics use the most sensational or negative language, and how that
changed. Three things this module refuses to do.

**It does not report a rate without a denominator.** A topic with 4 headlines
has a rate, but the rate is noise, so topics below `min_topic_rows` are
excluded from the ranking and listed separately with their counts.

**It does not present one threshold as if it were a fact.** The cut-off at
0.2208 is the measured 95th percentile, which is a judgement. The full
sensitivity table is returned so the report can show how the ranking behaves
across the range, and whether it is stable.

**It does not call any of this a fake-news rate.** These headlines have no
labels. This is a risk-signal rate: a share of headlines whose *style* trips
the sensationalism measure. Only IFND carries ground truth, and only the
classifier in `dwm/mining/classifier.py` may make an accuracy claim.

A confidence interval is attached to each rate. Headline counts here are in
the tens of thousands, so a naive standard error would be misleadingly small;
the Wilson interval is used because it stays sensible at extreme proportions,
which is exactly the regime for the highest-scoring topics.
"""

from __future__ import annotations

import math
from typing import Any

import duckdb

from dwm.logging_utils import get, human_int

log = get("dwm.mining.sensationalism")


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Preferred over the normal approximation because the sensationalism rate
    sits near 0 or 1 for some topics, where the normal interval runs outside
    [0, 1] and becomes meaningless.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = (
        z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
        / denominator
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def sensationalism_by_topic(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """Rank topics by risk-signal rate, with counts and intervals."""
    cfg = config.get("sensationalism", {})
    threshold = float(cfg.get("threshold", 0.2208))
    min_rows = int(cfg.get("min_topic_rows", 1000))

    rows = con.execute(
        """
        SELECT
            t.topic_name,
            t.topic_group,
            count(*)                                             AS n,
            count(*) FILTER (WHERE f.is_sensational)             AS sensational,
            count(*) FILTER (WHERE f.is_risk_signal)             AS risk_signal,
            count(*) FILTER (WHERE f.sentiment_band = 'negative') AS negative,
            count(*) FILTER (WHERE f.sentiment_band = 'positive') AS positive,
            sum(f.sentiment_compound)                            AS sum_sentiment,
            sum(f.caps_token_ratio)                              AS sum_caps_ratio,
            sum(f.exclamation_count)                             AS sum_exclam,
            sum(f.superlative_count)                             AS sum_superl,
            sum(f.urgency_count)                                 AS sum_urgency
        FROM fact_headline f
        JOIN dim_topic t ON t.topic_key = f.topic_key
        WHERE f.in_window
        GROUP BY 1, 2
        ORDER BY n DESC
        """
    ).fetchall()

    included, excluded = [], []
    for (
        topic, group, n, sens, risk, negative, positive,
        sum_sent, caps, exclam, superl, urgency,
    ) in rows:
        if not n:
            continue
        rate = risk / n
        low, high = wilson_interval(risk, n)
        record = {
            "topic": topic,
            "topic_group": group,
            "headline_count": n,
            "risk_signal_count": risk,
            "risk_signal_rate": round(rate, 6),
            "ci95_low": round(low, 6),
            "ci95_high": round(high, 6),
            "sensational_count": sens,
            "negative_count": negative,
            "negative_rate": round(negative / n, 6),
            "positive_count": positive,
            "positive_rate": round(positive / n, 6),
            "mean_sentiment": round(sum_sent / n, 6),
            # The sub-signals, so a reader can see WHICH cue is driving a
            # topic's score rather than only that it is high.
            "mean_caps_ratio": round(caps / n, 6),
            "mean_exclamations": round(exclam / n, 6),
            "mean_superlatives": round(superl / n, 6),
            "mean_urgency_words": round(urgency / n, 6),
            "meets_min_rows": n >= min_rows,
        }
        (included if n >= min_rows else excluded).append(record)

    included.sort(key=lambda r: -r["risk_signal_rate"])
    excluded.sort(key=lambda r: -r["headline_count"])

    # Only include topics whose interval excludes the corpus-wide rate, so the
    # ranking says something rather than ordering noise.
    total = sum(r["headline_count"] for r in included)
    overall = (
        sum(r["risk_signal_count"] for r in included) / total if total else 0.0
    )
    for r in included:
        r["above_corpus_average"] = r["ci95_low"] > overall
        r["below_corpus_average"] = r["ci95_high"] < overall

    # The headline topic can be one with no editorial meaning at all. The TOI
    # `unknown` category is a filing gap, not a subject, and it tops this
    # ranking: a reader told "Unknown is the most sensational topic" has been
    # told nothing. It is reported separately so it cannot be mistaken for a
    # finding.
    uninformative = {"Unknown", "Other"}
    informative = [r for r in included if r["topic"] not in uninformative]
    no_meaning = [r for r in included if r["topic"] in uninformative]

    log.info(
        "sensationalism: %s topics above the row floor, corpus rate %.4f",
        len(included), overall,
    )
    return {
        "threshold": threshold,
        "corpus_rate": round(overall, 6),
        "min_topic_rows": min_rows,
        "ranked": included,
        "ranked_excluding_uninformative": informative,
        "uninformative_topics": {
            "topics": [r["topic"] for r in no_meaning],
            "reason": (
                "These carry no editorial subject, so their score measures the "
                "absence of a filing decision rather than the language used. "
                "They are excluded from the headline ranking."
            ),
        },
        "excluded_below_min_rows": excluded,
        "distinguishable_from_corpus": [r for r in included if r["above_corpus_average"]],
        "distinguishable_excluding_uninformative": [
            r for r in informative if r["above_corpus_average"]
        ],
        "metric_name": "risk_signal_rate",
        "note": (
            "STYLE measure on unlabelled headlines, not a fake-news rate. "
            "The threshold is the measured 95th percentile, a chosen cut-off."
        ),
    }


def threshold_sensitivity(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ3 robustness: how the topic ranking moves as the cut-off moves.

    If the ranking reshuffles wildly across nearby thresholds, the ordering
    is an artefact of the cut-off and the report must say so rather than
    publish a single ranked table as if it were stable.
    """
    cfg = config.get("sensationalism", {})
    thresholds = [float(t) for t in cfg.get("sensitivity_thresholds", [])]
    chosen = float(cfg.get("threshold", 0.2208))
    if chosen not in thresholds:
        thresholds.append(chosen)
    thresholds.sort()

    # The floor comes from the same config as the ranking, so the sensitivity
    # table covers exactly the topics the ranking reports.
    min_rows = int(cfg.get("min_topic_rows", 1000))
    rows = con.execute(
        """
        SELECT
            t.topic_name,
            count(*) AS n
        FROM fact_headline f
        JOIN dim_topic t ON t.topic_key = f.topic_key
        WHERE f.in_window
        GROUP BY 1
        HAVING count(*) >= ?
        """,
        [min_rows],
    ).fetchall()
    if not rows:
        return {
            "thresholds": thresholds,
            "rows": [],
            "min_topic_rows": min_rows,
            "note": (
                f"no topic reaches the {min_rows}-headline floor, so there is "
                "nothing to rank"
            ),
        }

    names = [r[0] for r in rows]
    # Quote the names even though they come from our own dimension, so a name
    # containing an apostrophe cannot break the SQL.
    quoted = ", ".join("'" + n.replace("'", "''") + "'" for n in names)

    table = []
    for thr in thresholds:
        counts = con.execute(
            f"""
            SELECT
                t.topic_name,
                count(*) FILTER (WHERE f.sensational_score >= {thr}) AS flagged,
                count(*) AS n
            FROM fact_headline f
            JOIN dim_topic t ON t.topic_key = f.topic_key
            WHERE f.in_window AND t.topic_name IN ({quoted})
            GROUP BY 1
            """
        ).fetchall()
        rates = {c: (flag / n if n else 0.0) for c, flag, n in counts}
        ranked = sorted(rates.items(), key=lambda kv: -kv[1])
        table.append(
            {
                "threshold": thr,
                "is_chosen_threshold": thr == chosen,
                "corpus_rate": round(
                    sum(f for _c, f, _n in counts) / sum(n for _c, _f, n in counts), 6
                ) if counts else None,
                "ranking": [c for c, _r in ranked],
                "top3": [c for c, _r in ranked[:3]],
                "top1": ranked[0][0] if ranked else None,
            }
        )

    top1 = {r["top1"] for r in table}
    chosen_row = next((r for r in table if r["is_chosen_threshold"]), None)
    return {
        "thresholds": thresholds,
        "rows": table,
        "min_topic_rows": min_rows,
        "topics_considered": len(names),
        "distinct_top1_across_thresholds": sorted(top1),
        "ranking_is_stable": len(top1) == 1,
        "chosen_threshold_ranking": chosen_row["ranking"] if chosen_row else None,
        "note": (
            "A ranking that changes its top topic as the cut-off moves is an "
            "artefact of the cut-off. Both facts are reported."
        ),
    }


def sensationalism_trend_by_year(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ3 over time: is sensationalism rising or falling, and by how much."""
    rows = con.execute(
        """
        SELECT
            d.year_no,
            count(*)                              AS n,
            count(*) FILTER (WHERE f.is_risk_signal) AS risk,
            sum(f.sentiment_compound)             AS sum_sentiment,
            sum(f.sensational_score)              AS sum_score
        FROM fact_headline f
        JOIN dim_date d ON d.date_key = f.date_key
        WHERE f.in_window
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    series = [
        {
            "year": r[0],
            "headline_count": r[1],
            "risk_signal_count": r[2],
            "risk_signal_rate": round(r[2] / r[1], 6) if r[1] else None,
            "ci95_low": round(wilson_interval(r[2], r[1])[0], 6) if r[1] else None,
            "ci95_high": round(wilson_interval(r[2], r[1])[1], 6) if r[1] else None,
            "mean_sentiment": round(r[3] / r[1], 6) if r[1] else None,
            "mean_sensational_score": round(r[4] / r[1], 6) if r[1] else None,
        }
        for r in rows
    ]
    if len(series) >= 2:
        first, last = series[0], series[-1]
        change = last["risk_signal_rate"] - first["risk_signal_rate"]
        series_summary = {
            "from_year": first["year"],
            "to_year": last["year"],
            "from_rate": first["risk_signal_rate"],
            "to_rate": last["risk_signal_rate"],
            "change_pp": round(change * 100, 4),
            "intervals_overlap": not (
                last["ci95_low"] > first["ci95_high"]
                or first["ci95_low"] > last["ci95_high"]
            ),
        }
    else:
        series_summary = None
    return {"series": series, "summary": series_summary}


def run_sensationalism(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    by_topic = sensationalism_by_topic(con, config)
    return {
        "by_topic": by_topic,
        "threshold_sensitivity": threshold_sensitivity(con, config),
        "trend_by_year": sensationalism_trend_by_year(con, config),
        "headline_count": human_int(
            con.execute("SELECT count(*) FROM fact_headline WHERE in_window").fetchone()[0]
        ),
    }
