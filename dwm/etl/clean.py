"""Clean tables produced by the ETL stage.

    cln_headline      one TOI headline per (date, text)
    cln_statement     one IFND statement, with a nullable date_key
    cln_market_daily  one Nifty 50 trading day

Three decisions worth stating, because they change the numbers:

1. **Grain and dedupe.** A TOI headline is identified by (date, text), not by
   text alone. Measured on the real data: 37,629 headline texts appear on more
   than one date, and 111,146 (date, text) pairs are filed under more than one
   category. Deduplicating on text alone would merge genuinely separate
   publications; keeping one row per category would multiply-count headlines
   in every topic analysis. So: one row per (date, text), and the primary
   category is the most frequent one, ties broken alphabetically. The number of
   categories each headline carried is kept in `category_count`.

2. **The window is a flag, not a filter.** Every cleaned row is kept and
   `in_window` marks membership of the analysis window. The funnel can then
   report how many rows the window excludes, which a hard filter would hide.
   The window is derived from the data via `analysis_window`, never hard-coded.

3. **IFND dates stay nullable.** Only 67% of IFND rows have a resolvable
   calendar date, 12.6% have a day but no year, and 20.2% have no date at all.
   `date_key` is NULL in those cases and `date_precision` records why. No year
   is ever guessed.
"""

from __future__ import annotations

from datetime import UTC

import duckdb

from dwm.config import DatasetSpec, Settings, TopicMap, analysis_window
from dwm.etl.dates import (
    date_key_expr,
    ifnd_date_precision_expr,
    ifnd_date_value_expr,
    nifty_date_expr,
    toi_date_expr,
)
from dwm.ingest.audit import ensure_audit_table, record
from dwm.logging_utils import get, human_int

log = get("dwm.etl.clean")

DDL_HEADLINE = """
    CREATE OR REPLACE TABLE cln_headline AS
    WITH typed AS (
        SELECT
            stg_row_id,
            {toi}       AS publish_date,
            raw_category,
            raw_text
        FROM stg_toi
        WHERE raw_text IS NOT NULL AND trim(raw_text) <> ''
    ),
    -- How often each (date, text) was filed under each category.
    cat_counts AS (
        SELECT publish_date, raw_text, raw_category, count(*) AS n
        FROM typed
        GROUP BY 1, 2, 3
    ),
    -- One row per (date, text). The primary category is the one it was filed
    -- under most often, ties broken alphabetically so the result is stable.
    picked AS (
        SELECT
            publish_date,
            raw_text,
            raw_category,
            count(*) OVER (PARTITION BY publish_date, raw_text) AS category_count,
            sum(n)     OVER (PARTITION BY publish_date, raw_text) AS staged_rows
        FROM cat_counts
        QUALIFY row_number() OVER (
            PARTITION BY publish_date, raw_text
            ORDER BY n DESC, raw_category ASC
        ) = 1
    )
    SELECT
        row_number() OVER (ORDER BY publish_date, raw_text) AS headline_id,
        publish_date,
        {date_key}                                         AS date_key,
        raw_category,
        split_part(raw_category, '.', 1)                  AS category_prefix,
        raw_text                                           AS headline_text,
        length(raw_text)                                   AS text_length,
        len(regexp_split_to_array(trim(raw_text), '\\s+'))  AS word_count,
        staged_rows,
        category_count,
        category_count > 1                                 AS is_multi_category,
        {date_key} BETWEEN {w_start} AND {w_end}           AS in_window
    FROM picked
    ORDER BY publish_date, raw_text
"""

DDL_STATEMENT = """
    CREATE OR REPLACE TABLE cln_statement AS
    WITH typed AS (
        SELECT
            stg_row_id,
            {ifnd}                        AS source_date,
            {ifnd_prec}                   AS date_precision,
            raw_category,
            raw_label,
            raw_text
        FROM stg_ifnd
    ),
    labelled AS (
        SELECT
            stg_row_id,
            source_date,
            date_precision,
            raw_category,
            raw_text,
            COALESCE(m.label_code, 'UNLABELLED') AS label_code
        FROM typed
        LEFT JOIN map_label_value m
               ON m.dataset_code = 'ifnd'
              AND m.raw_label = upper(trim(typed.raw_label))
    ),    -- One row per distinct statement text. A single representative row is
    -- chosen with QUALIFY so that source_date and date_precision always come
    -- from the SAME row. Using any_value() for each independently can pair a
    -- date from one row with the precision of another, which silently
    -- mislabels the precision. A row that has a date is preferred.
    deduped AS (
        SELECT
            source_date,
            date_precision,
            raw_category,
            label_code,
            raw_text,
            count(*) OVER (PARTITION BY raw_text) AS staged_rows
        FROM labelled
        WHERE raw_text IS NOT NULL AND trim(raw_text) <> ''
        QUALIFY row_number() OVER (
            PARTITION BY raw_text
            ORDER BY (source_date IS NULL) ASC, stg_row_id ASC
        ) = 1
    )
    SELECT
        row_number() OVER (ORDER BY raw_text) AS statement_id,
        source_date,
        {ifnd_key}                            AS date_key,
        date_precision,
        lower(trim(raw_category))             AS raw_category,
        raw_text                               AS statement_text,
        length(raw_text)                       AS text_length,
        len(regexp_split_to_array(trim(raw_text), '\\s+')) AS word_count,
        label_code,
        staged_rows,
        (source_date IS NOT NULL)             AS has_date,
        (source_date IS NOT NULL
            AND {ifnd_key} BETWEEN {w_start} AND {w_end}) AS in_window
    FROM deduped
    ORDER BY raw_text
"""

DDL_MARKET = """
    CREATE OR REPLACE TABLE cln_market_daily AS
    SELECT
        row_number() OVER (ORDER BY {nifty})      AS market_id,
        {nifty}                                   AS trade_date,
        {date_key}                                AS date_key,
        'NIFTY50'                                 AS instrument_code,
        raw_open                                  AS open,
        raw_high                                  AS high,
        raw_low                                   AS low,
        raw_close                                 AS close,
        raw_volume                                AS volume,
        raw_turnover                              AS turnover,
        {nifty} BETWEEN {w_start} AND {w_end}     AS in_window
    FROM stg_nifty
    WHERE {nifty} IS NOT NULL
    ORDER BY {nifty}
"""


def _q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _keys(lo: str, hi: str) -> tuple[str, str]:
    """Window bounds as the YYYYMMDD integers that date_key uses."""
    from datetime import date

    def key(iso: str) -> int:
        d = date.fromisoformat(iso)
        return d.year * 10000 + d.month * 100 + d.day

    return str(key(lo)), str(key(hi))


def window_from_staging(
    con: duckdb.DuckDBPyConnection, years: int
) -> tuple[str, str, str, str]:
    """Derive the analysis window from the data.

    The end is the maximum resolved TOI publish date; the start is `years`
    before it. Never hard-coded, per BLUEPRINT section 1.
    """
    toi = toi_date_expr()
    row = con.execute(f"SELECT max({toi}) FROM stg_toi").fetchone()
    if not row or row[0] is None:
        raise ValueError("stg_toi has no resolvable dates; run the ingest stage first")
    max_date = row[0]
    start, end = analysis_window(max_date, years)
    return start.isoformat(), end.isoformat(), str(max_date), f"{years}"


def build_clean(
    con: duckdb.DuckDBPyConnection,
    *,
    specs: dict[str, DatasetSpec],
    topic_map: TopicMap,
    settings: Settings,
    run_id: str,
) -> dict[str, object]:
    """Build the three clean tables and record the ETL audit rows.

    The date UDFs must already be registered on `con` by the caller; see
    `dwm.etl.dates.register_date_functions`.
    """
    w_start, w_end, max_date, years = window_from_staging(con, settings.years)
    k_start, k_end = _keys(w_start, w_end)
    log.info(
        "analysis window: %s .. %s (%s years, derived from max publish_date %s)",
        w_start, w_end, years, max_date,
    )

    # The label map must exist before cln_statement is built, because the
    # statement DDL joins to it.
    label_map_rows = _build_label_map(con, specs)

    toi = toi_date_expr()
    nifty = nifty_date_expr()
    ifnd_value = ifnd_date_value_expr()
    ifnd_prec = ifnd_date_precision_expr()

    before = {name: _count(con, name) for name in ("stg_toi", "stg_ifnd", "stg_nifty")}

    con.execute(
        DDL_HEADLINE.format(
            toi=toi, date_key=date_key_expr("publish_date"),
            w_start=k_start, w_end=k_end,
        )
    )
    con.execute(
        DDL_STATEMENT.format(
            ifnd=ifnd_value, ifnd_key=date_key_expr("source_date"), ifnd_prec=ifnd_prec,
            w_start=k_start, w_end=k_end,
        )
    )
    con.execute(
        DDL_MARKET.format(
            nifty=nifty, date_key=date_key_expr("trade_date"),
            w_start=f"DATE {_q(w_start)}", w_end=f"DATE {_q(w_end)}",
        )
    )

    after = {
        "cln_headline": _count(con, "cln_headline"),
        "cln_statement": _count(con, "cln_statement"),
        "cln_market_daily": _count(con, "cln_market_daily"),
    }

    # Topics are applied after the clean tables exist, because the mapping is
    # derived from the categories actually present in the data.
    map_info = _build_category_map(con, topic_map=topic_map, specs=specs)
    topic_info = _attach_topics(con)

    in_window = {
        "cln_headline": int(con.execute("SELECT count(*) FROM cln_headline WHERE in_window").fetchone()[0]),
        "cln_statement": int(con.execute("SELECT count(*) FROM cln_statement WHERE in_window").fetchone()[0]),
        "cln_market_daily": int(con.execute("SELECT count(*) FROM cln_market_daily WHERE in_window").fetchone()[0]),
    }

    info: dict[str, object] = {
        "rows_read": before["stg_toi"] + before["stg_ifnd"] + before["stg_nifty"],
        "rows_loaded": sum(after.values()),
        "rows_rejected": 0,
        "window_start": w_start,
        "window_end": w_end,
        "window_years": settings.years,
        "window_max_publish_date": max_date,
        "before": before,
        "after": after,
        "in_window": in_window,
        "duplicates_removed": {
            "headline": before["stg_toi"] - after["cln_headline"],
            "statement": before["stg_ifnd"] - after["cln_statement"],
        },
        "statement_without_date": int(
            con.execute("SELECT count(*) FROM cln_statement WHERE source_date IS NULL").fetchone()[0]
        ),
        "statement_date_precision": _precision_counts(con),
        "multi_category_headlines": int(
            con.execute("SELECT count(*) FROM cln_headline WHERE is_multi_category").fetchone()[0]
        ),
        "category_map": map_info,
        "label_map_rows": label_map_rows,
        **topic_info,
    }
    log.info(
        "cln_headline %s (from %s staged, %s dups removed, %s multi-category)",
        human_int(after["cln_headline"]), human_int(before["stg_toi"]),
        human_int(info["duplicates_removed"]["headline"]),  # type: ignore[index]
        human_int(info["multi_category_headlines"]),  # type: ignore[arg-type]
    )
    log.info(
        "cln_statement %s (from %s staged, %s dups removed, %s with no date)",
        human_int(after["cln_statement"]), human_int(before["stg_ifnd"]),
        human_int(info["duplicates_removed"]["statement"]),  # type: ignore[index]
        human_int(info["statement_without_date"]),  # type: ignore[arg-type]
    )
    log.info("cln_market_daily %s (from %s staged)", human_int(after["cln_market_daily"]), human_int(before["stg_nifty"]))

    ensure_audit_table(con)
    from datetime import datetime

    record(
        con, run_id=run_id, dataset_code="all", step="etl.clean",
        info=info, status="ok",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    return info


DDL_CATEGORY_MAP = """
    CREATE OR REPLACE TABLE map_category_topic (
        dataset_code  VARCHAR,
        raw_category  VARCHAR,
        topic_name    VARCHAR,
        topic_key     INTEGER
    )
"""


def _build_category_map(
    con: duckdb.DuckDBPyConnection, *, topic_map: TopicMap, specs: dict[str, DatasetSpec]
) -> dict[str, int]:
    """Persist the raw-category to topic mapping for every dataset.

    Only distinct categories are mapped, not rows: 1,016 distinct TOI
    categories cover 3.3M rows, so the Python lookup runs a few thousand
    times and the join happens in SQL. The table is keyed by dataset as well
    as category, because TOI and IFND resolve the same-looking string
    differently.
    """
    con.execute(DDL_CATEGORY_MAP)
    rows: list[tuple[str, str, str, int]] = []

    def add(dataset: str, table: str, resolve) -> None:
        found = con.execute(
            f"""
            SELECT DISTINCT lower(trim(raw_category)) AS c
            FROM {table}
            WHERE raw_category IS NOT NULL AND trim(raw_category) <> ''
            """
        ).fetchall()
        for (raw,) in found:
            rows.append((dataset, str(raw), resolve(str(raw)), 0))

    toi = specs.get("toi")
    if toi is not None:
        add("toi", "stg_toi", topic_map.lookup)

    ifnd = specs.get("ifnd")
    if ifnd is not None:
        fallback = topic_map.fallback_topic
        add(
            "ifnd",
            "stg_ifnd",
            lambda raw: topic_map.ifnd_category_map.get(raw.lower(), fallback),
        )

    if rows:
        con.executemany("INSERT INTO map_category_topic VALUES (?, ?, ?, ?)", rows)
    con.execute(
        """
        UPDATE map_category_topic AS m
        SET topic_key = t.topic_key
        FROM dim_topic AS t
        WHERE t.topic_name = m.topic_name
        """
    )
    unresolved = int(
        con.execute("SELECT count(*) FROM map_category_topic WHERE topic_key IS NULL").fetchone()[0]
    )
    if unresolved:
        log.warning("%s raw categories mapped to a topic absent from dim_topic", unresolved)
    return {"categories": len(rows)}


def _attach_topics(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Add topic_name and topic_key to the clean tables from the mapping."""
    for table, dataset in (("cln_headline", "toi"), ("cln_statement", "ifnd")):
        con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS topic_key INTEGER")
        con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS topic_name VARCHAR")
        con.execute(
            f"""
            UPDATE {table} AS f
            SET topic_key = m.topic_key, topic_name = m.topic_name
            FROM map_category_topic AS m
            WHERE m.dataset_code = '{dataset}'
              AND m.raw_category = lower(trim(f.raw_category))
            """
        )

    unmapped = int(
        con.execute("SELECT count(*) FROM cln_headline WHERE topic_name IS NULL").fetchone()[0]
    )
    return {"headlines_without_topic": unmapped}


DDL_LABEL_MAP = """
    CREATE OR REPLACE TABLE map_label_value (
        dataset_code  VARCHAR,
        raw_label     VARCHAR,
        label_code    VARCHAR
    )
"""


def _build_label_map(con: duckdb.DuckDBPyConnection, specs: dict[str, DatasetSpec]) -> int:
    """Build the raw-label to label_code mapping from config.

    The mapping comes from `config/datasets.yaml` and is applied by the tested
    `normalise_label`, not by a hard-coded SQL CASE. The IFND source mixes
    "TRUE", "FALSE" and "Fake" in the same column; a CASE over just 'TRUE' and
    'FALSE' silently turned "Fake" rows into UNLABELLED, which would have
    quietly removed fakes from the classifier's training data in Phase 6.
    """
    from dwm.parse import normalise_label

    con.execute(DDL_LABEL_MAP)
    ifnd = specs.get("ifnd")
    if ifnd is None or not ifnd.is_labelled:
        return 0

    accepted = ifnd.label_values
    found = [
        str(r[0])
        for r in con.execute(
            "SELECT DISTINCT raw_label FROM stg_ifnd "
            "WHERE raw_label IS NOT NULL AND trim(raw_label) <> ''"
        ).fetchall()
    ]
    rows: list[tuple[str, str, str]] = []
    unmapped: list[str] = []
    for raw in found:
        canonical = normalise_label(raw, accepted)
        if canonical is None:
            unmapped.append(raw)
            continue
        code = "REAL" if canonical == 1 else "FAKE"
        rows.append(("ifnd", raw.strip().upper(), code))

    if rows:
        con.executemany("INSERT INTO map_label_value VALUES (?, ?, ?)", rows)
    if unmapped:
        # Not fatal: an unrecognised label becomes UNLABELLED and is
        # reported, but it must not be silently folded into a class.
        log.warning(
            "ifnd: %d distinct raw label value(s) not in config, mapped to "
            "UNLABELLED: %s", len(unmapped), sorted(unmapped)[:10],
        )
    return len(rows)


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _precision_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = con.execute(
        "SELECT date_precision, count(*) FROM cln_statement GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return {str(p): int(n) for p, n in rows}
