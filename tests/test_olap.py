"""Phase 4: the OLAP operations.

Two things are checked throughout.

**Sums, never averages.** A roll-up must equal the sum of its parts, and a
reported mean must be that sum divided by its count, not an average of the
means of the parts. Averaging averages weights a thin month the same as a
busy one, which is the classic OLAP mistake the blueprint calls out.

**Drill-across must respect the trading calendar.** Headlines are published on
1,828 distinct days in the window while the market trades on 1,235. Attaching
a close price to a Sunday headline would be a category error, so the join
goes through the market table's own dates and the result is bounded by the
analysis window rather than by the full dimension.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from dwm.config import Settings, load_datasets_config
from dwm.etl import run_etl
from dwm.features.runner import load_features_config, run_features
from dwm.ingest.staging import stage_dataset
from dwm.olap import (
    DEFAULT_PARAMS,
    OPERATIONS,
    cube_by_year_topic_band,
    dice_by_topic_and_year,
    drill_across_market_and_headlines,
    drill_down_to_month,
    list_operations,
    pivot_month_by_topic,
    roll_up_to_year,
    slice_by_topic,
    slice_by_year,
    top_n_months,
    topic_mix_over_time,
)
from dwm.warehouse import run_build

TOI_ROWS = [
    "publish_date,headline_category,headline_text",
    "20160101,sports.cricket,India win the final over comfortably",
    "20160102,politics.parliament,Parliament passes the new bill after debate",
    "20160103,business.markets,Sensex gains as profits beat expectations",
    # A second Business month in the same year, with a different headline
    # count. Without this the roll-up test cannot tell sum/count apart from a
    # mean of monthly means, because a one-month group makes them identical.
    "20160203,business.markets,RBI holds rates steady amid inflation worries",
    "20160105,technology.gadgets,New phone launch promises faster charging",
    "20160106,sports.cricket,SHOCKING! India CRUSHED in final OVER!!!",
    "20160107,business.markets,Sensex falls as profits disappoint badly",
    "20160108,entertainment.bollywood,Actor says film is his best work yet",
    "20160109,business.markets,Crisis deepens as Sensex tumbles on fears",
    "20160110,city.mumbai,Mumbai rains bring relief after a long dry spell",
    "20170103,business.markets,Sensex gains on budget hopes",
    "20170104,sports.cricket,India wins another final comfortably",
    "20170105,politics.parliament,Budget speech passes in parliament",
    "20170106,city.delhi,Delhi air quality improves after rain",
    "20180103,business.markets,Sensex ends year on a high note",
    "20180104,technology.gadgets,Phone camera claims to be the best ever",
    "20180105,city.bengaluru,Bengaluru traffic plan announced for metro",
]

IFND_ROWS = [
    "id,Statement,Image,Web,Category,Date,Label",
    '1,"A calm statement about policy",a.jpg,SITE,POLITICS,Oct-20,TRUE',
    '2,"SHOCKING government admits massive failure!!",b.jpg,SITE,GOVERNMENT,Oct-20,Fake',
    '3,"Third statement with a neutral tone",c.jpg,SITE,VIOLENCE,Nov 2020,FALSE',
]

NIFTY_ROWS = [
    "Date,Open,High,Low,Close,Volume,Turnover",
    "04-01-2016,100,110,95,105,1000,10.5",
    "05-01-2016,105,115,100,112,1100,11.5",
    "06-01-2016,112,120,108,118,1200,12.5",
    "07-01-2016,118,125,115,124,1300,13.5",
    "03-01-2017,124,130,120,128,1500,15.5",
    "04-01-2017,128,135,125,132,1600,16.5",
    "03-01-2018,132,140,130,138,1700,17.5",
    "04-01-2018,138,145,135,142,1800,18.5",
    "05-01-2018,142,148,138,145,1900,19.5",
]


def _write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def olap_db(tmp_path: Path, settings: Settings, monkeypatch):
    """A complete warehouse, ready for OLAP."""
    import dwm.features.runner as runner

    cfg = copy.deepcopy(load_features_config())
    cfg["runtime"]["use_multiprocessing"] = False
    cfg["keywords"]["min_doc_frequency"] = 1
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
    yield con
    con.close()


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------


def test_all_eight_operations_are_registered() -> None:
    names = {o["name"] for o in list_operations()}
    assert {
        "slice", "dice", "roll_up", "drill_down", "pivot", "cube", "drill_across",
    } <= names
    assert set(OPERATIONS) == names
    for name in names:
        assert name in DEFAULT_PARAMS


def test_every_operation_runs(olap_db) -> None:
    for name, fn in OPERATIONS.items():
        result = fn(olap_db, **DEFAULT_PARAMS.get(name, {}))
        assert isinstance(result.rows, list)
        assert result.columns, f"{name} returned no columns"
        payload = result.to_dict()
        # The registry name and the result's own label may differ on purpose
        # (top_months reports itself as a "ranking"), so check the shape.
        assert set(payload) == {"operation", "description", "columns", "rows", "meta"}
        assert payload["description"], f"{name} has no description"
        assert payload["operation"]


# ---------------------------------------------------------------------------
# slice and dice
# ---------------------------------------------------------------------------


def test_slice_fixes_one_dimension(olap_db) -> None:
    result = slice_by_topic(olap_db, "Business")
    assert result.operation == "slice"
    assert result.rows
    # One topic fixed, months as the varying dimension.
    assert "year_month" in result.columns
    assert all(r["year_month"] for r in result.rows)
    total = sum(r["headline_count"] for r in result.rows)
    assert total == _scalar(
        olap_db, "SELECT coalesce(sum(headline_count),0) FROM cube_month_topic c "
                 "JOIN dim_topic t USING (topic_key) WHERE t.topic_name='Business'"
    )


def test_slice_by_year(olap_db) -> None:
    result = slice_by_year(olap_db, 2016)
    assert result.rows
    assert all(r["headline_count"] > 0 for r in result.rows)
    topics = {r["topic_name"] for r in result.rows}
    assert "Business" in topics


def test_slice_of_a_missing_topic_is_empty_not_an_error(olap_db) -> None:
    result = slice_by_topic(olap_db, "NoSuchTopic")
    assert result.rows == []


def test_dice_fixes_two_dimensions(olap_db) -> None:
    result = dice_by_topic_and_year(olap_db, ["Business", "Sports"], [2016, 2017])
    assert result.rows
    for r in result.rows:
        assert r["topic_name"] in {"Business", "Sports"}
        assert r["year_no"] in {2016, 2017}


# ---------------------------------------------------------------------------
# roll-up and drill-down
# ---------------------------------------------------------------------------


def test_roll_up_equals_the_sum_of_its_months(olap_db) -> None:
    """The core OLAP rule: a roll-up is a sum, not a mean of means."""
    result = roll_up_to_year(olap_db)
    assert result.rows

    rolled = {(r["year_no"], r["topic_name"]): r["headline_count"] for r in result.rows}
    direct = {
        (y, t): n
        for y, t, n in olap_db.execute(
            """
            SELECT c.year_no, t.topic_name, sum(c.headline_count)
            FROM cube_month_topic c JOIN dim_topic t USING (topic_key)
            GROUP BY 1, 2
            """
        ).fetchall()
    }
    assert rolled == direct


def test_roll_up_mean_is_sum_over_count(olap_db) -> None:
    result = roll_up_to_year(olap_db)
    for r in result.rows:
        if not r["headline_count"]:
            continue
        expected = r["sum_sentiment_compound"] / r["headline_count"]
        assert r["mean_sentiment"] == pytest.approx(expected, abs=1e-4)


def test_roll_up_mean_differs_from_the_mean_of_monthly_means(olap_db) -> None:
    """Guards the exact mistake the blueprint warns about.

    If the months hold different headline counts, averaging the monthly means
    gives a different answer from the true overall mean. The test asserts the
    two are distinguishable, so the implementation cannot quietly switch to
    the wrong one.
    """
    monthly = olap_db.execute(
        """
        SELECT c.year_no, t.topic_name,
               round(sum(c.sum_sentiment_compound) / nullif(sum(c.headline_count), 0), 6) AS true_mean,
               round(avg(c.sum_sentiment_compound / nullif(c.headline_count, 0)), 6)    AS mean_of_means
        FROM cube_month_topic c JOIN dim_topic t USING (topic_key)
        GROUP BY 1, 2
        """
    ).fetchall()
    differing = [m for m in monthly if m[2] != m[3]]
    # On this fixture at least one group must separate, otherwise the test
    # would pass vacuously.
    assert differing, "fixture cannot distinguish the two; it is not testing anything"

    result = {
        (r["year_no"], r["topic_name"]): r for r in roll_up_to_year(olap_db).rows
    }
    for year, topic, true_mean, mean_of_means in differing:
        assert result[(year, topic)]["mean_sentiment"] == pytest.approx(
            true_mean, abs=1e-4
        )
        assert result[(year, topic)]["mean_sentiment"] != pytest.approx(
            mean_of_means, abs=1e-4
        )


def test_drill_down_is_the_reverse_of_roll_up(olap_db) -> None:
    rolled = {
        (r["year_no"], r["topic_name"]): r["headline_count"]
        for r in roll_up_to_year(olap_db).rows
    }
    topics = {r["topic_name"] for r in roll_up_to_year(olap_db).rows}
    years = {r["year_no"] for r in roll_up_to_year(olap_db).rows}
    for topic in topics:
        for year in years:
            drilled = drill_down_to_month(olap_db, topic, year)
            if not drilled.rows:
                continue
            assert sum(r["headline_count"] for r in drilled.rows) == rolled[(year, topic)]


def test_top_months_ranks_by_a_stored_sum(olap_db) -> None:
    result = top_n_months(olap_db, 3)
    assert len(result.rows) == 3
    values = [r["measure_value"] for r in result.rows]
    assert values == sorted(values, reverse=True)


def test_top_months_rejects_an_unknown_measure(olap_db) -> None:
    with pytest.raises(ValueError, match="cannot rank by"):
        top_n_months(olap_db, 3, by="mean_sentiment")


# ---------------------------------------------------------------------------
# pivot and cube
# ---------------------------------------------------------------------------


def test_pivot_puts_topics_in_columns(olap_db) -> None:
    topics = ["Business", "Sports"]
    result = pivot_month_by_topic(olap_db, topics, "headline_count")
    assert result.operation == "pivot"
    for t in topics:
        assert t in result.columns
    assert "year_month" in result.columns
    # Row count must not multiply: one row per month, not per topic-month.
    months = _scalar(olap_db, "SELECT count(DISTINCT year_month) FROM cube_month_topic")
    assert len(result.rows) == months


def test_pivot_rejects_an_unknown_measure(olap_db) -> None:
    with pytest.raises(ValueError, match="unknown measure"):
        pivot_month_by_topic(olap_db, ["Business"], "not_a_measure")


def test_cube_produces_multiple_grouping_levels(olap_db) -> None:
    result = cube_by_year_topic_band(olap_db, "Subject")
    assert result.operation == "cube"
    flags = {
        (r["g_year"], r["g_topic"], r["g_band"]) for r in result.rows
    }
    # More than one grouping set must be present, or it is not a cube.
    assert len(flags) > 1
    assert (1, 1, 1) in flags, "the grand total grouping is missing"
    assert (0, 0, 0) in flags, "the fully-detailed grouping is missing"


def test_cube_grand_total_matches_the_fact(olap_db) -> None:
    result = cube_by_year_topic_band(olap_db, "Subject")
    grand = next(r for r in result.rows if (r["g_year"], r["g_topic"], r["g_band"]) == (1, 1, 1))
    expected = _scalar(
        olap_db, "SELECT count(*) FROM fact_headline f JOIN dim_topic t USING (topic_key) "
                 "WHERE f.in_window AND t.topic_group='Subject'"
    )
    assert grand["headline_count"] == expected


def test_cube_excludes_other_topic_groups(olap_db) -> None:
    result = cube_by_year_topic_band(olap_db, "Subject")
    # Grand total must not silently include Place topics.
    everything = _scalar(olap_db, "SELECT count(*) FROM fact_headline WHERE in_window")
    grand = next(r for r in result.rows if (r["g_year"], r["g_topic"], r["g_band"]) == (1, 1, 1))
    assert grand["headline_count"] < everything


# ---------------------------------------------------------------------------
# drill-across
# ---------------------------------------------------------------------------


def test_drill_across_joins_two_facts_on_date_key(olap_db) -> None:
    result = drill_across_market_and_headlines(olap_db, "Business")
    assert result.operation == "drill_across"
    assert result.meta["conform_on"] == "date_key"
    for col in ("full_date", "headline_count", "close", "return_pct"):
        assert col in result.columns
    assert result.rows


def test_drill_across_stays_inside_the_window(olap_db) -> None:
    """Regression: the dimension spans 2001-2023, the question is about five years."""
    lo, hi = olap_db.execute(
        "SELECT min(date_key), max(date_key) FROM fact_headline WHERE in_window"
    ).fetchone()
    result = drill_across_market_and_headlines(olap_db, "Business")
    assert result.rows
    for r in result.rows:
        key = int(str(r["full_date"]).replace("-", ""))
        assert lo <= key <= hi, f"{r['full_date']} is outside the analysis window"


def test_drill_across_only_returns_days_with_market_data(olap_db) -> None:
    result = drill_across_market_and_headlines(olap_db, "Business")
    trading = _scalar(olap_db, "SELECT count(*) FROM dim_date WHERE is_trading_day")
    assert len(result.rows) <= trading
    for r in result.rows:
        assert r["close"] is not None, "a non-trading day carried a close price"
        assert r["is_trading_day"] is True


def test_drill_across_can_include_non_trading_days_explicitly(olap_db) -> None:
    """The relaxation is opt-in, and the result says so in its metadata."""
    strict = drill_across_market_and_headlines(olap_db, "Business", trading_days_only=True)
    loose = drill_across_market_and_headlines(olap_db, "Business", trading_days_only=False)
    assert strict.meta["trading_days_only"] is True
    assert loose.meta["trading_days_only"] is False
    assert len(loose.rows) >= len(strict.rows)
    # The extra rows must have headlines but no price.
    extra = [r for r in loose.rows if r["close"] is None]
    assert all(r["is_trading_day"] is False for r in extra)


def test_drill_across_associates_sentiment_with_market_rows(olap_db) -> None:
    """A positive headline count with market data is what RQ6 needs."""
    result = drill_across_market_and_headlines(olap_db, "Business")
    with_headlines = [r for r in result.rows if r["headline_count"] > 0]
    assert with_headlines
    assert any(r["return_pct"] is not None for r in with_headlines)


# ---------------------------------------------------------------------------
# research question support
# ---------------------------------------------------------------------------


def test_topic_mix_shares_sum_to_one_per_year(olap_db) -> None:
    result = topic_mix_over_time(olap_db, "Subject")
    assert result.rows
    by_year: dict[int, float] = {}
    for r in result.rows:
        by_year[r["year_no"]] = by_year.get(r["year_no"], 0.0) + r["share_of_year"]
    for year, total in by_year.items():
        assert total == pytest.approx(1.0, abs=0.001), f"{year} shares sum to {total}"


def test_topic_mix_respects_the_group_filter(olap_db) -> None:
    subject = topic_mix_over_time(olap_db, "Subject")
    place = topic_mix_over_time(olap_db, "Place")
    assert all(r["topic_group"] == "Subject" for r in subject.rows)
    assert all(r["topic_group"] == "Place" for r in place.rows)
    # The two must be disjoint, and both populated, otherwise the split is not
    # doing any work. Which one is larger is a property of the corpus, not a
    # rule: on the real data Place is 70% of the window, on a small fixture
    # Subject is larger.
    assert subject.rows and place.rows
    assert not ({r["topic_name"] for r in subject.rows} & {r["topic_name"] for r in place.rows})


def test_no_operation_returns_a_stored_average(olap_db) -> None:
    """A result column must never be a pre-stored mean of a measure.

    Means are allowed only where they are clearly derived at query time from a
    sum and a count in the same row.
    """
    for name, fn in OPERATIONS.items():
        result = fn(olap_db, **DEFAULT_PARAMS.get(name, {}))
        for col in result.columns:
            lowered = col.lower()
            assert not lowered.startswith("avg_"), f"{name}.{col}"
            assert not lowered.endswith("_avg"), f"{name}.{col}"
            if "mean" in lowered or "rate" in lowered or "share" in lowered:
                # A derived figure must sit beside its own denominator.
                assert "headline_count" in result.columns, (
                    f"{name}.{col} is a rate with no count to divide by"
                )
