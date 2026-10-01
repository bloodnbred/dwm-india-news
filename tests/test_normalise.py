"""CSV normalisation fallback.

DuckDB 1.5.6 mis-parses the real IFND file, so the loader has to be able to
recover. These tests use a fixture that reproduces the same failure: a row
whose unquoted field contains a stray quote character.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from dwm.config import Settings, load_datasets_config
from dwm.ingest.normalise import normalise, normalised_path
from dwm.ingest.staging import stage_dataset, stage_table_name

# A field that is not quoted yet contains a double quote, which is what makes
# DuckDB's sniffer bail out on the real IFND file.
AWKWARD_ROWS = [
    "id,Statement,Image,Web,Category,Date,Label",
    '1,"ordinary statement",a.jpg,SITE,ELECTION,Oct-20,TRUE',
    '2,plain text with an unbalanced " quote,b.jpg,SITE,VIOLENCE,Oct-20,Fake',
    '3,"another ordinary statement",c.jpg,SITE,POLITICS,Nov 2020,TRUE',
]


@pytest.fixture
def awkward_csv(tmp_path: Path) -> Path:
    path = tmp_path / "awkward.csv"
    path.write_text("\n".join(AWKWARD_ROWS) + "\n", encoding="utf-8")
    return path


def test_normalise_roundtrips_every_row(awkward_csv: Path) -> None:
    result = normalise(awkward_csv)
    assert result.rows == 3
    target = result.target
    assert target == normalised_path(awkward_csv)
    assert target.exists()

    with target.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["id", "Statement", "Image", "Web", "Category", "Date", "Label"]
    assert len(rows) == 4
    # The awkward row survives intact rather than being mangled.
    assert rows[2][1] == 'plain text with an unbalanced " quote'


def test_normalise_is_idempotent(awkward_csv: Path) -> None:
    first = normalise(awkward_csv)
    before = first.target.read_bytes()
    second = normalise(awkward_csv)
    assert second.rows == first.rows
    assert second.target.read_bytes() == before


def test_normalise_output_has_no_blank_trailing_row(awkward_csv: Path) -> None:
    result = normalise(awkward_csv)
    text = result.target.read_text(encoding="utf-8")
    # Exactly one terminating newline, and no doubled blank line at the end.
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_loader_recovers_from_an_unreadable_csv(
    con, awkward_csv: Path, settings: Settings
) -> None:
    """Either DuckDB reads it, or the fallback normalises and it loads fully.

    The gate is the row count, not which path was taken.
    """
    ifnd = load_datasets_config()["ifnd"]
    info = stage_dataset(con, ifnd, awkward_csv, settings=settings)

    assert info["rows_loaded"] == 3
    assert info["rows_rejected"] == 0
    # Whatever happened, the audit says whether the file was rewritten.
    assert isinstance(info["normalised"], bool)

    table = stage_table_name("ifnd")
    texts = [
        r[0]
        for r in con.execute(f"SELECT raw_text FROM {table} ORDER BY stg_row_id").fetchall()
    ]
    assert len(texts) == 3
    assert any("unbalanced" in (t or "") for t in texts)


def test_normalised_file_is_actually_reused(con, awkward_csv: Path, settings: Settings) -> None:
    ifnd = load_datasets_config()["ifnd"]
    stage_dataset(con, ifnd, awkward_csv, settings=settings)
    target = normalised_path(awkward_csv)
    if target.exists():
        # Second run must not rewrite it.
        stamp = target.stat().st_mtime_ns
        con.execute(f"DROP TABLE {stage_table_name('ifnd')}")
        info = stage_dataset(con, ifnd, awkward_csv, settings=settings)
        assert info["rows_loaded"] == 3
        assert target.stat().st_mtime_ns == stamp
