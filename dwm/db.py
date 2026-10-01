"""DuckDB connection helper.

One warehouse file, opened by every stage. The staging tables, the dimensions,
the facts and the cubes all live in it so a professor can open the file after
the run and run any SQL by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from dwm.config import Settings, memory_limit, threads

STAGING_TABLES = ("stg_toi", "stg_ifnd", "stg_nifty")
DIM_TABLES = ("dim_date", "dim_topic", "dim_dataset", "dim_label", "dim_instrument")
FACT_TABLES = ("fact_headline", "fact_statement", "fact_market_daily")
CUBE_TABLES = ("cube_month_topic", "cube_year_topic", "cube_topic_sentiment")


def connect(settings: Settings | None = None, *, create: bool = True) -> duckdb.DuckDBPyConnection:
    """Open (and if needed create) the warehouse file."""
    settings = settings or Settings()
    path: Path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "tmp").mkdir(parents=True, exist_ok=True)
    # Do not touch() the path: DuckDB refuses to open a zero-byte file, and
    # duckdb.connect() creates the database itself when it is absent.
    if not path.exists() and not create:
        raise FileNotFoundError(f"warehouse not found: {path} (run the ingest stage first)")

    con = duckdb.connect(str(path), read_only=False if create else settings.read_only)
    con.execute(f"SET threads TO {threads()}")
    con.execute(f"SET memory_limit = '{memory_limit()}'")
    # Keep our temp space next to the warehouse, not in the user temp dir.
    con.execute(f"SET temp_directory = '{(path.parent / 'tmp').as_posix()}'")
    return con


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()
    return bool(row and row[0])


def count_rows(con: duckdb.DuckDBPyConnection, name: str) -> int:
    """Row count of a table, or 0 when the table is absent."""
    if not table_exists(con, name):
        return 0
    return int(con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])


def all_counts(con: duckdb.DuckDBPyConnection, names: tuple[str, ...]) -> dict[str, int]:
    return {name: count_rows(con, name) for name in names}


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    row = con.execute(sql, params or []).fetchone()
    return row[0] if row else None
