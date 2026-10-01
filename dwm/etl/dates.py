"""Date resolution for the ETL stage.

Two strategies, chosen per dataset by how messy the source actually is:

* TOI (`YYYYMMDD`) and nifty (`YYYY-MM-DD`) are single, verified formats, so
  they are parsed in SQL. That keeps 3.3M rows off the Python interpreter.
* IFND mixes month-year, day-without-year and empty, so it goes through a
  Python UDF that calls the tested parser in `dwm/parse.py`. Correctness beats
  speed on 56k rows.

Both paths are checked against each other in `tests/test_etl_dates.py`, so
they cannot silently diverge.
"""

from __future__ import annotations

import contextlib

import duckdb

from dwm.config import DatasetSpec
from dwm.parse import parse_date

# UDF names registered on the connection.
FN_VALUE = "dwm_date_value"
FN_PRECISION = "dwm_date_precision"


def register_date_functions(
    con: duckdb.DuckDBPyConnection, spec: DatasetSpec
) -> None:
    """Register the Python date UDFs for one dataset's formats.

    Bound to the connection rather than global, so two datasets with different
    format lists cannot interfere.
    """
    formats = list(spec.date_formats)

    def value(raw: str | None) -> str | None:
        parsed = parse_date(raw, formats)
        return parsed.value.isoformat() if parsed.value else None

    def precision(raw: str | None) -> str:
        return parse_date(raw, formats).precision

    for name, fn in ((FN_VALUE, value), (FN_PRECISION, precision)):
        # Tolerate a fresh connection: remove_function raises if absent.
        with contextlib.suppress(duckdb.Error):
            con.remove_function(name)
        # Types are given as SQL type names; duckdb.typing is not importable
        # in duckdb 1.5.x and dict parameters are rejected.
        con.create_function(name, fn, ["VARCHAR"], "VARCHAR", null_handling="special")


def simple_date_expr(formats: list[str], column: str = "raw_date") -> str:
    """SQL expression resolving `column` via strptime, trying each format.

    Returns NULL when nothing matches. The value is a DATE cast.
    """
    attempts = [f"try_strptime(trim({column}), '{fmt}')" for fmt in formats]
    return "CAST(" + "coalesce(" + ", ".join(attempts) + ")" + " AS DATE)"


def toi_date_expr(column: str = "raw_date") -> str:
    """TOI dates are YYYYMMDD, verified: 7,080 distinct values, 0 failures."""
    return f"CAST(strptime(trim({column}), '%Y%m%d') AS DATE)"


def nifty_date_expr(column: str = "raw_date") -> str:
    formats = ["%Y-%m-%d", "%d-%b-%y", "%d-%m-%Y", "%d-%b-%Y"]
    return simple_date_expr(formats, column)


def ifnd_date_value_expr(column: str = "raw_date") -> str:
    return f'CAST({FN_VALUE}({column}) AS DATE)'


def ifnd_date_precision_expr(column: str = "raw_date") -> str:
    return f"{FN_PRECISION}({column})"


def date_key_expr(date_expr: str) -> str:
    """YYYYMMDD integer surrogate key from a DATE expression."""
    return f"CAST(strftime({date_expr}, '%Y%m%d') AS INTEGER)"
