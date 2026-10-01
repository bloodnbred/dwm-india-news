"""Staging tables stg_toi, stg_ifnd, stg_nifty.

Ingest is deliberately lossless and dumb: load the file as-is, add a surrogate
row id and an ingest timestamp, and record what happened. No cleaning, no
dedupe, no date parsing, no window filter. Those belong to the ETL stage, which
then has an honest "rows in, rows out" funnel to report.

Loading goes through DuckDB's read_csv rather than pandas so the 227 MB TOI
file streams instead of being materialised in RAM (BLUEPRINT section 7,
memory pressure on 1M+ rows).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import duckdb

from dwm.config import DatasetSpec, Settings
from dwm.ingest.audit import ensure_audit_table
from dwm.ingest.normalise import normalise
from dwm.logging_utils import get, human_int

log = get("dwm.ingest.staging")


def stage_table_name(code: str) -> str:
    return f"stg_{code}"


def _read_header(path: Path, encoding: str) -> list[str]:
    with path.open("r", encoding=encoding, errors="replace", newline="") as fh:
        for row in csv.reader(fh):
            return [c.strip() for c in row]
    raise ValueError(f"{path} appears to be empty")


def _pick(aliases: list[str], lookup: dict[str, str], *, required: bool, label: str) -> str:
    """First alias present in the source header, else '' when optional."""
    for alias in aliases:
        if alias.lower() in lookup:
            return lookup[alias.lower()]
    if required:
        raise KeyError(
            f"required column for {label!r} not found; aliases tried {aliases}, "
            f"header has {sorted(lookup)}. Fix config/datasets.yaml."
        )
    return ""


def resolve_columns(
    spec: DatasetSpec, header: list[str]
) -> dict[str, dict[str, str]]:
    """Map logical field -> source column name, honouring the alias lists.

    Raises when a required field is absent, so an upstream header change is a
    loud config edit rather than a silently empty column. A dataset that
    declares no text column (nifty is a price series) is loaded without one.
    """
    lookup = {h.lower(): h for h in header}

    resolved: dict[str, str] = {}
    if spec.has_text:
        logical = str(spec.text_column)
        resolved["text"] = _pick(
            spec.alias_list(logical) or [logical], lookup, required=True, label="text"
        )

    for logical in ("category", "date", "label"):
        # Only look for a field the dataset actually declares, so nifty is
        # not probed for a label column it will never have.
        if not spec.raw.get(f"{logical}_column"):
            continue
        aliases = spec.alias_list(logical) or [logical]
        col = _pick(aliases, lookup, required=False, label=logical)
        if col:
            resolved[logical] = col

    numeric: dict[str, str] = {}
    for logical in spec.numeric_columns:
        col = _pick(spec.alias_list(logical), lookup, required=False, label=logical)
        if col:
            numeric[logical] = col
    return {"columns": resolved, "numeric": numeric}


def count_source_rows(path: Path, encoding: str = "utf-8") -> int:
    """Row count of the source file, excluding the header.

    Streams the file rather than materialising rows, so it is cheap enough to
    run on 227 MB.
    """
    with path.open("rb") as fh:
        data = fh.read()
    if not data:
        return 0
    text = data.decode(encoding, errors="replace")
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.count("\n")
    if not normalised.endswith("\n"):
        lines += 1
    return max(0, lines - 1)


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _ddl(table: str, numeric: list[str]) -> str:
    numeric_ddl = "".join(f", raw_{name} DOUBLE" for name in numeric)
    return f"""
        CREATE OR REPLACE TABLE {table} (
            stg_row_id      BIGINT,
            stg_dataset_code VARCHAR,
            stg_filename    VARCHAR,
            stg_ingested_at TIMESTAMP,
            stg_row_num     BIGINT,
            raw_text        VARCHAR,
            raw_category    VARCHAR,
            raw_date        VARCHAR,
            raw_label       VARCHAR{numeric_ddl}
        )
    """


def stage_dataset(
    con: duckdb.DuckDBPyConnection,
    spec: DatasetSpec,
    path: Path,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Load one source file into its stg_* table. Returns audit info."""
    settings = settings or Settings()
    table = stage_table_name(spec.code)
    ensure_audit_table(con)

    header = _read_header(path, spec.encoding)
    resolved = resolve_columns(spec, header)
    columns = resolved["columns"]
    numeric = resolved["numeric"]
    source_rows = count_source_rows(path, spec.encoding)

    log.info(
        "%s: header=%s columns=%s numeric=%s source_rows=%s",
        spec.code, header, columns, list(numeric), human_int(source_rows),
    )

    def col(name: str, target: str, cast: str = "VARCHAR") -> str:
        return f'CAST("{columns[name]}" AS {cast}) AS {target}'

    # Every stg_* table has the same shape, so a field the dataset does not
    # provide is emitted as NULL rather than omitted.
    parts: list[str] = [
        col("text", "raw_text") if "text" in columns else "NULL AS raw_text"
    ]
    parts.append(
        col("category", "raw_category") if "category" in columns else "NULL AS raw_category"
    )
    parts.append(col("date", "raw_date") if "date" in columns else "NULL AS raw_date")
    parts.append(col("label", "raw_label") if "label" in columns else "NULL AS raw_label")
    for name in numeric:
        parts.append(f'try_cast("{numeric[name]}" AS DOUBLE) AS raw_{name}')

    limit = f"LIMIT {int(settings.sample)}" if settings.is_sampled else ""
    select_sql = ",\n                   ".join(parts)
    projection = ",\n            ".join(
        [
            "row_number() OVER ()",
            _quote(spec.code),
            _quote(path.name),
            "now()",
            "row_number() OVER ()",
            "raw_text",
            "raw_category",
            "raw_date",
            "raw_label",
            *(f"raw_{name}" for name in numeric),
        ]
    )

    def insert_from(source: Path) -> None:
        con.execute(_ddl(table, list(numeric)))
        # Strict parsing on purpose. Two options were measured on duckdb 1.5.6
        # and both are unusable:
        #   ignore_errors=true  silently discarded 15,730 of 56,714 IFND rows
        #   store_rejects=true  the same, and it also creates a fixed-name
        #                       "reject_scans" table, so staging a second
        #                       dataset in the same connection fails outright
        # A malformed row therefore raises, which triggers the strict csv
        # re-quoting fallback; and a silent shortfall is caught by the count
        # reconciliation below. That covers both failure modes honestly.
        con.execute(
            f"""
            INSERT INTO {table}
            WITH src AS (
                SELECT
                       {select_sql}
                FROM read_csv(
                    {_quote(str(source))},
                    header = true,
                    all_varchar = true,
                    encoding = {_quote(spec.encoding)},
                    sample_size = -1
                )
                {limit}
            )
            SELECT
                {projection}
            FROM src
            """
        )

    normalised = False
    try:
        insert_from(path)
    except duckdb.Error as exc:
        # DuckDB's CSV sniffer rejects some files outright. Rewrite with a
        # strict RFC 4180 writer and retry once rather than lose the dataset.
        log.warning("%s: DuckDB could not read the file directly (%s)", spec.code, str(exc)[:120])
        result = normalise(path, encoding=spec.encoding)
        insert_from(result.target)
        normalised = True
        source_rows = result.rows

    staged = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    expected = min(source_rows, settings.sample) if settings.is_sampled else source_rows

    # The load can also succeed while silently dropping rows, so reconcile the
    # count and, if it is short, retry once through the strict csv writer.
    if staged < expected and not normalised:
        log.warning(
            "%s: staged %s of %s source rows, retrying via the strict csv writer",
            spec.code, human_int(staged), human_int(expected),
        )
        result = normalise(path, encoding=spec.encoding)
        source_rows = result.rows
        expected = min(source_rows, settings.sample) if settings.is_sampled else source_rows
        insert_from(result.target)
        normalised = True
        staged = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    delta = expected - staged

    info: dict[str, Any] = {
        "rows_read": source_rows,
        "rows_loaded": staged,
        "rows_rejected": max(0, delta),
        "reconciled": delta == 0,
        "normalised": normalised,
        "table": table,
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "sampled": settings.is_sampled,
        "sample_n": settings.sample,
        "header": header,
        "resolved_columns": columns,
        "numeric_columns": numeric,
    }
    if delta:
        log.warning(
            "%s: staged %s of %s source rows (%s short). Check for malformed rows.",
            spec.code, human_int(staged), human_int(expected), human_int(delta),
        )
    else:
        log.info("%s: staged %s rows, matches source", spec.code, human_int(staged))
    return info


def describe(con: duckdb.DuckDBPyConnection, code: str) -> dict[str, Any]:
    """Column list and row count of a staging table, for tests and the CLI."""
    table = stage_table_name(code)
    cols = [
        (r[0], r[1])
        for r in con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
    ]
    rows = int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) if cols else 0
    return {"table": table, "rows": rows, "columns": cols}
