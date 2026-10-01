"""Phase 3 gate: fact row counts equal clean row counts, and keys are unique.

The headline check is the one that matters. `fact_headline` is built with an
inner join to `feat_headline`, so any clean row the feature stage failed to
score would vanish silently. Comparing the counts is what catches that; a
`count(*)` on the fact table alone would look perfectly healthy.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from dwm.config import Settings, load_datasets_config
from dwm.etl import run_etl
from dwm.features.runner import load_features_config, run_features
from dwm.ingest.staging import stage_dataset
from dwm.warehouse import CUBE_TABLES, FACT_TABLES, run_build
from dwm.warehouse import check_gates as build_gates

TOI_ROWS = [
    "publish_date,headline_category,headline_text",
    "20160101,sports.cricket,India win the final over comfortably",
    "20160102,politics.parliament,Parliament passes the new bill after debate",
    "20160103,business.markets,Sensex gains as profits beat expectations",
    "20160104,city.mumbai,Mumbai rains bring relief after a long dry spell",
    "20160105,technology.gadgets,New phone launch promises faster charging",
    "20160106,sports.cricket,SHOCKING! India CRUSHED in final OVER!!!",
    "20160107,business.markets,Sensex gains as profits beat expectations again",
    "20160108,entertainment.bollywood,Actor says film is his best work yet",
    "20160109,world.diplomacy,Leaders meet in Delhi for trade talks",
    "20160110,health.health-news,Hospital reports a rise in dengue cases",
    "20200630,covid-19.health,India reports highest daily case count",
]

IFND_ROWS = [
    "id,Statement,Image,Web,Category,Date,Label",
    '1,"A calm statement about policy",a.jpg,SITE,POLITICS,Oct-20,TRUE',
    '2,"SHOCKING government admits massive failure!!",b.jpg,SITE,GOVERNMENT,Oct-20,Fake',
    '3,"Third statement with a neutral tone",c.jpg,SITE,VIOLENCE,Nov 2020,FALSE',
    '4,"Fourth statement about courts",d.jpg,SITE,POLITICS,20-Sep,TRUE',
    '5,"Fifth statement with no date",e.jpg,SITE,ELECTION,,FALSE',
]

NIFTY_ROWS = [
    "Date,Open,High,Low,Close,Volume,Turnover",
    "04-01-2016,100,110,95,105,1000,10.5",
    "05-01-2016,105,115,100,112,1100,11.5",
    "06-01-2016,112,120,108,118,1200,12.5",
    "07-01-2016,118,125,115,124,1300,13.5",
    "08-01-2016,124,122,110,113,1400,14.5",
]


def _write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def built(tmp_path: Path, settings: Settings, monkeypatch):
    """Staging -> clean -> features -> facts, all on fixtures."""
    import dwm.features.runner as runner

    cfg = copy.deepcopy(load_features_config())
    cfg["runtime"]["use_multiprocessing"] = False
    cfg["keywords"]["min_doc_frequency"] = 1
    cfg["runtime"]["chunk_size"] = 5
    monkeypatch.setattr(runner, "load_features_config", lambda *a, **k: cfg)

    specs = load_datasets_config()
    from dwm.db import connect

    con = connect(settings)
    paths = {
        "toi": _write(tmp_path, "india-news-headlines.csv", TOI_ROWS),
        "ifnd": _write(tmp_path, "IFND.csv", IFND_ROWS),
        "nifty": _write(tmp_path, "nifty50.csv", NIFTY_ROWS),
    }
    for code, path in paths.items():
        stage_dataset(con, specs[code], path, settings=settings)
    run_etl(settings, con=con)
    run_features(settings, con=con)
    run_build(settings, con=con)
    yield con, settings
    con.close()


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def test_phase3_gate_passes(built) -> None:
    con, _ = built
    gates = build_gates(con, strict=True)  # raises if it fails
    assert gates["passed"] is True
    assert gates["count_mismatches"] == {}
    assert gates["key_violations"] == {}


def test_fact_counts_equal_clean_counts(built) -> None:
    con, _ = built
    for fact, clean, _key in (
        ("fact_headline", "cln_headline", "headline_id"),
        ("fact_statement", "cln_statement", "statement_id"),
        ("fact_market_daily", "cln_market_daily", "market_id"),
    ):
        assert _scalar(con, f"SELECT count(*) FROM {fact}") == _scalar(
            con, f"SELECT count(*) FROM {clean}"
        ), f"{fact} lost rows against {clean}"


def test_fact_keys_are_unique(built) -> None:
    con, _ = built
    for table, key in (
        ("fact_headline", "headline_id"),
        ("fact_statement", "statement_id"),
        ("fact_market_daily", "market_id"),
    ):
        dupes = _scalar(
            con, f"SELECT count(*) FROM (SELECT {key} FROM {table} GROUP BY 1 HAVING count(*)>1) t"
        )
        assert dupes == 0


def test_bridge_has_no_duplicates_or_orphans(built) -> None:
    con, _ = built
    assert _scalar(
        con, "SELECT count(*) FROM (SELECT headline_id, keyword_key FROM "
            "bridge_headline_keyword GROUP BY 1,2 HAVING count(*)>1) t"
    ) == 0
    assert _scalar(
        con, "SELECT count(*) FROM bridge_headline_keyword b WHERE NOT EXISTS "
            "(SELECT 1 FROM fact_headline h WHERE h.headline_id=b.headline_id)"
    ) == 0
    assert _scalar(
        con, "SELECT count(*) FROM bridge_headline_keyword b WHERE NOT EXISTS "
            "(SELECT 1 FROM dim_keyword k WHERE k.keyword_key=b.keyword_key)"
    ) == 0


# ---------------------------------------------------------------------------
# cubes: sums, never averages
# ---------------------------------------------------------------------------


def test_cube_totals_reconcile_with_the_fact(built) -> None:
    con, _ = built
    in_window = _scalar(con, "SELECT count(*) FROM fact_headline WHERE in_window")
    assert in_window > 0
    for cube in ("cube_month_topic", "cube_topic_sentiment", "cube_day_topic"):
        total = _scalar(con, f"SELECT coalesce(sum(headline_count),0) FROM {cube}")
        assert total == in_window, f"{cube} does not reconcile"


def test_year_cube_reconciles_across_years(built) -> None:
    con, _ = built
    in_window = _scalar(con, "SELECT count(*) FROM fact_headline WHERE in_window")
    total = _scalar(con, "SELECT coalesce(sum(headline_count),0) FROM cube_year_topic")
    assert total == in_window


def test_cubes_store_sums_not_averages(built) -> None:
    """The viva point: sums roll up, averages do not.

    No cube may contain a column that looks like a mean of a measure. The
    mean must be recoverable as sum/count.
    """
    con, _ = built
    for cube in CUBE_TABLES:
        cols = [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [cube],
            ).fetchall()
        ]
        for col in cols:
            lowered = col.lower()
            assert not lowered.endswith("_avg"), f"{cube}.{col} stores an average"
            assert not lowered.startswith("avg_"), f"{cube}.{col} stores an average"
            assert "mean" not in lowered, f"{cube}.{col} looks like a mean"
        # and the means can be computed
        assert "headline_count" in cols


def test_cube_month_topic_recomputes_the_means(built) -> None:
    con, _ = built
    row = con.execute(
        """
        SELECT headline_count,
               sum_sentiment_compound,
               sum_sensational_score,
               sensational_count,
               negative_count
        FROM cube_month_topic
        WHERE headline_count > 0
        ORDER BY headline_count DESC LIMIT 1
        """
    ).fetchone()
    count, sum_compound, sum_score, sens, negative = row
    # These are the averages a query would compute, and they must be ratios
    # of stored sums, not stored values.
    mean_compound = sum_compound / count
    mean_score = sum_score / count
    sens_rate = sens / count
    neg_rate = negative / count
    assert 0 <= sens_rate <= 1
    assert 0 <= neg_rate <= 1
    assert -1 <= mean_compound <= 1
    assert 0 <= mean_score <= 1


def test_month_rollup_equals_the_sum_of_its_months(built) -> None:
    """A roll-up must be exactly the sum of the parts."""
    con, _ = built
    by_month = con.execute(
        "SELECT year_month_key, sum(headline_count) FROM cube_month_topic GROUP BY 1 ORDER BY 1"
    ).fetchall()
    by_year = dict(
        con.execute(
            "SELECT year_no, sum(headline_count) FROM cube_year_topic GROUP BY year_no"
        ).fetchall()
    )
    rolled: dict[int, int] = {}
    for ym, n in by_month:
        year = int(str(ym)[:4])
        rolled[year] = rolled.get(year, 0) + n
    for year, n in rolled.items():
        assert by_year[year] == n


# ---------------------------------------------------------------------------
# fact content
# ---------------------------------------------------------------------------


def test_fact_headline_carries_measures_and_keys(built) -> None:
    con, _ = built
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='fact_headline'"
    ).fetchall()}
    for required in (
        "headline_id", "date_key", "topic_key", "dataset_key",
        "sentiment_compound", "sensational_score", "is_risk_signal",
        "is_multi_category", "in_window",
    ):
        assert required in cols, f"fact_headline is missing {required}"


def test_fact_statement_keeps_a_nullable_date(built) -> None:
    con, _ = built
    # Two fixture statements have no resolvable calendar date.
    assert _scalar(con, "SELECT count(*) FROM fact_statement WHERE date_key IS NULL") == 2
    assert _scalar(
        con, "SELECT count(*) FROM fact_statement WHERE date_precision='month_day' "
            "AND date_key IS NOT NULL"
    ) == 0
    labels = dict(
        con.execute("SELECT label_code, count(*) FROM fact_statement GROUP BY 1").fetchall()
    )
    assert set(labels) <= {"REAL", "FAKE", "UNLABELLED"}


def test_fact_market_has_returns_and_volatility(built) -> None:
    con, _ = built
    cols = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='fact_market_daily'"
    ).fetchall()}
    for required in ("return_pct", "day_range", "volatility_20d", "return_sign"):
        assert required in cols
    # The first day has no previous close, so no return.
    assert _scalar(con, "SELECT count(*) FROM fact_market_daily WHERE return_pct IS NULL") == 1
    # Volatility needs a FULL 20-session window; a 5-row fixture yields none,
    # because a "20-day" figure from three observations would be a lie.
    assert _scalar(
        con, "SELECT count(*) FROM fact_market_daily WHERE volatility_20d IS NOT NULL"
    ) == 0


def test_market_return_arithmetic(built) -> None:
    con, _ = built
    # 105 -> 112 is a 6.666...% gain
    row = con.execute(
        "SELECT return_pct FROM fact_market_daily ORDER BY trade_date OFFSET 1 LIMIT 1"
    ).fetchone()
    assert row[0] == pytest.approx((112 - 105) / 105 * 100, abs=1e-4)


def test_dataset_keys_point_at_dim_dataset(built) -> None:
    """Regression: the fact keys must be looked up, not hard-coded.

    dim_dataset assigns keys by sorting the configured codes, so toi is key 3.
    A literal mapping in the fact DDL wrote 1, and every headline would have
    pointed at the wrong source.
    """
    con, _ = built
    codes = dict(con.execute("SELECT dataset_code, dataset_key FROM dim_dataset").fetchall())
    assert _scalar(
        con, f"SELECT count(*) FROM fact_headline WHERE dataset_key <> {codes['toi']}"
    ) == 0
    assert _scalar(
        con, f"SELECT count(*) FROM fact_statement WHERE dataset_key <> {codes['ifnd']}"
    ) == 0
    assert _scalar(
        con, f"SELECT count(*) FROM fact_market_daily WHERE dataset_key <> {codes['nifty']}"
    ) == 0


def test_label_keys_point_at_dim_label(built) -> None:
    """Regression: label_key was a broken constant, always the same value."""
    con, _ = built
    keys = dict(con.execute("SELECT label_code, label_key FROM dim_label").fetchall())
    assert _scalar(
        con, "SELECT count(*) FROM fact_statement WHERE label_code='REAL' "
            f"AND label_key <> {keys['REAL']}"
    ) == 0
    assert _scalar(
        con, "SELECT count(*) FROM fact_statement WHERE label_code='FAKE' "
            f"AND label_key <> {keys['FAKE']}"
    ) == 0
    # The fixture has both labels, so a constant key would have failed this.
    distinct = _scalar(con, "SELECT count(DISTINCT label_key) FROM fact_statement")
    assert distinct == 2


def test_instrument_key_comes_from_the_dimension(built) -> None:
    con, _ = built
    key = _scalar(con, "SELECT min(instrument_key) FROM dim_instrument")
    assert _scalar(
        con, f"SELECT count(*) FROM fact_market_daily WHERE instrument_key <> {key}"
    ) == 0


def test_all_tables_exist(built) -> None:
    con, _ = built
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    for name in (*FACT_TABLES, *CUBE_TABLES, "dim_keyword", "bridge_headline_keyword"):
        assert name in present


def test_build_refuses_without_features(built) -> None:
    """A missing feature table must be a clear error, not an empty fact."""
    import dwm.warehouse as w

    con, _ = built
    con.execute("DROP TABLE feat_headline")
    with pytest.raises(RuntimeError, match="features"):
        w.build_facts(con, run_id="test")
