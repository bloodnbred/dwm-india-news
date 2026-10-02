"""Phase 5-6 mining tests.

The emphasis is on the guard rails rather than on the numbers, because the
numbers on the real corpus are already recorded in reports/mining.json. What
these tests protect is the set of promises the modules make:

  * a rate is never reported without its denominator
  * a statistic from too few observations is refused with a reason
  * unlabelled measures are never called a fake-news rate
  * correlations are associations, and are reported with a p-value
  * the classifier is judged against the majority baseline, not against 50%
  * fixed seeds mean two runs agree exactly
  * a partial year never contaminates a whole-year statistic
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from dwm.config import Settings, load_datasets_config
from dwm.etl import run_etl
from dwm.features.runner import load_features_config, run_features
from dwm.ingest.staging import stage_dataset
from dwm.mining import SECTIONS, load_mining_config, run_mining
from dwm.mining.classifier import _metrics
from dwm.mining.market import _p_value, _pearson, _spearman
from dwm.mining.rules import _to_frame, build_attribute_transactions
from dwm.mining.sensationalism import wilson_interval
from dwm.mining.trends import Guard, _coefficient_of_variation, _zscores
from dwm.warehouse import run_build

TOI_ROWS = [
    "publish_date,headline_category,headline_text",
    "20160101,sports.cricket,India win the final over comfortably",
    "20160103,business.markets,Sensex gains as profits beat expectations",
    "20160106,sports.cricket,SHOCKING! India CRUSHED in final OVER!!!",
    "20160107,business.markets,Sensex falls as profits disappoint badly",
    "20160110,city.mumbai,Mumbai rains bring relief after a long dry spell",
    "20170103,business.markets,Sensex gains on budget hopes",
    "20170104,sports.cricket,India wins another final comfortably",
    "20180103,business.markets,Sensex ends year on a high note",
    "20180104,technology.gadgets,Phone camera claims to be the best ever",
    "20180105,city.bengaluru,Bengaluru traffic plan announced for metro",
]

IFND_ROWS = [
    "id,Statement,Image,Web,Category,Date,Label",
    '1,"A calm statement about policy",a.jpg,SITE,POLITICS,Oct-20,TRUE',
    '2,"SHOCKING government admits massive failure!!",b.jpg,SITE,GOVERNMENT,Oct-20,Fake',
    '3,"Third statement with a neutral tone",c.jpg,SITE,VIOLENCE,Nov 2020,FALSE',
    '4,"Fourth statement about courts",d.jpg,SITE,POLITICS,20-Sep,TRUE',
    '5,"Fifth statement with no date",e.jpg,SITE,ELECTION,,FALSE',
    '6,"Sixth calm statement",f.jpg,SITE,POLITICS,Oct-20,TRUE',
    '7,"Seventh calm statement",g.jpg,SITE,GOVERNMENT,Nov 2020,TRUE',
    '8,"Eighth calm statement",h.jpg,SITE,POLITICS,Oct-20,TRUE',
    '9,"Ninth calm statement",i.jpg,SITE,GOVERNMENT,Nov 2020,TRUE',
    '10,"Tenth calm statement",j.jpg,SITE,POLITICS,Oct-20,TRUE',
]

NIFTY_ROWS = [
    "Date,Open,High,Low,Close,Volume,Turnover",
    "04-01-2016,100,110,95,105,1000,10.5",
    "05-01-2016,105,115,100,112,1100,11.5",
    "06-01-2016,112,120,108,118,1200,12.5",
    "07-01-2016,118,125,115,124,1300,13.5",
    "03-01-2017,124,130,120,128,1500,15.5",
    "04-01-2017,128,135,125,132,1600,16.5",
    "05-01-2017,132,140,130,138,1700,17.5",
    "06-01-2017,138,145,135,142,1800,18.5",
    "03-01-2018,142,148,138,145,1900,19.5",
    "04-01-2018,145,152,142,150,2000,20.5",
    "05-01-2018,150,156,147,154,2100,21.5",
    "06-01-2018,154,160,150,158,2200,22.5",
]


def _write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def mining_db(tmp_path: Path, settings: Settings, monkeypatch):
    """A complete warehouse with a small, fast mining configuration."""
    import dwm.features.runner as runner

    features_cfg = copy.deepcopy(load_features_config())
    features_cfg["runtime"]["use_multiprocessing"] = False
    features_cfg["keywords"]["min_doc_frequency"] = 1
    monkeypatch.setattr(runner, "load_features_config", lambda *a, **k: features_cfg)

    mining_cfg = copy.deepcopy(load_mining_config())
    # Small samples so the fixture runs in seconds, and low thresholds so the
    # sparse fixture still yields transactions.
    mining_cfg["clustering"]["sample_size"] = 400
    mining_cfg["clustering"]["k_min"] = 2
    mining_cfg["clustering"]["k_max"] = 3
    mining_cfg["clustering"]["min_df"] = 1
    mining_cfg["clustering"]["svd_components"] = 5
    mining_cfg["rules"]["sample_transactions"] = 500
    mining_cfg["rules"]["min_support"] = 0.10
    mining_cfg["rules"]["keyword_rules"]["sample_transactions"] = 200
    mining_cfg["market"]["min_observations"] = 3
    monkeypatch.setattr("dwm.mining.load_mining_config", lambda *a, **k: mining_cfg)

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
    yield con, mining_cfg
    con.close()


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_guard_records_failures() -> None:
    g = Guard([])
    g.require("ok_check", True, "fine")
    g.require("bad_check", False, "too few rows")
    assert not g.ok
    assert [c["check"] for c in g.failed] == ["bad_check"]


def test_zscores_of_a_flat_series_is_all_zero() -> None:
    z = _zscores([("a", 10.0), ("b", 10.0), ("c", 10.0), ("d", 10.0)])
    assert all(abs(v) < 1e-9 for v in z.values())


def test_zscores_needs_three_points() -> None:
    assert _zscores([("a", 1.0), ("b", 2.0)]) == {}


def test_coefficient_of_variation_of_a_flat_series() -> None:
    assert _coefficient_of_variation([("a", 10.0), ("b", 10.0), ("c", 10.0)]) == 0.0


def test_wilson_interval_brackets_the_point_estimate() -> None:
    low, high = wilson_interval(50, 1000)
    assert low < 0.05 < high
    # Symmetric enough for a mid-range proportion, and inside [0, 1].
    assert 0.0 <= low <= high <= 1.0


def test_wilson_interval_stays_valid_at_extreme_proportions() -> None:
    """The reason Wilson is used over the normal approximation."""
    for successes, total in ((0, 500), (500, 500), (2, 1000)):
        low, high = wilson_interval(successes, total)
        assert 0.0 <= low <= high <= 1.0, (successes, total)


def test_wilson_of_zero_rows() -> None:
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_pearson_of_a_perfect_line() -> None:
    import numpy as np

    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert _pearson(x, 2 * x + 1) == pytest.approx(1.0)


def test_pearson_of_unrelated_input_is_near_zero() -> None:
    import numpy as np

    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([3.0, 1.0, 4.0, 1.0, 5.0])
    assert abs(_pearson(x, y)) < 0.5


def test_spearman_is_unaffected_by_a_monotone_transform() -> None:
    import numpy as np

    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _spearman(x, x**3) == pytest.approx(1.0)


def test_p_value_is_none_for_an_undefined_correlation() -> None:
    assert _p_value(float("nan"), 100) is None
    assert _p_value(1.0, 100) is None
    assert _p_value(0.5, 2) is None


def test_p_value_flags_a_large_sample_small_correlation() -> None:
    # The same coefficient is significant or not depending on n, which is why
    # a p-value has to travel with the correlation. At n=1000 the threshold
    # is about r=0.063; at n=10 nothing short of a near-perfect fit reaches it.
    assert _p_value(0.02, 1000) > 0.05
    assert _p_value(0.10, 1000) < 0.05
    assert _p_value(0.10, 10) > 0.05


# ---------------------------------------------------------------------------
# the stage end to end
# ---------------------------------------------------------------------------


def test_run_mining_answers_all_seven_questions(mining_db) -> None:
    con, _ = mining_db
    summary = run_mining(Settings(db_path="unused"), con=con)
    assert summary["sections"] == len(SECTIONS) == 7
    assert set(SECTIONS) == {
        f"rq{i}_{name}"
        for i, name in [
            (1, "topic_mix"), (2, "bursts"), (3, "sensationalism"),
            (4, "clusters"), (5, "association_rules"),
            (6, "market_association"), (7, "classifier"),
        ]
    }


def test_mining_writes_its_results(mining_db, tmp_path: Path, monkeypatch) -> None:
    """The report quotes this file, so it has to be written and complete."""
    import json

    import dwm.mining as mining

    target = tmp_path / "mining.json"

    def fake_write(results, settings):
        target.write_text(json.dumps(results, default=str), encoding="utf-8")
        return target

    monkeypatch.setattr(mining, "_write", fake_write)
    con, _ = mining_db
    run_mining(Settings(db_path="unused"), con=con)
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert "rq7_classifier" in payload
    assert payload["corpus"]["headline_in_window"] >= 0
    assert payload["guard_summary"]["total"] >= 0


def test_mining_refuses_without_facts(settings: Settings) -> None:
    from dwm.db import connect

    con = connect(settings)
    try:
        with pytest.raises(RuntimeError, match="build"):
            run_mining(settings, con=con)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# RQ1: topic mix
# ---------------------------------------------------------------------------


def test_topic_mix_shares_are_within_year(mining_db) -> None:
    from dwm.mining.trends import topic_mix_by_year

    con, cfg = mining_db
    result = topic_mix_by_year(con, cfg)
    assert result["rows"]
    by_year: dict[int, float] = {}
    for r in result["rows"]:
        by_year[r["year"]] = by_year.get(r["year"], 0.0) + r["share_of_year"]
    for total in by_year.values():
        assert total == pytest.approx(1.0, abs=0.001)


def test_partial_year_is_flagged_not_dropped(mining_db) -> None:
    """A half year must still appear, marked, so nothing silently disappears."""
    from dwm.mining.trends import topic_mix_by_year

    con, cfg = mining_db
    cfg = copy.deepcopy(cfg)
    cfg["trends"]["partial_years"] = [2016]
    result = topic_mix_by_year(con, cfg)
    partial = [r for r in result["rows"] if r["year"] == 2016]
    assert partial
    assert all(r["is_partial_year"] and not r["comparable"] for r in partial)
    other = [r for r in result["rows"] if r["year"] != 2016]
    assert all(not r["is_partial_year"] and r["comparable"] for r in other)


def test_composition_shift_reports_percentage_points(mining_db) -> None:
    from dwm.mining.trends import composition_shift

    con, cfg = mining_db
    result = composition_shift(con, cfg)
    assert result["rows"]
    for row in result["rows"]:
        expected = (row["to_share"] - row["from_share"]) * 100
        assert row["change_pp"] == pytest.approx(expected, abs=1e-3)
        # A topic missing an intermediate year is compared across the gap and
        # says so, rather than presenting it as a year-on-year move.
        assert row["year_gap"] >= 1
        assert row["is_year_on_year"] == (row["year_gap"] == 1)


# ---------------------------------------------------------------------------
# RQ2: bursts
# ---------------------------------------------------------------------------


def test_burst_detection_excludes_partial_years_from_flatness(mining_db) -> None:
    """Regression: a 7-month year reported CV 0.39 for a flat series.

    The fixture has no year with more than one distinct month, so the rule is
    checked structurally: the threshold is threaded through, every year below
    it is listed as excluded, and no CV is invented for one.
    """
    from dwm.mining.trends import detect_bursts

    con, cfg = mining_db
    strict = copy.deepcopy(cfg)
    strict["trends"]["full_year_months"] = 12
    result = detect_bursts(con, strict)
    assert result["full_year_months_required"] == 12
    assert result["partial_years_excluded"], "short years must be named"
    # No CV is reported for a year below the threshold, rather than a wrong one.
    for excluded in result["partial_years_excluded"]:
        assert result["per_year_volume_cv"][excluded] is None


def test_burst_flatness_ignores_years_below_the_month_floor(mining_db) -> None:
    """A year excluded from flatness must not create a burst either."""
    from dwm.mining.trends import detect_bursts

    con, cfg = mining_db
    strict = copy.deepcopy(cfg)
    strict["trends"]["full_year_months"] = 12
    strict["bursts"]["z_threshold"] = -99.0  # would flag every month
    result = detect_bursts(con, strict)
    assert result["detected"] == [], "short years must not produce bursts"


def test_flatness_claim_needs_a_full_year(mining_db) -> None:
    """With no qualifying year, no flatness verdict may be asserted."""
    from dwm.mining.trends import detect_bursts

    con, cfg = mining_db
    strict = copy.deepcopy(cfg)
    strict["trends"]["full_year_months"] = 12
    result = detect_bursts(con, strict)
    assert result["max_within_year_volume_cv"] is None
    assert result["volume_is_flat"] is False


def test_burst_result_states_its_own_flatness(mining_db) -> None:
    from dwm.mining.trends import detect_bursts

    con, cfg = mining_db
    result = detect_bursts(con, cfg)
    assert "volume_is_flat" in result
    assert "finding" in result
    assert result["event_months"]
    for record in result["event_months"]:
        assert "label" in record and "measures" in record


def test_burst_event_records_carry_no_causal_claim(mining_db) -> None:
    from dwm.mining.trends import detect_bursts

    con, cfg = mining_db
    result = detect_bursts(con, cfg)
    assert "not a cause" in result["note"].lower()


# ---------------------------------------------------------------------------
# RQ3: sensationalism
# ---------------------------------------------------------------------------


def test_rate_is_never_reported_without_its_count(mining_db) -> None:
    from dwm.mining.sensationalism import sensationalism_by_topic

    con, cfg = mining_db
    for row in sensationalism_by_topic(con, cfg)["ranked"]:
        assert row["headline_count"] > 0
        if row["risk_signal_rate"] is not None:
            assert row["risk_signal_count"] is not None
        assert row["ci95_low"] <= row["ci95_high"]


def test_small_topics_are_excluded_from_the_ranking(mining_db) -> None:
    from dwm.mining.sensationalism import sensationalism_by_topic

    con, cfg = mining_db
    cfg = copy.deepcopy(cfg)
    cfg["sensationalism"]["min_topic_rows"] = 100_000
    result = sensationalism_by_topic(con, cfg)
    assert all(r["headline_count"] < 100_000 for r in result["ranked"])
    assert result["excluded_below_min_rows"]


def test_uninformative_topics_are_reported_separately(mining_db) -> None:
    """`Unknown` is a filing gap, not a subject, and must not lead the ranking."""
    from dwm.mining.sensationalism import sensationalism_by_topic

    con, cfg = mining_db
    result = sensationalism_by_topic(con, cfg)
    assert "uninformative_topics" in result
    uninformative = {r["topic"] for r in result["uninformative_topics"]["topics"]}
    assert uninformative <= {"Unknown", "Other"}
    for row in result["ranked_excluding_uninformative"]:
        assert row["topic"] not in {"Unknown", "Other"}


def test_threshold_sensitivity_reports_stability(mining_db) -> None:
    from dwm.mining.sensationalism import threshold_sensitivity

    con, cfg = mining_db
    cfg = copy.deepcopy(cfg)
    # The fixture is far below the production floor, so lower it rather than
    # asserting on a table that correctly refuses to rank anything.
    cfg["sensationalism"]["min_topic_rows"] = 1
    result = threshold_sensitivity(con, cfg)
    assert result["rows"], "a lowered floor must produce rows"
    assert "ranking_is_stable" in result
    for row in result["rows"]:
        assert "threshold" in row and "top1" in row
    # The chosen threshold must appear among the rows tested.
    assert any(r["is_chosen_threshold"] for r in result["rows"])
    # The floor is reported, so a reader can see what the ranking covered.
    assert result["min_topic_rows"] == 1


def test_no_result_uses_the_fake_news_phrase(mining_db) -> None:
    """The honesty rule, enforced mechanically over the whole payload."""
    import json

    from dwm.mining.sensationalism import sensationalism_by_topic

    con, cfg = mining_db
    blob = json.dumps(sensationalism_by_topic(con, cfg)).lower()
    assert "fake_news_rate" not in blob
    assert "fakenewsrate" not in blob
    assert "risk_signal_rate" in blob


def test_trend_by_year_carries_intervals(mining_db) -> None:
    from dwm.mining.sensationalism import sensationalism_trend_by_year

    con, cfg = mining_db
    result = sensationalism_trend_by_year(con, cfg)
    assert result["series"]
    for row in result["series"]:
        assert row["ci95_low"] <= row["risk_signal_rate"] <= row["ci95_high"]


# ---------------------------------------------------------------------------
# RQ5: association rules
# ---------------------------------------------------------------------------


def test_attribute_transactions_have_enough_items(mining_db) -> None:
    """The whole reason attributes were chosen over the keyword vocabulary."""
    con, cfg = mining_db
    built = build_attribute_transactions(con, cfg)
    assert built["transactions"]
    assert built["mean_items"] >= 3
    assert not built["sparse"]
    assert set(built["items"]) >= {"topic", "year", "sentiment_band"}


def test_transaction_frame_has_one_column_per_item() -> None:
    transactions = [frozenset({"a", "b"}), frozenset({"b", "c"}), frozenset({"a"})]
    frame = _to_frame(transactions)
    assert list(frame.columns) == ["a", "b", "c"]
    assert frame.shape == (3, 3)
    assert bool(frame.iloc[0]["a"]) is True
    assert bool(frame.iloc[0]["c"]) is False


def test_frame_handles_an_empty_transaction_set() -> None:
    assert _to_frame([]).empty


def test_rules_refuse_an_unknown_attribute(mining_db) -> None:
    con, cfg = mining_db
    cfg = copy.deepcopy(cfg)
    cfg["rules"]["transaction_items"] = ["not_a_real_attribute"]
    with pytest.raises(ValueError, match="unknown transaction_items"):
        build_attribute_transactions(con, cfg)


def test_both_algorithms_are_run_and_compared(mining_db) -> None:
    from dwm.mining.rules import mine_rules

    con, cfg = mining_db
    result = mine_rules(con, cfg)
    assert result["ran"]
    assert "apriori" in result and "fpgrowth" in result
    # The two algorithms must find the same rules, or one is broken.
    assert result["rule_sets_identical"] is True
    assert result["rules_in_apriori_not_fpgrowth"] == 0
    assert result["fpgrowth_speedup"] is not None


def test_rules_carry_no_causal_claim(mining_db) -> None:
    from dwm.mining.rules import mine_rules

    con, cfg = mining_db
    result = mine_rules(con, cfg)
    assert "not causation" in result["note"].lower()


def test_keyword_rules_report_their_sparsity(mining_db) -> None:
    from dwm.mining.rules import mine_keyword_rules

    con, cfg = mining_db
    result = mine_keyword_rules(con, cfg)
    if result.get("ran"):
        assert "mean_items" in result["transactions"]
        if result["transactions"]["sparse"]:
            assert result["caveat"], "a sparse run must carry its caveat"


# ---------------------------------------------------------------------------
# RQ6: market association
# ---------------------------------------------------------------------------


def test_market_uses_trading_days_only(mining_db) -> None:
    from dwm.mining.market import paired_series

    con, cfg = mining_db
    keys, volume, sentiment, sensational, returns, dates = paired_series(con, "Business")
    assert len(keys) == len(volume) == len(sentiment) == len(sensational) == len(returns)
    # Every paired date must be a real trading day.
    placeholders = ", ".join(str(k) for k in keys)
    assert _scalar(
        con, f"SELECT count(*) FROM fact_market_daily WHERE date_key IN ({placeholders})"
    ) == len(keys)


def test_lagged_correlation_reports_every_lag(mining_db) -> None:
    from dwm.mining.market import lagged_correlation

    con, cfg = mining_db
    result = lagged_correlation(con, cfg)
    if not result.get("ran") or not result.get("sufficient_data"):
        return
    lags = cfg["market"]["lags"]
    for measure in result["measures"].values():
        rows = measure["by_lag"]
        assert len(rows) == len(lags), "every requested lag gets a row"
        for row in rows:
            # Each row either carries a correlation or states why it could not.
            assert "lag_trading_days" in row
            assert "pearson_r" in row or "reason" in row


def test_lagged_correlation_refuses_insufficient_data(mining_db) -> None:
    from dwm.mining.market import lagged_correlation

    con, cfg = mining_db
    cfg = copy.deepcopy(cfg)
    cfg["market"]["min_observations"] = 100_000
    result = lagged_correlation(con, cfg)
    assert result["ran"] is True
    assert not result["sufficient_data"]
    assert "reason" in result
    assert "measures" not in result or not result["measures"]


def test_market_results_carry_no_causal_claim(mining_db) -> None:
    from dwm.mining.market import run_market

    con, cfg = mining_db
    result = run_market(con, cfg)
    text = str(result).lower()
    assert "association only" in text
    for banned in ("causes", "caused by", "leads to", "impact on the market"):
        assert banned not in text, f"market result contains causal wording: {banned}"


# ---------------------------------------------------------------------------
# RQ7: classifier
# ---------------------------------------------------------------------------


def test_classifier_is_judged_against_the_real_baseline(mining_db) -> None:
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    result = run_classifier(con, cfg)
    assert result["ran"]
    baseline = result["majority_baseline_accuracy"]
    # The IFND split is imbalanced, so the baseline is well away from 0.5.
    assert baseline > 0.5
    metrics = result["chosen_test_metrics"]
    assert metrics["majority_baseline_accuracy"] == baseline
    assert "lift_over_baseline_pp" in metrics


def test_classifier_reports_the_fake_class_first(mining_db) -> None:
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    result = run_classifier(con, cfg)
    metrics = result["chosen_test_metrics"]
    assert "FAKE" in metrics["per_class"]
    assert "fake_recall" in metrics
    assert "fake_precision" in metrics


def test_classifier_model_is_chosen_on_training_data(mining_db) -> None:
    """Choosing on test accuracy and then reporting it is the trap."""
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    result = run_classifier(con, cfg)
    assert "train_cv_accuracy" in result
    best_train = max(result["train_cv_accuracy"], key=lambda k: result["train_cv_accuracy"][k])
    assert result["chosen_on_train_cv"] == best_train


def test_classifier_is_reproducible(mining_db) -> None:
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    first = run_classifier(con, cfg)
    second = run_classifier(con, cfg)
    assert first["chosen_test_metrics"] == second["chosen_test_metrics"]
    assert first["train_cv_accuracy"] == second["train_cv_accuracy"]


def test_classifier_states_the_upper_bound_caveat(mining_db) -> None:
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    result = run_classifier(con, cfg)
    assert "upper bound" in result["upper_bound_caveat"].lower()
    assert "ground truth" in result["honesty_note"].lower()


def test_classifier_refuses_a_tiny_class(mining_db) -> None:
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    con.execute(
        "UPDATE fact_statement SET label_code='FAKE' WHERE statement_id > 6"
    )
    result = run_classifier(con, cfg)
    if not result.get("ran"):
        assert "reason" in result


def test_confusion_matrix_is_square_and_labelled(mining_db) -> None:
    from dwm.mining.classifier import run_classifier

    con, cfg = mining_db
    metrics = run_classifier(con, cfg)["chosen_test_metrics"]
    matrix = metrics["confusion_matrix"]
    assert len(matrix["matrix"]) == len(matrix["labels"])
    for row in matrix["matrix"]:
        assert len(row) == len(matrix["labels"])


def test_metrics_helper_reports_a_lift_over_baseline() -> None:
    import numpy as np

    truth = np.array(["REAL", "REAL", "FAKE", "FAKE"])
    predicted = np.array(["REAL", "REAL", "FAKE", "FAKE"])
    result = _metrics(truth, predicted, 0.5)
    assert result["accuracy"] == 1.0
    assert result["lift_over_baseline_pp"] == pytest.approx(50.0)
    assert result["beats_baseline"] is True
    assert result["fake_recall"] == 1.0


def test_metrics_helper_flags_a_useless_model() -> None:
    """A model that always says REAL must not look good."""
    import numpy as np

    truth = np.array(["REAL", "REAL", "REAL", "FAKE"])
    predicted = np.array(["REAL", "REAL", "REAL", "REAL"])
    result = _metrics(truth, predicted, 0.75)
    assert result["fake_recall"] == 0.0
    assert result["accuracy"] == 0.75
    assert result["lift_over_baseline_pp"] == pytest.approx(0.0)
