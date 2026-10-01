"""etl_audit: the data-quality funnel.

Every stage writes one row per (dataset, step) so the report can show where
rows were lost, and so the Phase gates can be checked from the warehouse
itself rather than from log text (BLUEPRINT section 4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import duckdb

CREATE_AUDIT_SQL = """
CREATE SEQUENCE IF NOT EXISTS etl_audit_id_seq START 1;

CREATE TABLE IF NOT EXISTS etl_audit (
    audit_id      BIGINT DEFAULT nextval('etl_audit_id_seq'),
    run_id        VARCHAR,
    dataset_code  VARCHAR,
    step          VARCHAR,
    status        VARCHAR,
    rows_read     BIGINT,
    rows_loaded   BIGINT,
    rows_rejected BIGINT,
    detail        VARCHAR,
    started_at    TIMESTAMP,
    finished_at   TIMESTAMP,
    elapsed_s     DOUBLE
)
"""

def ensure_audit_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(CREATE_AUDIT_SQL)


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def record(
    con: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    dataset_code: str,
    step: str,
    info: dict[str, Any],
    status: str,
    started_at: datetime,
) -> int:
    """Insert one audit row. Returns the new audit_id."""
    detail = {
        k: v
        for k, v in info.items()
        if k not in {"status", "elapsed_s"}
    }
    row = con.execute(
        """
        INSERT INTO etl_audit (
            run_id, dataset_code, step, status, rows_read, rows_loaded,
            rows_rejected, detail, started_at, finished_at, elapsed_s
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING audit_id
        """,
        [
            run_id,
            dataset_code,
            step,
            status,
            int(info.get("rows_read", 0) or 0),
            int(info.get("rows_loaded", 0) or 0),
            int(info.get("rows_rejected", 0) or 0),
            _to_json(detail),
            started_at,
            datetime.now(UTC).replace(tzinfo=None),
            float(info.get("elapsed_s") or 0.0),
        ],
    ).fetchone()
    if not row or row[0] is None:  # pragma: no cover - sequence guarantees a value
        raise RuntimeError(f"etl_audit insert returned no audit_id for {dataset_code}/{step}")
    return int(row[0])


def _to_json(payload: dict[str, Any]) -> str:
    import json

    def default(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    return json.dumps(payload, default=default, sort_keys=True)


def funnel(con: duckdb.DuckDBPyConnection, run_id: str | None = None) -> list[dict[str, Any]]:
    """Audit rows for a run, ordered by step. Used by tests and the report.

    Returns an empty list when no audit has been written yet, so querying a
    fresh warehouse is not an error.
    """
    present = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'etl_audit'"
    ).fetchone()[0]
    if not present:
        return []
    where = "WHERE run_id = ?" if run_id else ""
    params = [run_id] if run_id else []
    rows = con.execute(
        f"""
        SELECT run_id, dataset_code, step, status, rows_read, rows_loaded,
               rows_rejected, elapsed_s
        FROM etl_audit
        {where}
        ORDER BY dataset_code, audit_id
        """,
        params,
    ).fetchall()
    columns = [
        "run_id", "dataset_code", "step", "status",
        "rows_read", "rows_loaded", "rows_rejected", "elapsed_s",
    ]
    return [dict(zip(columns, row, strict=True)) for row in rows]
