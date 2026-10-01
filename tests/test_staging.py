"""Staging: the Phase 1 gate.

The gate is "row counts in staging equal rows in source file". These tests
assert that on small fixtures, so a regression shows up without a 227 MB
download.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from dwm.config import Settings, load_datasets_config
from dwm.ingest import audit
from dwm.ingest.staging import (
    count_source_rows,
    describe,
    resolve_columns,
    stage_dataset,
    stage_table_name,
)
from dwm.logging_utils import step


def test_count_source_rows_excludes_header(toi_csv: Path) -> None:
    assert count_source_rows(toi_csv) == 6


def test_resolve_columns_finds_every_field() -> None:
    specs = load_datasets_config()
    header = ["publish_date", "headline_category", "headline_text"]
    resolved = resolve_columns(specs["toi"], header)
    assert resolved["columns"]["text"] == "headline_text"
    assert resolved["columns"]["date"] == "publish_date"
    assert resolved["columns"]["category"] == "headline_category"
    assert resolved["numeric"] == {}


def test_resolve_columns_honours_nifty_aliases() -> None:
    specs = load_datasets_config()
    header = ["Date", "Open", "High", "Low", "Close", "Volume", "Turnover"]
    resolved = resolve_columns(specs["nifty"], header)
    assert resolved["numeric"] == {
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume", "turnover": "Turnover",
    }


def test_resolve_columns_raises_on_missing_required_column() -> None:
    import pytest

    specs = load_datasets_config()
    # No alias for the text field anywhere in this header.
    with pytest.raises(KeyError):
        resolve_columns(specs["toi"], ["id", "nope"])


def test_resolve_columns_allows_absent_text_for_nifty() -> None:
    specs = load_datasets_config()
    resolved = resolve_columns(specs["nifty"], ["Date", "Open", "High", "Low", "Close"])
    assert "text" not in resolved["columns"]
    assert resolved["columns"]["date"] == "Date"


def test_stage_toi_rows_match_source(con, toi_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["toi"]
    info = stage_dataset(con, spec, toi_csv, settings=settings)

    # The gate.
    assert info["rows_read"] == 6
    assert info["rows_loaded"] == 6
    assert info["rows_rejected"] == 0

    table = stage_table_name("toi")
    assert int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]) == 6


def test_stage_toi_keeps_values_verbatim(con, toi_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["toi"]
    stage_dataset(con, spec, toi_csv, settings=settings)
    row = con.execute(
        f"""
        SELECT raw_date, raw_category, raw_text
        FROM {stage_table_name('toi')}
        WHERE raw_text LIKE 'Parliament clears%'
        """
    ).fetchone()
    assert row is not None
    # Ingest must not clean anything: raw values pass through untouched.
    assert row[0] == "20010104"
    assert row[1] == "politics.parliament"
    assert row[2].endswith("!!!")


def test_staging_adds_surrogate_keys(con, toi_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["toi"]
    stage_dataset(con, spec, toi_csv, settings=settings)
    table = stage_table_name("toi")
    distinct_ids = con.execute(f"SELECT count(DISTINCT stg_row_id) FROM {table}").fetchone()[0]
    rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    assert distinct_ids == rows
    assert con.execute(f"SELECT count(DISTINCT stg_dataset_code) FROM {table}").fetchone()[0] == 1


def test_sample_caps_row_count(con, toi_csv: Path, tmp_path: Path) -> None:
    spec = load_datasets_config()["toi"]
    limited = Settings(db_path=tmp_path / "s.duckdb", sample=2)
    info = stage_dataset(con, spec, toi_csv, settings=limited)
    assert info["rows_loaded"] == 2
    # rows_read still reports the true source size, so the funnel is honest.
    assert info["rows_read"] == 6
    assert info["sampled"] is True


def test_stage_ifnd_keeps_raw_label(con, ifnd_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["ifnd"]
    info = stage_dataset(con, spec, ifnd_csv, settings=settings)
    assert info["rows_loaded"] == 3
    labels = [
        r[0]
        for r in con.execute(
            f"SELECT raw_label FROM {stage_table_name('ifnd')} ORDER BY stg_row_id"
        ).fetchall()
    ]
    # Mixed case in the source ("TRUE" and "Fake") is preserved for ETL to map.
    assert labels == ["TRUE", "TRUE", "Fake"]


def test_stage_nifty_needs_no_text_column(con, nifty_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["nifty"]
    info = stage_dataset(con, spec, nifty_csv, settings=settings)
    assert info["rows_loaded"] == 3
    # raw_text exists but stays NULL for a price series.
    assert con.execute(
        f"SELECT count(*) FROM {stage_table_name('nifty')} WHERE raw_text IS NOT NULL"
    ).fetchone()[0] == 0
    row = con.execute(
        f"""
        SELECT raw_open, raw_high, raw_close, raw_volume
        FROM {stage_table_name('nifty')}
        ORDER BY stg_row_id LIMIT 1
        """
    ).fetchone()
    assert row == (8272.8, 8294.7, 8284.0, 56560411.0)


def test_describe_reports_columns(con, toi_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["toi"]
    stage_dataset(con, spec, toi_csv, settings=settings)
    info = describe(con, "toi")
    assert info["rows"] == 6
    names = [c for c, _ in info["columns"]]
    assert "raw_text" in names and "stg_row_id" in names


def test_audit_rows_reconcile_with_staging(con, toi_csv: Path, settings: Settings) -> None:
    spec = load_datasets_config()["toi"]
    from datetime import datetime

    audit.ensure_audit_table(con)
    started = datetime.now(UTC).replace(tzinfo=None)
    with step("stage toi") as info:
        info.update(stage_dataset(con, spec, toi_csv, settings=settings))
    audit.record(
        con, run_id="test", dataset_code="toi", step="ingest.stage",
        info=info, status=info["status"], started_at=started,
    )

    rows = audit.funnel(con, "test")
    assert len(rows) == 1
    assert rows[0]["rows_loaded"] == 6
    assert rows[0]["rows_read"] == 6
    assert rows[0]["status"] == "ok"

    staged = int(con.execute(f"SELECT count(*) FROM {stage_table_name('toi')}").fetchone()[0])
    assert staged == rows[0]["rows_loaded"]
