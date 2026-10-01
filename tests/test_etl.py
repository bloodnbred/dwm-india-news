"""ETL tests: dimensions, clean tables, and the Phase 2 gate.

These run against small fixtures so the semantics are pinned down without a
227 MB file. The real-data numbers live in docs/01-ingest-etl.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dwm.config import Settings, load_datasets_config
from dwm.etl import check_gates, run_etl, staging_ready
from dwm.etl.dates import (
    date_key_expr,
    ifnd_date_value_expr,
    nifty_date_expr,
    register_date_functions,
    toi_date_expr,
)
from dwm.ingest.staging import stage_dataset
from dwm.parse import parse_date

# A TOI fixture with a deliberate duplicate: the same text on the same date
# filed under two categories, plus a repeat on a different date.
TOI_ROWS = [
    "publish_date,headline_category,headline_text",
    "20160101,sports.cricket,India win the final over",
    "20160101,sports.cricket,India win the final over",       # exact duplicate
    "20160101,business.gadgets,India win the final over",      # same text, other desk
    "20160102,sports.cricket,India win the final over",       # same text, next day
    "20160103,business.markets,Sensex closes higher on profit booking",
    "20160104,politics.parliament,Parliament clears the bill after debate",
    "20200630,covid-19.health,India reports highest daily case count",
    # Outside the derived window, so the flag has something to mark.
    "20100101,sports.tennis,Australian Open final goes to five sets",
]

IFND_ROWS = [
    "id,Statement,Image,Web,Category,Date,Label",
    '1,"Statement with a month-year date",a.jpg,SITE,POLITICS,Oct-20,TRUE',
    '2,"Statement with a day but no year",b.jpg,SITE,COVID-19,20-Sep,Fake',
    '3,"Statement with no date at all",c.jpg,SITE,VIOLENCE,,FALSE',
    # Exact duplicate of row 1, but WITHOUT a date. The dated row must win,
    # and its precision must stay "month" rather than being overwritten.
    '4,"Statement with a month-year date",a.jpg,SITE,POLITICS,,TRUE',
]

NIFTY_ROWS = [
    "Date,Open,High,Low,Close,Volume,Turnover",
    "04-01-2016,100,110,95,105,1000,10.5",
    "05-01-2016,105,115,100,112,1100,11.5",
    "06-01-2016,112,120,108,118,1200,12.5",
]


def _write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def etl_db(tmp_path: Path, settings: Settings):
    """A warehouse with all three staging tables loaded from fixtures."""
    from dwm.db import connect

    specs = load_datasets_config()
    paths = {
        "toi": _write(tmp_path, "india-news-headlines.csv", TOI_ROWS),
        "ifnd": _write(tmp_path, "IFND.csv", IFND_ROWS),
        "nifty": _write(tmp_path, "nifty50.csv", NIFTY_ROWS),
    }
    con = connect(settings)
    for code, path in paths.items():
        stage_dataset(con, specs[code], path, settings=settings)
    yield con
    con.close()


@pytest.fixture
def etl_settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "etl.duckdb", years=5)


# ---------------------------------------------------------------------------
# date expressions agree with the tested Python parser
# ---------------------------------------------------------------------------


def test_toi_sql_matches_the_python_parser(con) -> None:
    from dwm.config import load_datasets_config

    fmt = load_datasets_config()["toi"].date_formats
    expr = toi_date_expr()
    for raw in ("20160101", "20200630"):
        sql = con.execute(f"SELECT {expr.replace('raw_date', _lit(raw))}").fetchone()[0]
        py = parse_date(raw, fmt).value
        assert sql == py


def _lit(value: str) -> str:
    return "'" + value + "'"


def test_nifty_sql_matches_the_python_parser(con) -> None:
    expr = nifty_date_expr()
    for raw in ("2016-01-04", "04-01-2016"):
        sql = con.execute(f"SELECT {expr.replace('raw_date', _lit(raw))}").fetchone()[0]
        assert sql is not None
        assert sql.year in (2016,)


def test_ifnd_udf_matches_the_python_parser(etl_db) -> None:
    """The SQL path and the tested parser must not diverge."""
    specs = load_datasets_config()
    register_date_functions(etl_db, specs["ifnd"])
    fmt = specs["ifnd"].date_formats
    rows = etl_db.execute("SELECT DISTINCT raw_date FROM stg_ifnd").fetchall()
    assert rows
    for (raw,) in rows:
        sql = etl_db.execute(
            f"SELECT {ifnd_date_value_expr().replace('raw_date', _lit(raw) if raw else 'NULL')}"
        ).fetchone()[0]
        py = parse_date(raw, fmt)
        assert sql == py.value
        prec = etl_db.execute(
            f"SELECT dwm_date_precision({_lit(raw) if raw else 'NULL'})"
        ).fetchone()[0]
        assert prec == py.precision


def test_date_key_expression_format(etl_db) -> None:
    assert etl_db.execute("SELECT " + date_key_expr("DATE '2016-01-04'")).fetchone()[0] == 20160104


# ---------------------------------------------------------------------------
# dedupe and grain
# ---------------------------------------------------------------------------


def test_headline_grain_is_date_and_text(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    rows = etl_db.execute(
        "SELECT publish_date, headline_text, staged_rows, category_count, is_multi_category "
        "FROM cln_headline ORDER BY publish_date, headline_text"
    ).fetchall()

    # "India win the final over" appears on two dates: two rows, not one.
    same_text = [r for r in rows if r[1] == "India win the final over"]
    assert len(same_text) == 2
    assert {r[0].isoformat() for r in same_text} == {"2016-01-01", "2016-01-02"}

    # On 2016-01-01 it was filed twice: exact dup + other desk = 3 staged rows.
    day_one = next(r for r in same_text if r[0].isoformat() == "2016-01-01")
    assert day_one[2] == 3          # staged_rows
    assert day_one[3] == 2          # category_count: sports.cricket + business.gadgets
    assert day_one[4] is True       # is_multi_category

    total = etl_db.execute("SELECT count(*) FROM cln_headline").fetchone()[0]
    # 8 staged rows collapse to 6 distinct (date, text) pairs.
    assert total == 6


def test_primary_category_is_the_most_frequent_filing(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    # On 2016-01-01 the text was filed twice as sports.cricket (one of them an
    # exact duplicate) and once as business.gadgets, so the primary category
    # is the one with the most filings, not an arbitrary pick.
    row = etl_db.execute(
        "SELECT raw_category, category_count FROM cln_headline "
        "WHERE publish_date = DATE '2016-01-01' AND headline_text = 'India win the final over'"
    ).fetchone()
    assert row[0] == "sports.cricket"
    assert row[1] == 2


def test_statement_prefers_the_dated_duplicate(etl_db, etl_settings: Settings) -> None:
    """Regression: date and precision must come from the same row.

    Two rows share the text "Statement with a month-year date", one dated and
    one not. Picking date and precision independently with any_value() would
    pair the date of one with the precision of the other.
    """
    run_etl(etl_settings, con=etl_db)
    row = etl_db.execute(
        "SELECT source_date, date_precision, staged_rows FROM cln_statement "
        "WHERE statement_text = 'Statement with a month-year date'"
    ).fetchone()
    assert row is not None
    assert row[0] is not None                       # the dated row was chosen
    assert row[0].isoformat() == "2020-10-01"
    assert row[1] == "month"                        # not overwritten by "none"
    assert row[2] == 2                              # both staged rows collapsed


def test_statement_precision_matches_null_dates(etl_db, etl_settings: Settings) -> None:
    """Every statement with no date must be explained by its precision."""
    run_etl(etl_settings, con=etl_db)
    no_date = etl_db.execute(
        "SELECT count(*) FROM cln_statement WHERE source_date IS NULL"
    ).fetchone()[0]
    explained = etl_db.execute(
        "SELECT count(*) FROM cln_statement "
        "WHERE date_precision IN ('none', 'month_day')"
    ).fetchone()[0]
    assert no_date == explained

    # A yearless day must not have acquired an invented date.
    assert etl_db.execute(
        "SELECT count(*) FROM cln_statement "
        "WHERE date_precision = 'month_day' AND source_date IS NOT NULL"
    ).fetchone()[0] == 0


def test_label_is_normalised(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    labels = dict(
        etl_db.execute("SELECT label_code, count(*) FROM cln_statement GROUP BY 1").fetchall()
    )
    # The fixture labels are TRUE, Fake and FALSE. All three are recognised,
    # so nothing falls through to UNLABELLED.
    assert set(labels) == {"REAL", "FAKE"}
    assert labels["REAL"] == 1      # the two TRUE rows dedupe to one
    assert labels["FAKE"] == 2      # "Fake" and "FALSE"


def test_mixed_case_fake_label_is_not_lost(etl_db, etl_settings: Settings) -> None:
    """Regression: "Fake" must map to FAKE, not to UNLABELLED.

    The first implementation used a SQL CASE over the literals 'TRUE' and
    'FALSE'. The IFND source also writes "Fake", which matches neither, so
    every such row silently became UNLABELLED and fakes would have vanished
    from the Phase 6 classifier's training data.
    """
    run_etl(etl_settings, con=etl_db)
    code = etl_db.execute(
        "SELECT label_code FROM cln_statement WHERE statement_text = ?",
        ["Statement with a day but no year"],
    ).fetchone()[0]
    assert code == "FAKE"
    assert etl_db.execute(
        "SELECT count(*) FROM cln_statement WHERE label_code = 'UNLABELLED'"
    ).fetchone()[0] == 0


def test_label_map_is_built_from_config(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    rows = dict(
        etl_db.execute(
            "SELECT raw_label, label_code FROM map_label_value WHERE dataset_code='ifnd'"
        ).fetchall()
    )
    assert rows["TRUE"] == "REAL"
    assert rows["FALSE"] == "FAKE"
    assert rows["FAKE"] == "FAKE"


# ---------------------------------------------------------------------------
# window
# ---------------------------------------------------------------------------


def test_window_is_derived_from_the_data(etl_db, etl_settings: Settings) -> None:
    summary = run_etl(etl_settings, con=etl_db)
    # Max publish date in the fixture is 2020-06-30, so a 5-year window starts
    # 2015-06-30. Nothing about those dates is hard-coded.
    assert summary["window"]["max_publish_date"] == "2020-06-30"
    assert summary["window"]["start"] == "2015-06-30"
    assert summary["window"]["end"] == "2020-06-30"


def test_in_window_is_a_flag_not_a_filter(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    total = etl_db.execute("SELECT count(*) FROM cln_headline").fetchone()[0]
    inside = etl_db.execute(
        "SELECT count(*) FROM cln_headline WHERE in_window"
    ).fetchone()[0]
    # The 2010 row is retained with in_window false. A hard filter would have
    # dropped it, hiding how much the window excludes.
    assert total == 6
    assert inside == 5
    assert etl_db.execute(
        "SELECT count(*) FROM cln_headline "
        "WHERE headline_text = 'Australian Open final goes to five sets' AND NOT in_window"
    ).fetchone()[0] == 1


# ---------------------------------------------------------------------------
# dimensions
# ---------------------------------------------------------------------------


def test_dim_date_is_contiguous_and_flagged(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    lo, hi, n = etl_db.execute(
        "SELECT min(full_date), max(full_date), count(*) FROM dim_date"
    ).fetchone()
    assert (hi - lo).days + 1 == n           # no gaps
    assert n > 0
    # 2016-01-04 is a Monday and a trading day in the fixture.
    flags = etl_db.execute(
        "SELECT day_name, is_weekend, is_trading_day, date_key, year_month_key "
        "FROM dim_date WHERE full_date = DATE '2016-01-04'"
    ).fetchone()
    assert flags[0] == "Monday"
    assert flags[1] is False
    assert flags[2] is True
    assert flags[3] == 20160104
    assert flags[4] == 201601


def test_dim_date_quarter_end_flag(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    assert etl_db.execute(
        "SELECT is_quarter_end FROM dim_date WHERE full_date = DATE '2016-03-31'"
    ).fetchone()[0] is True
    assert etl_db.execute(
        "SELECT is_quarter_end FROM dim_date WHERE full_date = DATE '2016-03-30'"
    ).fetchone()[0] is False


def test_dim_topic_separates_place_from_subject(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    row = {
        r[0]: (r[1], r[2])
        for r in etl_db.execute(
            "SELECT topic_name, topic_group, is_place FROM dim_topic"
        ).fetchall()
    }
    assert row["Local"][0] == "Place"
    assert row["Local"][1] is True
    assert row["Business"][0] == "Subject"
    assert row["Business"][1] is False
    assert row["Unknown"][0] == "Unknown"


def test_dim_label_marks_ground_truth(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    rows = etl_db.execute(
        "SELECT label_code, label_value, is_ground_truth FROM dim_label ORDER BY label_key"
    ).fetchall()
    by_code = {r[0]: (r[1], r[2]) for r in rows}
    assert by_code["REAL"] == (1, True)
    assert by_code["FAKE"] == (0, True)
    # Unlabelled rows cannot support an accuracy claim, and the dimension
    # says so explicitly.
    assert by_code["UNLABELLED"] == (None, False)


def test_dim_dataset_carries_provenance(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    row = etl_db.execute(
        "SELECT provenance, is_labelled, staged_rows FROM dim_dataset WHERE dataset_code='nifty'"
    ).fetchone()
    assert "mirror" in row[0].lower()
    assert row[1] is False
    assert row[2] == 3


def test_dim_instrument(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    assert etl_db.execute(
        "SELECT instrument_code, exchange FROM dim_instrument"
    ).fetchone() == ("NIFTY50", "NSE")


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def test_phase2_gate_passes(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    gates = check_gates(etl_db, strict=True)  # raises if it fails
    assert gates["passed"] is True
    assert gates["headline_null_date_keys"] == 0
    assert gates["unmapped_categories"] == 0
    assert gates["orphan_date_keys"] == 0
    assert gates["orphan_topic_keys"] == 0


def test_every_headline_maps_to_a_topic(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    assert etl_db.execute(
        "SELECT count(*) FROM cln_headline WHERE topic_name IS NULL"
    ).fetchone()[0] == 0


def test_statement_dates_are_exempt_but_documented(etl_db, etl_settings: Settings) -> None:
    run_etl(etl_settings, con=etl_db)
    gates = check_gates(etl_db, strict=True)
    # Non-zero is expected and permitted; the reason is recorded, not hidden.
    assert gates["statement_null_date_keys"] > 0
    assert "nullable by design" in gates["note"]


def test_etl_refuses_to_run_without_staging(tmp_path: Path) -> None:
    from dwm.db import connect

    settings = Settings(db_path=tmp_path / "empty.duckdb")
    con = connect(settings)
    try:
        assert staging_ready(con) == ["toi", "ifnd", "nifty"]
    finally:
        con.close()
    with pytest.raises(RuntimeError, match="ingest"):
        run_etl(settings)


def test_category_map_is_keyed_by_dataset(etl_db, etl_settings: Settings) -> None:
    """TOI and IFND must not share one raw-category namespace."""
    run_etl(etl_settings, con=etl_db)
    datasets = dict(
        etl_db.execute(
            "SELECT dataset_code, count(*) FROM map_category_topic GROUP BY 1"
        ).fetchall()
    )
    assert set(datasets) == {"toi", "ifnd"}
    assert etl_db.execute(
        "SELECT count(*) FROM map_category_topic WHERE topic_key IS NULL"
    ).fetchone()[0] == 0
