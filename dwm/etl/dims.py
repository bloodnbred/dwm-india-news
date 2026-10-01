"""Conformed dimensions for the fact constellation.

Five dimensions, all shared by the fact tables (BLUEPRINT section 2):

    dim_date       one calendar day, contiguous, flags for trading days
    dim_topic      coarse topic, with a group so "where" and "what" stay apart
    dim_dataset    which source a fact row came from, with its provenance
    dim_label      REAL / FAKE / UNLABELLED
    dim_instrument traded market series

They are conformed: `date_key`, `topic_key` and `dataset_key` mean the same
thing in every fact table, which is what makes drill-across possible.
"""

from __future__ import annotations

import duckdb

from dwm.config import DatasetSpec, TopicMap
from dwm.logging_utils import get, human_int

log = get("dwm.etl.dims")

# Topics that describe a place rather than a subject. Kept as data so the
# report can exclude or isolate them instead of hard-coding a name.
PLACE_TOPICS = {"Local"}

# What each topic is fundamentally about. RQ1 is a subject question, so
# separating the two groups is what makes that analysis meaningful.
TOPIC_GROUPS = {
    "Local": "Place",
    "Nation": "Place",
    "World": "Place",
    "Politics": "Subject",
    "Business": "Subject",
    "Sports": "Subject",
    "Entertainment": "Subject",
    "Technology": "Subject",
    "Health": "Subject",
    "Education": "Subject",
    "Automobile": "Subject",
    "Travel": "Subject",
    "Food": "Subject",
    "Lifestyle": "Subject",
    "Environment": "Subject",
    "Crime": "Subject",
    "Religion": "Subject",
    "Misinformation": "Type",
    "Other": "Other",
    "Unknown": "Unknown",
}

DDL = {
    "dim_date": """
        CREATE OR REPLACE TABLE dim_date AS
        WITH bounds AS (
            SELECT min(d) AS lo, max(d) AS hi FROM (
                SELECT {toi} AS d FROM stg_toi WHERE {toi} IS NOT NULL
                UNION ALL
                SELECT {nifty} FROM stg_nifty WHERE {nifty} IS NOT NULL
                UNION ALL
                SELECT {ifnd} FROM stg_ifnd WHERE {ifnd} IS NOT NULL
            ) WHERE d IS NOT NULL
        ),
        cal AS (
            SELECT unnest(generate_series(lo, hi, INTERVAL 1 DAY))::DATE AS full_date
            FROM bounds
        )
        SELECT
            CAST(strftime(full_date, '%Y%m%d') AS INTEGER) AS date_key,
            full_date,
            year(full_date)                                   AS year_no,
            quarter(full_date)                                AS quarter_no,
            month(full_date)                                  AS month_no,
            day(full_date)                                    AS day_no,
            dayname(full_date)                                AS day_name,
            dayofweek(full_date)                              AS day_of_week,
            weekofyear(full_date)                             AS week_of_year,
            dayofyear(full_date)                              AS day_of_year,
            strftime(full_date, '%Y-%m')                      AS year_month,
            CAST(year(full_date) * 100 + month(full_date) AS INTEGER) AS year_month_key,
            dayofweek(full_date) IN (0, 6)                    AS is_weekend,
            full_date = last_day(full_date)                   AS is_month_end,
            (month(full_date) IN (3, 6, 9, 12)
                AND full_date = last_day(full_date))          AS is_quarter_end,
            -- Uses the configured nifty formats rather than a bare cast, so
            -- a source in DD-MM-YYYY still flags trading days correctly.
            EXISTS (SELECT 1 FROM stg_nifty n
                    WHERE {nifty} = full_date)          AS is_trading_day
        FROM cal
        ORDER BY full_date
    """,
    "dim_topic": """
        CREATE OR REPLACE TABLE dim_topic (
            topic_key       INTEGER,
            topic_name      VARCHAR,
            topic_group     VARCHAR,
            is_place        BOOLEAN,
            topic_sort      INTEGER
        )
    """,
    "dim_dataset": """
        CREATE OR REPLACE TABLE dim_dataset (
            dataset_key        INTEGER,
            dataset_code       VARCHAR,
            dataset_name       VARCHAR,
            source_url         VARCHAR,
            local_path         VARCHAR,
            citation           VARCHAR,
            license            VARCHAR,
            provenance         VARCHAR,
            is_labelled        BOOLEAN,
            declared_precision VARCHAR,
            expected_rows      BIGINT,
            staged_rows        BIGINT
        )
    """,
    "dim_label": """
        CREATE OR REPLACE TABLE dim_label (
            label_key   INTEGER,
            label_code  VARCHAR,
            label_name  VARCHAR,
            label_value INTEGER,
            is_ground_truth BOOLEAN,
            description VARCHAR
        )
    """,
    "dim_instrument": """
        CREATE OR REPLACE TABLE dim_instrument (
            instrument_key   INTEGER,
            instrument_code  VARCHAR,
            instrument_name  VARCHAR,
            exchange         VARCHAR,
            currency         VARCHAR,
            source_dataset   VARCHAR
        )
    """,
}

LABELS = [
    # key, code, name, value, ground truth, description
    (1, "REAL", "Real news", 1, True,
     "Labelled real by the IFND source. The only rows that support accuracy claims."),
    (2, "FAKE", "Fake news", 0, True,
     "Labelled fake by the IFND source. Partly produced by an LSTM augmentation "
     "algorithm, so a model trained on it is evaluated on an easier distribution "
     "than genuine fake news."),
    (3, "UNLABELLED", "Unlabelled", None, False,
     "No ground truth exists. TOI headlines and market rows live here. Measures "
     "over these rows are risk-signal rates, never fake-news rates."),
]


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_dims(
    con: duckdb.DuckDBPyConnection, *, topic_map: TopicMap, specs: dict[str, DatasetSpec]
) -> dict[str, int]:
    """Build all five dimensions. Returns row counts by table name."""
    counts: dict[str, int] = {}

    for name in DDL:
        con.execute(f"DROP TABLE IF EXISTS {name}")

    # dim_date is generated from the data, so its own CREATE lives in its
    # builder. The other four are fixed shapes, created here then filled.
    for name in ("dim_topic", "dim_dataset", "dim_label", "dim_instrument"):
        con.execute(DDL[name])

    _build_dim_date(con)
    counts["dim_date"] = _count(con, "dim_date")

    _build_dim_topic(con, topic_map)
    counts["dim_topic"] = _count(con, "dim_topic")

    _build_dim_dataset(con, specs)
    counts["dim_dataset"] = _count(con, "dim_dataset")

    _build_dim_label(con)
    counts["dim_label"] = _count(con, "dim_label")

    _build_dim_instrument(con, specs)
    counts["dim_instrument"] = _count(con, "dim_instrument")

    for name, n in counts.items():
        log.info("%s: %s rows", name, human_int(n))
    return counts


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _build_dim_date(con: duckdb.DuckDBPyConnection) -> None:
    from dwm.etl.dates import date_key_expr, ifnd_date_value_expr, nifty_date_expr, toi_date_expr

    toi = toi_date_expr()
    nifty = nifty_date_expr()
    ifnd = ifnd_date_value_expr()
    con.execute(
        DDL["dim_date"].format(toi=toi, nifty=nifty, ifnd=ifnd)
    )
    # Guarantee the surrogate key matches the fact-side expression exactly.
    con.execute(
        f"""
        UPDATE dim_date
        SET date_key = {date_key_expr('full_date')}
        WHERE date_key IS DISTINCT FROM {date_key_expr('full_date')}
        """
    )


def _build_dim_topic(con: duckdb.DuckDBPyConnection, topic_map: TopicMap) -> None:
    names = list(dict.fromkeys(topic_map.topics))
    rows = []
    for i, name in enumerate(names, start=1):
        group = TOPIC_GROUPS.get(name, "Other")
        rows.append((i, name, group, name in PLACE_TOPICS, i))
    con.executemany("INSERT INTO dim_topic VALUES (?, ?, ?, ?, ?)", rows)


def _build_dim_dataset(
    con: duckdb.DuckDBPyConnection, specs: dict[str, DatasetSpec]
) -> None:
    from dwm.ingest.staging import stage_table_name

    for i, code in enumerate(sorted(specs), start=1):
        spec = specs[code]
        table = stage_table_name(code)
        staged = 0
        if con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()[0]:
            staged = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        con.execute(
            """
            INSERT INTO dim_dataset VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                i,
                code,
                spec.name,
                spec.url,
                str(spec.local_path()),
                spec.citation,
                spec.license,
                spec.provenance,
                spec.is_labelled,
                spec.declared_date_precision,
                spec.expected_rows,
                staged,
            ],
        )


def _build_dim_label(con: duckdb.DuckDBPyConnection) -> None:
    con.executemany("INSERT INTO dim_label VALUES (?, ?, ?, ?, ?, ?)", LABELS)


def _build_dim_instrument(
    con: duckdb.DuckDBPyConnection, specs: dict[str, DatasetSpec]
) -> None:
    nifty = specs.get("nifty")
    if nifty is None:
        return
    raw = nifty.raw or {}
    con.execute(
        """
        INSERT INTO dim_instrument VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            1,
            str(raw.get("instrument") or "NIFTY50"),
            "Nifty 50 index",
            "NSE",
            "INR",
            "nifty",
        ],
    )


def dim_date_bounds(con: duckdb.DuckDBPyConnection) -> tuple[str, str] | None:
    row = con.execute("SELECT min(full_date), max(full_date) FROM dim_date").fetchone()
    if not row or row[0] is None:
        return None
    return row[0].isoformat(), row[1].isoformat()
