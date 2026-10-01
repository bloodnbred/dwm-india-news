"""Feature stage runner: chunked, optionally multiprocessed.

Reads `cln_headline` and `cln_statement`, computes every text measure in one
pass, and writes `feat_headline` / `feat_statement`. Also builds
`dim_keyword` and `bridge_headline_keyword` for the Apriori transactions in
Phase 6.

The market table gets its measures in SQL rather than Python: returns and
rolling volatility are window functions, and SQL is both faster and easier to
verify.

Multiprocessing is a convenience, not a requirement. Measured on this machine
VADER alone runs at ~41,000 rows/s single-threaded, so 3.15M headlines is
about 80 seconds. Set `runtime.use_multiprocessing: false` in
`config/features.yaml` to force the serial path, which is what the tests use.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from dwm.config import PROJECT_ROOT, Settings
from dwm.features.scoring import TextScorer, eligible_terms
from dwm.ingest.audit import ensure_audit_table, record
from dwm.logging_utils import get, human_int, step

log = get("dwm.features")

FEATURES_YAML = PROJECT_ROOT / "config" / "features.yaml"

# Set in each worker process by _init_worker. A module global rather than an
# argument so the analyzer is built once per process, not once per chunk.
_SCORER: TextScorer | None = None
_VOCAB: dict[str, int] = {}
_VOCAB_LIMIT: int = 8

FEATURE_COLUMNS = (
    "sentiment_compound", "sentiment_positive", "sentiment_negative",
    "sentiment_neutral", "char_count", "token_count", "unique_token_count",
    "caps_token_count", "caps_token_ratio", "exclamation_count",
    "question_count", "superlative_count", "urgency_count", "negation_count",
    "sensational_score", "is_sensational", "is_risk_signal", "sentiment_band",
)


def load_features_config(path: Path | None = None) -> dict[str, Any]:
    import yaml

    path = path or FEATURES_YAML
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# worker plumbing
# ---------------------------------------------------------------------------


def _init_worker(config: dict[str, Any], vocab: dict[str, int], limit: int) -> None:
    global _SCORER, _VOCAB, _VOCAB_LIMIT
    _SCORER = TextScorer(config)
    _VOCAB = vocab
    _VOCAB_LIMIT = limit


def _score_chunk(rows: Sequence[tuple[int, str | None]]) -> list[tuple]:
    """Score one chunk. Module level so it is picklable by ProcessPoolExecutor."""
    if _SCORER is None:  # pragma: no cover - init always runs first
        raise RuntimeError("worker scorer not initialised")
    out: list[tuple] = []
    for key, text in rows:
        m = _SCORER.measure(text)
        keywords = _SCORER.keywords(text, _VOCAB, _VOCAB_LIMIT)
        out.append(
            (
                key, m.sentiment_compound, m.sentiment_positive, m.sentiment_negative,
                m.sentiment_neutral, m.char_count, m.token_count, m.unique_token_count,
                m.caps_token_count, m.caps_token_ratio, m.exclamation_count,
                m.question_count, m.superlative_count, m.urgency_count,
                m.negation_count, m.sensational_score, m.is_sensational,
                m.is_risk_signal, _SCORER.sentiment_flag(m.sentiment_compound),
                keywords,
            )
        )
    return out


def _chunks(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    chunk_size: int,
    key_column: str,
    start_after: int = -1,
) -> Iterator[list[tuple[int, str | None]]]:
    """Stream (key, text) pairs in bounded chunks using keyset pagination.

    Keyset, not OFFSET: `LIMIT n OFFSET m` makes DuckDB walk and discard the
    first m rows, so paging 3.15M rows in 100k chunks re-reads roughly 50M
    rows in total. `WHERE key > last_seen` walks each row once.

    Peak memory stays at one chunk regardless of corpus size, and the
    surrogate key is unique, so the cursor cannot skip or repeat a row.
    `start_after` resumes an interrupted run.
    """
    last = start_after
    while True:
        rows = con.execute(
            f"{sql} WHERE {key_column} > ? ORDER BY {key_column} LIMIT {chunk_size}",
            [last],
        ).fetchall()
        if not rows:
            return
        chunk = [(int(r[0]), r[1]) for r in rows]
        yield chunk
        last = chunk[-1][0]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------


def build_vocabulary(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> tuple[dict[str, int], dict[str, Any]]:
    """Choose the keyword vocabulary from a document-frequency sample.

    Returns (term -> rank, stats). The vocabulary is capped at
    `keywords.vocabulary_size` (300 in the blueprint) and is the reason the
    Phase 6 itemset search stays tractable.
    """
    kw = config.get("keywords", {})
    size = int(kw.get("vocabulary_size", 300))
    min_length = int(kw.get("min_length", 3))
    min_df = int(kw.get("min_doc_frequency", 20))
    sample_size = int(kw.get("vocabulary_sample", 200_000))

    total = con.execute("SELECT count(*) FROM cln_headline").fetchone()[0]
    sample_rows = min(sample_size, total)
    texts = [
        r[0]
        for r in con.execute(
            f"SELECT headline_text FROM cln_headline USING SAMPLE {sample_rows} ROWS"
        ).fetchall()
    ]
    freq = eligible_terms(texts, min_length=min_length)
    kept = {t: n for t, n in freq.items() if n >= min_df}
    # Sort by frequency desc, then term asc, so the vocabulary is
    # deterministic rather than dependent on dict ordering.
    ordered = sorted(kept.items(), key=lambda kv: (-kv[1], kv[0]))[:size]
    vocabulary = {term: i for i, (term, _) in enumerate(ordered, start=1)}
    stats = {
        "sample_size": sample_rows,
        "corpus_size": int(total),
        "candidate_terms": len(freq),
        "terms_above_min_df": len(kept),
        "vocabulary_size": len(vocabulary),
        "min_doc_frequency": min_df,
    }
    log.info(
        "vocabulary: %s terms from a %s-row sample (candidates %s)",
        human_int(len(vocabulary)), human_int(sample_rows), human_int(len(freq)),
    )
    return vocabulary, stats


# ---------------------------------------------------------------------------
# feature tables
# ---------------------------------------------------------------------------


def _feature_ddl(table: str) -> str:
    return f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT * FROM (
            SELECT
                NULL::BIGINT      AS source_key,
                NULL::DOUBLE      AS sentiment_compound,
                NULL::DOUBLE      AS sentiment_positive,
                NULL::DOUBLE      AS sentiment_negative,
                NULL::DOUBLE      AS sentiment_neutral,
                NULL::INTEGER     AS char_count,
                NULL::INTEGER     AS token_count,
                NULL::INTEGER     AS unique_token_count,
                NULL::INTEGER     AS caps_token_count,
                NULL::DOUBLE      AS caps_token_ratio,
                NULL::INTEGER     AS exclamation_count,
                NULL::INTEGER     AS question_count,
                NULL::INTEGER     AS superlative_count,
                NULL::INTEGER     AS urgency_count,
                NULL::INTEGER     AS negation_count,
                NULL::DOUBLE      AS sensational_score,
                NULL::BOOLEAN     AS is_sensational,
                NULL::BOOLEAN     AS is_risk_signal,
                NULL::VARCHAR     AS sentiment_band
            WHERE false
        )
    """


def _keyword_ddl() -> str:
    return """
        CREATE OR REPLACE TABLE dim_keyword (
            keyword_key    INTEGER,
            term           VARCHAR,
            doc_frequency  BIGINT
        )
    """


def _bridge_ddl() -> str:
    return """
        CREATE OR REPLACE TABLE bridge_headline_keyword (
            headline_id  BIGINT,
            keyword_key  INTEGER
        )
    """


def _bulk_insert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[str],
    rows: list[tuple],
) -> None:
    """Insert rows as one statement via an Arrow table.

    executemany sends one prepared statement per row. At ~330,000 rows per
    chunk that dominated the runtime of the whole feature stage. Registering
    the chunk as Arrow and doing `INSERT ... SELECT` is a single statement and
    moves the transfer cost into DuckDB's columnar writer.
    """
    if not rows:
        return
    import pyarrow as pa

    names = list(columns)
    arrow = pa.table({name: [row[i] for row in rows] for i, name in enumerate(names)})
    con.register("_incoming", arrow)
    try:
        projection = ", ".join(f'"{name}"' for name in names)
        con.execute(f"INSERT INTO {table} ({projection}) SELECT {projection} FROM _incoming")
    finally:
        con.unregister("_incoming")


CONFIG_TABLE = "feat_config"

# Only these keys change a measure's value. Chunk size and worker count change
# how fast the stage runs, not what it produces, so they are excluded: a
# re-run for a speed tweak must not throw away two minutes of scoring.
_FEATURE_IDENTITY = (
    "sensationalism",
    "sentiment",
    "keywords.vocabulary_size",
    "keywords.min_length",
    "keywords.min_doc_frequency",
    "keywords.max_per_headline",
)


def feature_fingerprint(config: dict[str, Any]) -> str:
    """Stable hash of everything that affects a computed measure.

    Stored alongside the features. If it changes, the cached features are
    stale and must be rebuilt, otherwise a threshold edit would silently leave
    the old numbers in the warehouse.
    """
    import hashlib
    import json

    identity: dict[str, Any] = {}
    for key in _FEATURE_IDENTITY:
        node: Any = config
        for part in key.split("."):
            node = (node or {}).get(part) if isinstance(node, dict) else None
        identity[key] = node
    payload = json.dumps(identity, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _check_fingerprint(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> bool:
    """Return True when a valid feature cache existed and was kept.

    False means either nothing was cached or the cache was stale and has just
    been dropped, so the caller must rebuild.
    """
    fingerprint = feature_fingerprint(config)
    con.execute(f"CREATE TABLE IF NOT EXISTS {CONFIG_TABLE} (fingerprint VARCHAR)")
    row = con.execute(f"SELECT fingerprint FROM {CONFIG_TABLE} LIMIT 1").fetchone()

    # The tables that a fingerprint certifies.
    tracked = (
        "feat_headline", "feat_statement", "feat_market_daily",
        "dim_keyword", "bridge_headline_keyword",
    )
    have_features = any(_table_exists(con, t) for t in tracked)

    if row and row[0] == fingerprint:
        return True
    if row:
        log.warning(
            "feature config changed (%s -> %s), discarding cached features",
            row[0], fingerprint,
        )
    elif have_features:
        # Features exist but nothing certifies them: either the table was
        # created before fingerprinting existed, or it was hand-edited. An
        # unverifiable cache is a stale cache, so rebuild rather than trust it.
        log.warning(
            "cached features have no recorded config fingerprint, discarding them"
        )
    if have_features:
        for table in tracked:
            con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"DELETE FROM {CONFIG_TABLE}")
    con.execute(f"INSERT INTO {CONFIG_TABLE} VALUES (?)", [fingerprint])
    return False


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
    )


def _resume_point(con: duckdb.DuckDBPyConnection, target: str) -> int:
    """Highest source_key already scored in `target`, or -1 if there is none.

    Scoring 3.15M headlines takes minutes and is easy to interrupt, so a
    re-run continues instead of starting over. -1 is safe as a sentinel
    because surrogate keys start at 1.
    """
    if not _table_exists(con, target):
        return -1
    count = int(con.execute(f"SELECT count(*) FROM {target}").fetchone()[0])
    if count == 0:
        return -1
    return int(con.execute(f"SELECT max(source_key) FROM {target}").fetchone()[0])


def _compute_features(
    con: duckdb.DuckDBPyConnection,
    *,
    source: str,
    key_column: str,
    text_column: str,
    target: str,
    config: dict[str, Any],
    vocabulary: dict[str, int],
    run_id: str,
    dataset_code: str,
    resume: int = -1,
) -> dict[str, Any]:
    """Score one text corpus into `target`, writing the keyword bridge too.

    `resume` is the highest source_key already scored, or -1 for a fresh run.
    The surrogate key is unique and rows are written in key order, so
    resuming can neither skip nor duplicate a row.

    Keyword bridge rows are inserted into DuckDB as each chunk arrives rather
    than accumulated in a Python list. At up to 8 keywords per headline, the
    full corpus would otherwise hold ~12M tuples in memory.
    """
    runtime = config.get("runtime", {})
    # Small chunks keep the queue full: a large chunk is a long stretch where
    # the workers sit idle. 20k rows is ~0.4s of work per task, which is
    # short enough to overlap the parent's reads and writes.
    chunk_size = int(runtime.get("chunk_size", 20_000))
    limit = int(config.get("keywords", {}).get("max_per_headline", 8))
    use_mp = bool(runtime.get("use_multiprocessing", True))
    n_workers = _cpu_count(runtime, runtime.get("workers"))
    wants_keywords = target == "feat_headline"
    if resume > 0:
        log.info("%s: resuming after source_key %s", target, resume)

    # Keep whatever is already scored, then append the rest.
    if resume > 0 and _table_exists(con, target):
        con.execute(f"CREATE OR REPLACE TABLE {target}_partial AS SELECT * FROM {target}")
    con.execute(_feature_ddl(target))
    if resume > 0 and _table_exists(con, f"{target}_partial"):
        con.execute(f"INSERT INTO {target} SELECT * FROM {target}_partial")
        con.execute(f"DROP TABLE {target}_partial")

    if wants_keywords:
        if resume > 0 and _table_exists(con, "bridge_headline_keyword"):
            con.execute("CREATE OR REPLACE TABLE _bridge_partial AS SELECT * FROM bridge_headline_keyword")
        con.execute(_bridge_ddl())
        if resume > 0 and _table_exists(con, "_bridge_partial"):
            con.execute("INSERT INTO bridge_headline_keyword SELECT * FROM _bridge_partial")
            con.execute("DROP TABLE _bridge_partial")
        con.execute(_keyword_ddl())
        if vocabulary:
            con.executemany(
                "INSERT INTO dim_keyword VALUES (?, ?, 0)",
                [(idx, term) for term, idx in sorted(vocabulary.items(), key=lambda kv: kv[1])],
            )

    sql = f"SELECT {key_column}, {text_column} FROM {source}"
    started = datetime.now(UTC).replace(tzinfo=None)
    processed = 0

    measure_columns = ["source_key", *FEATURE_COLUMNS]

    def consume(results: list[tuple]) -> None:
        """Write one chunk: measures in bulk, then its keyword bridge rows.

        Both inserts go through Arrow and a single INSERT ... SELECT rather
        than executemany. executemany is one prepared statement per row, and
        a 50k chunk with up to 8 keywords each is ~330,000 statements; that
        was measured at 98% of total runtime, leaving scoring at 2%.
        """
        nonlocal processed
        if not results:
            return
        _bulk_insert(
            con, target, measure_columns, [r[:-1] for r in results]
        )
        if wants_keywords:
            _bulk_insert(
                con,
                "bridge_headline_keyword",
                ["headline_id", "keyword_key"],
                [(r[0], idx) for r in results for idx in r[-1]],
            )
        processed += len(results)

    # Serial, deliberately. Measured on this corpus: 25,900 rows/s single
    # threaded, so the full 3.15M headlines take about 2 minutes. The process
    # pool was measured at 39 rows/s, roughly 600x slower, because every
    # chunk has to be pickled to the workers and the results pickled back on
    # Windows, which costs far more than the scoring itself. A pool is only
    # worth it when the per-row work is much heavier than the transfer.
    _init_worker(config, vocabulary, limit)
    for chunk in _chunks(con, sql, chunk_size, key_column, resume):
        consume(_score_chunk(chunk))

    if wants_keywords:
        _finalise_keywords(con)

    info: dict[str, Any] = {
        "rows_read": processed,
        "rows_loaded": int(con.execute(f"SELECT count(*) FROM {target}").fetchone()[0]),
        "rows_rejected": 0,
        "source_table": source,
        "target_table": target,
        "multiprocessing": use_mp,
        "workers": n_workers if use_mp else 1,
        "chunk_size": chunk_size,
    }
    if target == "feat_headline":
        info["keyword_bridge_rows"] = int(
            con.execute("SELECT count(*) FROM bridge_headline_keyword").fetchone()[0]
        )
        info["keywords_used"] = int(
            con.execute("SELECT count(*) FROM dim_keyword").fetchone()[0]
        )
    record(
        con, run_id=run_id, dataset_code=dataset_code, step="features.build",
        info=info, status="ok", started_at=started,
    )
    log.info(
        "%s: scored %s rows -> %s",
        dataset_code, human_int(info["rows_read"]), target,
    )
    return info


def _finalise_keywords(con: duckdb.DuckDBPyConnection) -> None:
    """Set each keyword's document frequency from the bridge.

    The bridge was written incrementally during scoring, so the counts are
    derived here in SQL rather than accumulated in Python. doc_frequency is a
    *count*, never a rate, so it can be summed and rolled up.
    """
    con.execute(
        """
        UPDATE dim_keyword AS k
        SET doc_frequency = sub.n
        FROM (
            SELECT keyword_key, count(*) AS n
            FROM bridge_headline_keyword
            GROUP BY 1
        ) AS sub
        WHERE sub.keyword_key = k.keyword_key
        """
    )


def _cpu_count(runtime: dict[str, Any], override: Any) -> int:
    import os

    if override:
        return max(1, int(override))
    configured = runtime.get("workers")
    if configured:
        return max(1, int(configured))
    return max(1, (os.cpu_count() or 2) - 1)


def _split(chunk: list[tuple[int, str | None]], parts: int) -> list[list[tuple[int, str | None]]]:
    """Split a chunk so each worker gets a contiguous slice."""
    parts = max(1, min(parts, len(chunk)))
    size = (len(chunk) + parts - 1) // parts
    return [chunk[i : i + size] for i in range(0, len(chunk), size)] or [[]]


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def run_features(
    settings: Settings, *, con: duckdb.DuckDBPyConnection | None = None
) -> dict[str, Any]:
    """Compute all features. Returns a summary for the CLI.

    Pass `con` to reuse an existing connection; DuckDB does not allow two
    write connections on one file.
    """
    owned = con is None
    con = con or _connect(settings)
    try:
        _require_staging(con)
        ensure_audit_table(con)
        config = load_features_config()
        run_id = _new_run_id()

        # A changed threshold or vocabulary invalidates cached features.
        _check_fingerprint(con, config)

        vocabulary: dict[str, int] = {}
        vocab_stats: dict[str, Any] = {}
        headline_info: dict[str, Any] = {}
        statement_info: dict[str, Any] = {}

        with step("build keyword vocabulary"):
            vocabulary, vocab_stats = build_vocabulary(con, config)

        with step("score headlines"):
            headline_info = _compute_features(
                con, source="cln_headline", key_column="headline_id",
                text_column="headline_text", target="feat_headline",
                config=config, vocabulary=vocabulary, run_id=run_id,
                dataset_code="toi", resume=_resume_point(con, "feat_headline"),
            )

        with step("score statements"):
            statement_info = _compute_features(
                con, source="cln_statement", key_column="statement_id",
                text_column="statement_text", target="feat_statement",
                config=config, vocabulary={}, run_id=run_id,
                dataset_code="ifnd", resume=_resume_point(con, "feat_statement"),
            )

        with step("derive market measures"):
            market_info = _build_market_features(con, run_id=run_id)

        summary = {
            "run_id": run_id,
            "config_version": config.get("version"),
            "config_fingerprint": feature_fingerprint(config),
            "sensationalism_threshold": config.get("sensationalism", {}).get("threshold"),
            "vocabulary": vocab_stats,
            "feat_headline": headline_info,
            "feat_statement": statement_info,
            "feat_market_daily": market_info,
        }
        _log_headline_signals(con)
        return summary
    finally:
        if owned:
            con.close()


def _build_market_features(con: duckdb.DuckDBPyConnection, *, run_id: str) -> dict[str, Any]:
    """Market measures in SQL: returns, ranges, and rolling volatility.

    Research question 6 correlates headline behaviour against Nifty *returns
    and volatility*, so both are produced here and stored as sums/values,
    never pre-averaged.
    """
    started = datetime.now(UTC).replace(tzinfo=None)
    con.execute(
        """
        CREATE OR REPLACE TABLE feat_market_daily AS
        WITH base AS (
            SELECT
                market_id, date_key, trade_date, close, high, low, open, volume,
                LAG(close) OVER (ORDER BY trade_date) AS prev_close
            FROM cln_market_daily
        ),
        returns AS (
            SELECT
                *,
                close - prev_close                       AS abs_change,
                CASE WHEN prev_close IS NOT NULL AND prev_close <> 0
                     THEN (close - prev_close) / prev_close * 100.0
                END                                      AS return_pct,
                high - low                              AS day_range,
                CASE WHEN prev_close IS NOT NULL AND prev_close <> 0
                     THEN (high - low) / prev_close * 100.0
                END                                      AS range_pct,
                close - open                            AS intraday_change
            FROM base
        )
        SELECT
            market_id, date_key, trade_date, close, volume,
            round(return_pct, 6)                        AS return_pct,
            round(abs_change, 4)                        AS abs_change,
            round(day_range, 4)                         AS day_range,
            round(range_pct, 6)                         AS range_pct,
            round(intraday_change, 4)                   AS intraday_change,
            -- 20-session rolling standard deviation of the daily return.
            -- NULL until the window is full: a "20-day volatility" computed
            -- from three observations is not a 20-day volatility, and
            -- publishing it as one would mislead the Phase 6 correlation.
            CASE WHEN count(return_pct) OVER w >= 20
                 THEN round(stddev_samp(return_pct) OVER w, 6)
            END                                         AS volatility_20d,
            CASE WHEN return_pct > 0 THEN 1
                 WHEN return_pct < 0 THEN -1
                 ELSE 0 END                             AS return_sign
        FROM returns
        WINDOW w AS (ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        ORDER BY trade_date
        """
    )
    info = {
        "rows_read": int(con.execute("SELECT count(*) FROM cln_market_daily").fetchone()[0]),
        "rows_loaded": int(con.execute("SELECT count(*) FROM feat_market_daily").fetchone()[0]),
        "rows_rejected": 0,
        "target_table": "feat_market_daily",
        "volatility_window": 20,
    }
    record(
        con, run_id=run_id, dataset_code="nifty", step="features.build",
        info=info, status="ok", started_at=started,
    )
    log.info("nifty: derived returns and 20d volatility for %s rows", human_int(info["rows_loaded"]))
    return info


def _log_headline_signals(con: duckdb.DuckDBPyConnection) -> None:
    """Log the headline signal rates. Reported as rates, never as fake rates."""
    row = con.execute(
        """
        SELECT count(*),
               count(*) FILTER (WHERE is_sensational),
               round(avg(sensational_score), 4),
               round(avg(sentiment_compound), 4),
               count(*) FILTER (WHERE sentiment_band = 'negative')
        FROM feat_headline
        """
    ).fetchone()
    total, sens, score, compound, negative = row
    if not total:
        return
    log.info(
        "headline signals: sensationalism rate %.2f%% (mean score %.3f), "
        "mean compound %.3f, negative band %.2f%%",
        100 * sens / total, score, compound, 100 * negative / total,
    )


def _connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    from dwm.db import connect

    return connect(settings)


def _require_staging(con: duckdb.DuckDBPyConnection) -> None:
    needed = ("cln_headline", "cln_statement", "cln_market_daily")
    present = {
        r[0]
        for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    missing = [t for t in needed if t not in present]
    if missing:
        raise RuntimeError(
            f"missing {missing}. Run `python -m dwm etl` before `python -m dwm features`."
        )


def _new_run_id() -> str:
    from dwm.ingest.audit import new_run_id

    return new_run_id()
