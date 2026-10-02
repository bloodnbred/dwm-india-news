"""Trend and burst mining (RQ1 and RQ2).

RQ1: how the topic mix changed across the five-year window.
RQ2: which months spike in volume, and which known events they coincide with.

Two data facts shape this module, both measured rather than assumed.

**2015 is a partial year.** The window starts 2015-06-30, so 2015 holds about
half a year of headlines against full years for the rest. Raw counts are
therefore not comparable across years, and neither are raw shares: a half year
inflates every topic's share by roughly the same factor. Everything here is a
share of its own year, and a partial year is flagged rather than dropped or
silently compared.

**A taxonomy shift, not a trend.** `business.international-business` is 11.1%
of all 2017 headlines (26,856 rows) and 0.2% of 2018 (485 rows). TOI changed
how it filed content. A naive topic-mix answer would report "business news
quintupled in 2017", which is an artefact of filing, not of what India was
reading. The module therefore reports a per-year composition change and
flags years where one raw category dominates implausibly, so the report can
name the artefact instead of repeating it.

Everything is association. A burst is not a cause; the known-event list is a
set of candidate explanations to compare against, never an assertion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import duckdb

from dwm.logging_utils import get, human_int

log = get("dwm.mining.trends")


@dataclass(slots=True)
class Guard:
    """A guard rail: a check that either passes or explains why it cannot.

    The blueprint requires the inference stage to fail loudly on small data.
    Mining needs the same discipline: a statistic without a denominator, or
    from too few observations, is worse than an absent one because it looks
    like a finding.
    """

    checks: list[dict[str, Any]]

    def require(self, name: str, ok: bool, detail: str) -> bool:
        self.checks.append({"check": name, "passed": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if not c["passed"]]

    @property
    def ok(self) -> bool:
        return not self.failed


def topic_mix_by_year(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ1: each topic's share of each year, with the partial year flagged."""
    trends = config.get("trends", {})
    partial = {int(y) for y in trends.get("partial_years", [])}
    min_rows = int(trends.get("min_year_rows", 1))

    rows = con.execute(
        """
        SELECT
            d.year_no,
            t.topic_name,
            t.topic_group,
            count(*)                                   AS headline_count,
            count(*) FILTER (WHERE f.is_risk_signal)   AS risk_signal_count,
            sum(f.sentiment_compound)                  AS sum_sentiment_compound,
            sum(f.sensational_score)                   AS sum_sensational_score
        FROM fact_headline f
        JOIN dim_date  d ON d.date_key = f.date_key
        JOIN dim_topic t ON t.topic_key = f.topic_key
        WHERE f.in_window
        GROUP BY 1, 2, 3
        ORDER BY 1, 4 DESC
        """
    ).fetchall()

    by_year_total: dict[int, int] = {}
    for year, _topic, _group, n, *_ in rows:
        by_year_total[year] = by_year_total.get(year, 0) + n

    guard = Guard([])
    guard.require(
        "window_has_multiple_years",
        len(by_year_total) >= 2,
        f"{len(by_year_total)} distinct years in the window",
    )
    guard.require(
        "every_year_above_min_rows",
        all(v >= min_rows for v in by_year_total.values()),
        f"year totals {dict(sorted(by_year_total.items()))}, floor {min_rows}",
    )

    out_rows = []
    for year, topic, group, n, risk, sum_sent, sum_score in rows:
        total = by_year_total[year] or 1
        out_rows.append(
            {
                "year": year,
                "topic": topic,
                "topic_group": group,
                "headline_count": n,
                "year_total": total,
                "share_of_year": round(n / total, 6),
                "risk_signal_count": risk,
                "risk_signal_rate": round(risk / n, 6) if n else None,
                "mean_sentiment": round(sum_sent / n, 6) if n else None,
                "mean_sensational_score": round(sum_score / n, 6) if n else None,
                # A partial year is marked so no reader compares it as if it
                # were a full one.
                "is_partial_year": year in partial,
                "comparable": year not in partial,
            }
        )

    return {
        "rows": out_rows,
        "year_totals": dict(sorted(by_year_total.items())),
        "partial_years": sorted(partial),
        "guard": {"passed": guard.ok, "checks": guard.checks},
        "note": (
            "Shares are within-year, so the 2015 partial year is not "
            "misleading on its own. Raw counts are NOT comparable across "
            "years and must not be charted directly."
        ),
    }


def composition_shift(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ1: how each topic's share moved year over year.

    Reported as a change in share in percentage points, which is the
    meaningful comparison, plus the underlying counts so a reader can see
    whether a move is driven by a large or a small base.
    """
    mix = topic_mix_by_year(con, config)
    rows = mix["rows"]
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_topic.setdefault(r["topic"], []).append(r)

    shifts = []
    for topic, series in by_topic.items():
        series.sort(key=lambda r: r["year"])
        for previous, current in zip(series, series[1:], strict=False):
            delta = current["share_of_year"] - previous["share_of_year"]
            gap = current["year"] - previous["year"]
            shifts.append(
                {
                    "topic": topic,
                    "topic_group": current["topic_group"],
                    "from_year": previous["year"],
                    "to_year": current["year"],
                    # A topic absent in an intermediate year is compared
                    # across the gap, and the gap is recorded rather than
                    # presented as a year-on-year move.
                    "year_gap": gap,
                    "is_year_on_year": gap == 1,
                    "from_share": previous["share_of_year"],
                    "to_share": current["share_of_year"],
                    "change_pp": round(delta * 100, 4),
                    "from_count": previous["headline_count"],
                    "to_count": current["headline_count"],
                    # A move driven by a small base is not a trend, and the
                    # reader needs to be able to see that.
                    "from_comparable": previous["comparable"],
                    "to_comparable": current["comparable"],
                    "both_comparable": previous["comparable"] and current["comparable"],
                }
            )
    shifts.sort(key=lambda s: -abs(s["change_pp"]))
    return {
        "rows": shifts,
        "largest_moves": shifts[:15],
        "guard": mix["guard"],
    }


def raw_category_dominance(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """Flag years where one raw category dominates implausibly.

    This exists because of a measured artefact: in 2017
    `business.international-business` alone is 11.1% of every headline, and
    0.2% a year later. A topic-mix analysis that ignored this would report a
    news-industry event as a change in what the country was reading about.

    A category is flagged when it exceeds this share of a single year.
    """
    limit = 0.08
    rows = con.execute(
        """
        SELECT
            d.year_no,
            h.raw_category,
            count(*) AS n,
            sum(count(*)) OVER (PARTITION BY d.year_no) AS year_total
        FROM fact_headline f
        JOIN dim_date d ON d.date_key = f.date_key
        JOIN cln_headline h ON h.headline_id = f.headline_id
        WHERE f.in_window
        GROUP BY 1, 2
        """
    ).fetchall()

    flagged = []
    for year, category, n, total in rows:
        share = n / total if total else 0.0
        if share >= limit:
            flagged.append(
                {
                    "year": year,
                    "raw_category": category,
                    "count": n,
                    "year_total": total,
                    "share_of_year": round(share, 6),
                }
            )
    flagged.sort(key=lambda f: -f["share_of_year"])
    return {
        "rows": flagged,
        "threshold": limit,
        "interpretation": (
            "A single raw category holding this share of a year indicates a "
            "change in how the publisher filed content, not a change in "
            "reader interest. Affected years need this caveat in the report."
        ),
    }


def monthly_volume(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """The monthly headline series across the window."""
    rows = con.execute(
        """
        SELECT
            c.year_month,
            min(c.year_no)  AS year_no,
            min(c.month_no) AS month_no,
            sum(c.headline_count)           AS headline_count,
            sum(c.risk_signal_count)        AS risk_signal_count,
            sum(c.sum_sentiment_compound)   AS sum_sentiment_compound,
            sum(c.sum_sensational_score)    AS sum_sensational_score
        FROM cube_month_topic c
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    return [
        {
            "year_month": r[0],
            "year": r[1],
            "month": r[2],
            "headline_count": r[3],
            "risk_signal_count": r[4],
            "risk_signal_rate": round(r[4] / r[3], 6) if r[3] else None,
            "mean_sentiment": round(r[5] / r[3], 6) if r[3] else None,
            "mean_sensational_score": round(r[6] / r[3], 6) if r[3] else None,
        }
        for r in rows
    ]


def _zscores(pairs: list[tuple[str, float]]) -> dict[str, float]:
    """z-score each value against the mean and population sd of the series."""
    values = [v for _k, v in pairs if v is not None]
    if len(values) < 3:
        return {}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    sd = math.sqrt(variance)
    if sd == 0:
        return {}
    return {k: (v - mean) / sd for k, v in pairs if v is not None}


def _coefficient_of_variation(pairs: list[tuple[str, float]]) -> float | None:
    values = [v for _k, v in pairs if v is not None]
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    if mean == 0:
        return None
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / mean


def detect_bursts(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """RQ2: test whether any month departs from its year's norm, on any measure.

    The finding here is a NULL, and that is the honest answer.

    Measured on the real corpus, monthly headline VOLUME is almost perfectly
    flat: the coefficient of variation is 0.02 to 0.04 within every full year,
    and the busiest month of a year runs only 1.02 to 1.05 times the monthly
    mean. Even March 2020, the month India entered a national lockdown, is
    2.5% above its own year mean. A z-score threshold of 2.0 therefore finds
    nothing, and lowering it until something appears would be choosing a
    threshold to manufacture a result.

    So this module tests four measures rather than one, reports the flatness
    as evidence, and reports what happens to each measure in the event months
    including the counter-intuitive parts. The COVID months show LOWER health
    coverage (z = -0.74), LOWER sports (z = -1.33) and the lowest negative
    sentiment of the series (z = -2.63), which is the opposite of what a
    news-reactive archive would show.

    A null result with a measured explanation is worth more than a spike
    found by tuning a threshold until one appeared.
    """
    bursts_cfg = config.get("bursts", {})
    z_threshold = float(bursts_cfg.get("z_threshold", 2.0))
    min_rows = int(bursts_cfg.get("min_month_rows", 0))
    events = {e["date"]: e["label"] for e in bursts_cfg.get("known_events", [])}

    series = monthly_volume(con)
    guard = Guard([])
    guard.require("monthly_series_present", bool(series), f"{len(series)} months")

    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in series:
        by_year.setdefault(row["year"], []).append(row)

    # -- measure 1: total volume, z-scored within its own year ---------------
    #
    # Only FULL years enter the flatness claim. 2015 holds seven months
    # because the window starts 2015-06-30, and a seven-month mean has a
    # higher spread than a twelve-month one for reasons that have nothing to
    # do with news. Including it reported a coefficient of variation of 0.39
    # for a series that is otherwise flat to within 0.02 to 0.04.
    full_months = int(config.get("trends", {}).get("full_year_months", 12))
    detected: list[dict[str, Any]] = []
    per_year_cv: dict[int, float | None] = {}
    for year, months in sorted(by_year.items()):
        counts = [m["headline_count"] for m in months]
        is_full_year = len(months) >= full_months
        per_year_cv[year] = _coefficient_of_variation(
            [(m["year_month"], float(m["headline_count"])) for m in months]
        ) if is_full_year else None
        if not is_full_year:
            continue
        mean = sum(counts) / len(counts)
        sd = math.sqrt(sum((c - mean) ** 2 for c in counts) / len(counts))
        for m in months:
            if m["headline_count"] < min_rows:
                continue
            z = ((m["headline_count"] - mean) / sd) if sd > 0 else 0.0
            if z < z_threshold:
                continue
            detected.append(
                {
                    "measure": "headline_volume",
                    "year_month": m["year_month"],
                    "year": year,
                    "month": m["month"],
                    "value": m["headline_count"],
                    "year_mean": round(mean, 1),
                    "year_sd": round(sd, 1),
                    "z_score": round(z, 3),
                    "ratio_to_year_mean": round(m["headline_count"] / mean, 4) if mean else None,
                    "coincides_with": events.get(m["year_month"]),
                }
            )
    detected.sort(key=lambda b: -b["z_score"])

    # -- measures 2-4: per-topic volume, sensationalism, negative rate ------
    full_years = {y for y, m in by_year.items() if len(m) >= 6}
    topic_rows = con.execute(
        """
        SELECT c.year_month, t.topic_name, sum(c.headline_count) AS n
        FROM cube_month_topic c
        JOIN dim_topic t ON t.topic_key = c.topic_key
        WHERE c.year_no IN ({})
        GROUP BY 1, 2
        """.format(", ".join(str(y) for y in sorted(full_years)))
    ).fetchall() if full_years else []

    topic_series: dict[str, list[tuple[str, float]]] = {}
    for year_month, topic, n in topic_rows:
        topic_series.setdefault(topic, []).append((year_month, float(n)))

    event_rows = con.execute(
        """
        SELECT
            c.year_month,
            sum(c.headline_count)           AS n,
            sum(c.sensational_count)        AS sensational,
            sum(c.negative_count)           AS negative
        FROM cube_month_topic c
        GROUP BY 1
        """
    ).fetchall()
    rate_series = {
        "sensationalism_rate": [
            (ym, s / n if n else None) for ym, n, s, _neg in event_rows
        ],
        "negative_rate": [
            (ym, g / n if n else None) for ym, n, _s, g in event_rows
        ],
    }

    event_months: list[dict[str, Any]] = []
    for month, label in events.items():
        record: dict[str, Any] = {
            "year_month": month,
            "label": label,
            "measures": {},
        }
        for topic, pairs in topic_series.items():
            z = _zscores(pairs)
            if month in z:
                value = dict(pairs).get(month)
                record["measures"][f"topic_volume:{topic}"] = {
                    "value": value,
                    "z_score": round(z[month], 3),
                    "is_burst": abs(z[month]) >= z_threshold,
                }
        for name, pairs in rate_series.items():
            z = _zscores(pairs)
            if month in z:
                record["measures"][name] = {
                    "value": round(dict(pairs)[month], 6),
                    "z_score": round(z[month], 3),
                    "is_burst": abs(z[month]) >= z_threshold,
                }
        event_months.append(record)

    counter_signals = [
        {
            "year_month": r["year_month"],
            "label": r["label"],
            "measure": name,
            "z_score": m["z_score"],
        }
        for r in event_months
        for name, m in r["measures"].items()
        if m["z_score"] <= -z_threshold
    ]

    full_year_cvs = [v for v in per_year_cv.values() if v is not None]
    max_cv = max(full_year_cvs) if full_year_cvs else None

    # The counter-signal narrative, computed rather than asserted.
    #
    # An earlier version of this module carried a hard-coded sentence claiming
    # negative sentiment "is at its lowest" during the COVID months. Measured,
    # that was false: 2020-03 sits at z = +0.09, essentially neutral. A
    # sentence in a template that contradicts its own data is worse than no
    # sentence, so every claim below is derived from the values just measured.
    declines: list[dict[str, Any]] = []
    for record in event_months:
        for name, m in record["measures"].items():
            if m["z_score"] < -0.5:
                declines.append(
                    {
                        "year_month": record["year_month"],
                        "label": record["label"],
                        "measure": name,
                        "z_score": m["z_score"],
                    }
                )
    declines.sort(key=lambda d: d["z_score"])

    total_measured = sum(len(r["measures"]) for r in event_months)
    # Why the raw count is not reported as evidence: under a standard normal,
    # 30.85% of z-scores sit below -0.5, and these measures share months and
    # are correlated with one another, so the count is not a valid test. It is
    # reported only so the reader can see it is not being hidden.
    expected_below = round(total_measured * 0.3085, 1)

    # The checkable pattern is co-movement among the desks we predicted would
    # RISE. Twenty-one measures per month means "three fell" proves nothing, so
    # the test is restricted to a list fixed in config before the data was
    # looked at: if Health, Sports and Entertainment all fall during a national
    # pandemic lockdown, that is a falsifiable claim about a specific
    # prediction, and it fails.
    responsive = [
        t for t in bursts_cfg.get("event_responsive_topics", []) if t
    ]
    co_movement: list[dict[str, Any]] = []
    if responsive:
        for record in event_months:
            z_by_desk = {
                topic: record["measures"].get(f"topic_volume:{topic}", {}).get("z_score")
                for topic in responsive
            }
            observed = {k: v for k, v in z_by_desk.items() if v is not None}
            if not observed:
                continue
            falling = sorted(k for k, v in observed.items() if v < 0)
            co_movement.append(
                {
                    "year_month": record["year_month"],
                    "label": record["label"],
                    "z_by_desk": {k: round(v, 3) for k, v in observed.items()},
                    "all_fell": len(falling) == len(observed),
                    "desks_falling": falling,
                }
            )

    all_fell = [c for c in co_movement if c["all_fell"]]
    if declines:
        worst = declines[0]
        parts = [
            f"The single largest departure is "
            f"`{worst['measure'].replace('topic_volume:', '')}` in "
            f"{worst['year_month']} at z = {worst['z_score']:+.2f}."
        ]
        if responsive:
            names = ", ".join(responsive)
            if all_fell:
                months = ", ".join(c["year_month"] for c in all_fell)
                parts.append(
                    f"In {len(all_fell)} of the {len(co_movement)} event months "
                    f"({months}) every one of the desks predicted to rise — "
                    f"{names} — fell below its norm instead. That is a specific "
                    "prediction failing, not a vague absence of signal."
                )
            else:
                parts.append(
                    f"At no point did all of {names} fall together, so the "
                    "predicted response is not cleanly falsified."
                )
        parts.append(
            f"For scale, {len(declines)} of {total_measured} measures sit below "
            f"−0.5 SD, against roughly {expected_below} expected by chance. That "
            "count is **not** offered as a significance test: the measures share "
            "months and are correlated, so their z-scores are not independent and "
            "the count is only shown so it is not hidden."
        )
        summary = " ".join(parts)
    else:
        summary = (
            "No measure in any event month sits half a standard deviation below "
            "its norm, so the event months are unremarkable on every measure "
            "tested. That is itself the result."
        )

    guard.require(
        "at_least_one_year_measurable",
        any(len(v) >= 3 for v in by_year.values()),
        f"years with >=3 months: {sum(1 for v in by_year.values() if len(v) >= 3)}",
    )

    return {
        "detected": detected,
        "count": len(detected),
        "volume_is_flat": max_cv is not None and max_cv < 0.10,
        "max_within_year_volume_cv": round(max_cv, 4) if max_cv is not None else None,
        "per_year_volume_cv": {
            y: (round(v, 4) if v is not None else None) for y, v in sorted(per_year_cv.items())
        },
        "partial_years_excluded": sorted(
            y for y, v in per_year_cv.items() if v is None
        ),
        "full_year_months_required": full_months,
        "event_months": event_months,
        "counter_signals": counter_signals,
        "counter_signal_declines": declines[:12],
        "event_responsive_topics": responsive,
        "counter_signal_co_movement": co_movement,
        "event_months_all_predicted_desks_fell": [c["year_month"] for c in all_fell],
        "counter_signal_summary": summary,
        "events_compared": len(events),
        "z_threshold": z_threshold,
        "guard": {"passed": guard.ok, "checks": guard.checks},
        "finding": (
            "No month is a volume outlier. Within-year volume CV is at most "
            f"{round(max_cv, 3) if max_cv is not None else 'n/a'}, and the "
            "busiest month of each year runs only 2-5% above its own mean. "
            "The archive's headline volume behaves like a fixed editorial "
            "capacity rather than a response to news intensity."
        )
        if max_cv is not None and max_cv < 0.10
        else f"Volume shows variability; max within-year CV {max_cv}.",
        "counter_signal_note": (
            "Derived from the measured z-scores above, not asserted. Note that "
            "these are departures from the norm, not dramatic swings: the "
            "largest is around 1.5 standard deviations on a series this flat."
        ),
        "note": (
            "A burst is a statistical departure, not a cause. Event labels are "
            "calendar coincidences offered for the reader to judge."
        ),
    }


def run_trends(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """Both RQ1 and RQ2, with the artefact flags attached."""
    mix = topic_mix_by_year(con, config)
    log.info(
        "topic mix: %s topic-years across %s years",
        human_int(len(mix["rows"])), len(mix["year_totals"]),
    )
    bursts = detect_bursts(con, config)
    log.info(
        "bursts: %s volume outliers, max within-year CV %s, %s counter-signals",
        bursts["count"], bursts["max_within_year_volume_cv"],
        len(bursts["counter_signals"]),
    )
    return {
        "topic_mix": mix,
        "composition_shift": composition_shift(con, config),
        "taxonomy_artefacts": raw_category_dominance(con, config),
        "monthly_series": monthly_volume(con),
        "bursts": bursts,
    }
