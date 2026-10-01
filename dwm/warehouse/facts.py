"""Fact tables for the constellation.

    fact_headline       grain: one headline per (publish_date, headline_text)
    fact_statement      grain: one distinct statement text, nullable date_key
    fact_market_daily   grain: one Nifty 50 trading day

Each fact carries conformed dimension keys plus the measures computed by the
feature stage. Nothing is pre-averaged: measures are stored as they were
measured (a VADER score, a sensationalism score, a headline count) so that
roll-ups are exact sums. Averages are always recomputed as sum/count at query
time, which is the point the viva sheet makes about cubes.
"""

from __future__ import annotations

import duckdb

from dwm.config import Settings
from dwm.ingest.audit import ensure_audit_table, new_run_id, record
from dwm.logging_utils import get, human_int

log = get("dwm.warehouse.facts")


def dataset_keys(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Look the dataset keys up from dim_dataset.

    Deliberately not hard-coded. dim_dataset assigns keys by sorting the
    configured codes, so a literal mapping here silently disagreed with it:
    `toi` is key 3 in the dimension but was written as key 1 in the fact, and
    every headline would have pointed at the wrong source.
    """
    rows = con.execute("SELECT dataset_code, dataset_key FROM dim_dataset").fetchall()
    keys = {str(code): int(key) for code, key in rows}
    missing = {"toi", "ifnd", "nifty"} - set(keys)
    if missing:
        raise RuntimeError(f"dim_dataset is missing {sorted(missing)}")
    return keys


def label_keys(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Look the label keys up from dim_label by code."""
    rows = con.execute("SELECT label_code, label_key FROM dim_label").fetchall()
    keys = {str(code): int(key) for code, key in rows}
    missing = {"REAL", "FAKE", "UNLABELLED"} - set(keys)
    if missing:
        raise RuntimeError(f"dim_label is missing {sorted(missing)}")
    return keys


def instrument_keys(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT min(instrument_key) FROM dim_instrument").fetchone()
    if not row or row[0] is None:
        raise RuntimeError("dim_instrument is empty")
    return int(row[0])

DDL = {
    "fact_headline": """
        CREATE OR REPLACE TABLE fact_headline AS
        SELECT
            h.headline_id                        AS headline_id,
            h.date_key                          AS date_key,
            h.topic_key                         AS topic_key,
            {TOI}                               AS dataset_key,
            h.publish_date                      AS publish_date,
            h.raw_category                      AS raw_category,
            h.category_prefix                   AS category_prefix,
            h.headline_text                     AS headline_text,
            h.text_length                       AS text_length,
            h.word_count                        AS word_count,
            h.staged_rows                       AS staged_rows,
            h.category_count                    AS category_count,
            h.is_multi_category                 AS is_multi_category,
            h.in_window                         AS in_window,
            f.sentiment_compound                AS sentiment_compound,
            f.sentiment_positive                AS sentiment_positive,
            f.sentiment_negative                AS sentiment_negative,
            f.sentiment_neutral                 AS sentiment_neutral,
            f.sentiment_band                    AS sentiment_band,
            f.unique_token_count                AS unique_token_count,
            f.caps_token_count                  AS caps_token_count,
            f.caps_token_ratio                  AS caps_token_ratio,
            f.exclamation_count                 AS exclamation_count,
            f.question_count                    AS question_count,
            f.superlative_count                 AS superlative_count,
            f.urgency_count                     AS urgency_count,
            f.negation_count                    AS negation_count,
            f.sensational_score                 AS sensational_score,
            f.is_sensational                    AS is_sensational,
            f.is_risk_signal                    AS is_risk_signal
        FROM cln_headline h
        JOIN feat_headline f ON f.source_key = h.headline_id
    """,
    "fact_statement": """
        CREATE OR REPLACE TABLE fact_statement AS
        SELECT
            s.statement_id                      AS statement_id,
            s.date_key                          AS date_key,
            s.topic_key                         AS topic_key,
            {IFND}                              AS dataset_key,
            l.label_key                         AS label_key,
            s.source_date                       AS source_date,
            s.date_precision                    AS date_precision,
            s.has_date                          AS has_date,
            s.in_window                         AS in_window,
            s.raw_category                      AS raw_category,
            s.statement_text                    AS statement_text,
            s.text_length                       AS text_length,
            s.word_count                        AS word_count,
            s.staged_rows                       AS staged_rows,
            s.label_code                        AS label_code,
            f.sentiment_compound                AS sentiment_compound,
            f.sentiment_positive                AS sentiment_positive,
            f.sentiment_negative                AS sentiment_negative,
            f.sentiment_neutral                 AS sentiment_neutral,
            f.sentiment_band                    AS sentiment_band,
            f.unique_token_count                AS unique_token_count,
            f.caps_token_count                  AS caps_token_count,
            f.caps_token_ratio                  AS caps_token_ratio,
            f.exclamation_count                 AS exclamation_count,
            f.question_count                    AS question_count,
            f.superlative_count                 AS superlative_count,
            f.urgency_count                     AS urgency_count,
            f.negation_count                    AS negation_count,
            f.sensational_score                 AS sensational_score,
            f.is_sensational                    AS is_sensational,
            f.is_risk_signal                    AS is_risk_signal
        FROM cln_statement s
        JOIN feat_statement f ON f.source_key = s.statement_id
        JOIN dim_label l ON l.label_code = s.label_code
    """,
    "fact_market_daily": """
        CREATE OR REPLACE TABLE fact_market_daily AS
        SELECT
            m.market_id                         AS market_id,
            m.date_key                          AS date_key,
            {NIFTY}                             AS dataset_key,
            {INSTRUMENT}                        AS instrument_key,
            m.trade_date                        AS trade_date,
            m.in_window                         AS in_window,
            m.open                              AS open,
            m.high                              AS high,
            m.low                               AS low,
            m.close                             AS close,
            m.volume                            AS volume,
            m.turnover                          AS turnover,
            f.return_pct                        AS return_pct,
            f.abs_change                        AS abs_change,
            f.day_range                         AS day_range,
            f.range_pct                         AS range_pct,
            f.intraday_change                   AS intraday_change,
            f.volatility_20d                    AS volatility_20d,
            f.return_sign                       AS return_sign
        FROM cln_market_daily m
        JOIN feat_market_daily f ON f.market_id = m.market_id
    """,
}


def _fmt(template: str, keys: dict[str, int]) -> str:
    return template.format(TOI=keys["toi"], IFND=keys["ifnd"], NIFTY=keys["nifty"],
                           INSTRUMENT=keys["instrument"])


def build_facts(con: duckdb.DuckDBPyConnection, *, run_id: str | None = None) -> dict[str, int]:
    """Build the three fact tables. Returns row counts."""
    run_id = run_id or new_run_id()
    _require(con, ("cln_headline", "feat_headline", "cln_statement", "feat_statement",
                   "cln_market_daily", "feat_market_daily", "dim_dataset",
                   "dim_label", "dim_instrument"))
    keys = dataset_keys(con)
    keys["instrument"] = instrument_keys(con)
    log.debug("resolved keys: %s", keys)
    for name, template in DDL.items():
        con.execute(_fmt(template, keys))
        n = int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0])
        log.info("%s: %s rows", name, human_int(n))

    ensure_audit_table(con)
    from datetime import datetime, timezone

    record(
        con,
        run_id=run_id,
        dataset_code="all",
        step="warehouse.load",
        info={
            "rows_read": 0,
            "rows_loaded": sum(
                int(con.execute(f"SELECT count(*) FROM {n}").fetchone()[0]) for n in DDL
            ),
            "rows_rejected": 0,
        },
        status="ok",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    return {name: int(con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]) for name in DDL}


def _require(con: duckdb.DuckDBPyConnection, tables: tuple[str, ...]) -> None:
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    missing = [t for t in tables if t not in present]
    if missing:
        raise RuntimeError(
            f"missing {missing}. Run `python -m dwm features` before `python -m dwm build`."
        )
