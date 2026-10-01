"""Pre-aggregated cubes.

The blueprint makes one rule about these explicit, and the viva sheet repeats
it: **store sums, never averages.** Sums roll up exactly; averages do not. So
every cube holds a count and a set of column sums, and any mean is recomputed
as `sum / count` at query time.

Cubes exist for one reason: the OLAP operations in Phase 4 should not have to
rescan 3.15M fact rows to answer a roll-up. They are derived and can be
dropped and rebuilt at any time.

    cube_month_topic        year-month x topic, headlines in window
    cube_year_topic         year x topic
    cube_topic_sentiment    topic totals, the denominator for every rate
    cube_day_topic          day x topic, for drill-across onto market days
"""

from __future__ import annotations

import duckdb

from dwm.logging_utils import get, human_int

log = get("dwm.warehouse.cubes")

# Measures summed in every cube. Names are explicit about being sums.
SUM_MEASURES = (
    "sentiment_compound",
    "sentiment_positive",
    "sentiment_negative",
    "sentiment_neutral",
    "caps_token_ratio",
    "superlative_count",
    "urgency_count",
    "exclamation_count",
    "question_count",
    "word_count",
    "sensational_score",
)

# Boolean measures are summed as 0/1 counts, which is how a rate becomes
# sum/count rather than a stored percentage.
FLAG_MEASURES = (("is_sensational", "sensational_count"),
                 ("is_risk_signal", "risk_signal_count"))

DDL = {
    # One row per (year_month, topic) inside the analysis window.
    "cube_month_topic": """
        CREATE OR REPLACE TABLE cube_month_topic AS
        SELECT
            d.year_month_key        AS year_month_key,
            d.year_month            AS year_month,
            d.year_no               AS year_no,
            d.month_no              AS month_no,
            f.topic_key             AS topic_key,
            count(*)                AS headline_count,
            count(*) FILTER (WHERE f.is_multi_category)      AS multi_category_count,
            count(*) FILTER (WHERE f.sentiment_band = 'negative')  AS negative_count,
            count(*) FILTER (WHERE f.sentiment_band = 'positive')  AS positive_count,
            count(*) FILTER (WHERE f.is_multi_category IS FALSE)    AS single_category_count,
            {SUMS}
        FROM fact_headline f
        JOIN dim_date d ON d.date_key = f.date_key
        WHERE f.in_window
        GROUP BY 1, 2, 3, 4, 5
    """,
    # One row per (year, topic) inside the window.
    "cube_year_topic": """
        CREATE OR REPLACE TABLE cube_year_topic AS
        SELECT
            d.year_no               AS year_no,
            f.topic_key             AS topic_key,
            count(*)                AS headline_count,
            count(*) FILTER (WHERE f.sentiment_band = 'negative')  AS negative_count,
            count(*) FILTER (WHERE f.is_multi_category)             AS multi_category_count,
            {SUMS}
        FROM fact_headline f
        JOIN dim_date d ON d.date_key = f.date_key
        WHERE f.in_window
        GROUP BY 1, 2
    """,
    # Topic totals across the whole window: the denominator for every rate.
    "cube_topic_sentiment": """
        CREATE OR REPLACE TABLE cube_topic_sentiment AS
        SELECT
            f.topic_key             AS topic_key,
            count(*)                AS headline_count,
            count(*) FILTER (WHERE f.is_sensational) AS sensational_count,
            count(*) FILTER (WHERE f.is_risk_signal) AS risk_signal_count,
            count(*) FILTER (WHERE f.sentiment_band = 'negative') AS negative_count,
            count(*) FILTER (WHERE f.sentiment_band = 'positive') AS positive_count,
            count(*) FILTER (WHERE f.sentiment_band = 'neutral')  AS neutral_count,
            {SUMS}
        FROM fact_headline f
        WHERE f.in_window
        GROUP BY 1
    """,
    # Day x topic. This is the bridge to market data: it lets a drill-across
    # line up daily headline counts and sentiment sums with daily Nifty
    # returns without scanning the fact table.
    "cube_day_topic": """
        CREATE OR REPLACE TABLE cube_day_topic AS
        SELECT
            f.date_key              AS date_key,
            f.topic_key             AS topic_key,
            count(*)                AS headline_count,
            {SUMS}
        FROM fact_headline f
        WHERE f.in_window
        GROUP BY 1, 2
    """,
}


def _sum_columns() -> str:
    parts = [f"sum({m}) AS sum_{m}" for m in SUM_MEASURES]
    parts += [
        f"sum(CASE WHEN {column} THEN 1 ELSE 0 END) AS {alias}"
        for column, alias in FLAG_MEASURES
    ]
    return ",\n            ".join(parts)


def build_cubes(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Build every cube. Returns row counts."""
    for name, template in DDL.items():
        con.execute(template.format(SUMS=_sum_columns()))
        n = int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
        log.info("%s: %s rows", name, human_int(n))
    return {name: int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]) for name in DDL}
