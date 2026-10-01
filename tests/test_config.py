"""Configuration loading: dataset specs, topic map, analysis window."""

from __future__ import annotations

from datetime import date

import pytest

from dwm.config import (
    Settings,
    analysis_window,
    days_in_window,
    load_datasets_config,
    load_topic_map,
)


def test_settings_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        Settings(sample=0)
    with pytest.raises(ValueError):
        Settings(years=0)
    with pytest.raises(ValueError):
        Settings(chunk=-5)


def test_all_three_datasets_configured() -> None:
    specs = load_datasets_config()
    assert set(specs) == {"toi", "ifnd", "nifty"}
    assert all(s.enabled for s in specs.values())


def test_toi_aliases_match_the_verified_header() -> None:
    toi = load_datasets_config()["toi"]
    # Logical keys, with the verified header names as first aliases.
    assert toi.alias_list("text")[0] == "headline_text"
    assert toi.alias_list("date")[0] == "publish_date"
    assert toi.alias_list("category")[0] == "headline_category"
    assert toi.text_column == "text"
    assert toi.has_text
    assert toi.date_formats[0] == "%Y%m%d"
    assert not toi.is_labelled


def test_ifnd_is_labelled_with_month_precision() -> None:
    ifnd = load_datasets_config()["ifnd"]
    assert ifnd.is_labelled
    assert ifnd.label_column == "label"
    # Month-year only, so the window cannot claim day resolution.
    assert ifnd.declared_date_precision == "month"
    assert set(ifnd.label_values) == {"real", "fake"}


def test_nifty_declares_numeric_columns_and_no_text() -> None:
    nifty = load_datasets_config()["nifty"]
    assert nifty.numeric_columns == ["open", "high", "low", "close", "volume", "turnover"]
    assert nifty.declared_date_precision == "day"
    # A price series has no headline, and the loader must not demand one.
    assert nifty.text_column is None
    assert not nifty.has_text


def test_alias_falls_back_when_config_is_silent() -> None:
    toi = load_datasets_config()["toi"]
    # Not declared in config: must not raise.
    assert toi.alias("nonexistent_field") == "nonexistent_field"


def test_provenance_is_captured_for_the_report() -> None:
    specs = load_datasets_config()
    # The nifty mirror is unofficial and the report has to say so.
    assert "unofficial" in specs["nifty"].provenance.lower()
    assert specs["toi"].citation


def test_analysis_window_is_derived_not_hardcoded() -> None:
    start, end = analysis_window(date(2020, 6, 30), 5)
    assert end == date(2020, 6, 30)
    assert start == date(2015, 6, 30)
    assert days_in_window(5) > 1800


def test_analysis_window_handles_leap_day() -> None:
    start, end = analysis_window(date(2020, 2, 29), 5)
    assert end == date(2020, 2, 29)
    assert start == date(2015, 2, 28)  # 2015 is not a leap year


def test_topic_map_covers_hierarchical_categories() -> None:
    topics = load_topic_map()
    assert topics.lookup("sports.wwe") == "Sports"
    assert topics.lookup("business.gadgets") == "Business"
    assert topics.lookup("politics.parliament") == "Politics"
    assert topics.lookup("covid-19") == "Health"


def test_topic_map_handles_missing_and_unknown() -> None:
    topics = load_topic_map()
    assert topics.lookup(None) == "Unknown"
    assert topics.lookup("") == "Unknown"
    assert topics.lookup("unknown") == "Unknown"
    # Unmapped categories still get a topic, they are never dropped.
    assert topics.lookup("totally.made.up") == "Other"


def test_topic_map_keywords_only_fire_after_prefix_lookup() -> None:
    topics = load_topic_map()
    assert topics.lookup("technology.startups") == "Technology"
    assert topics.lookup("some.corona.virus.story") == "Health"


def test_topic_map_handles_the_times_city_editions() -> None:
    topics = load_topic_map()
    # Too many to enumerate individually, so they are matched by pattern.
    assert topics.lookup("delhi-times") == "Local"
    assert topics.lookup("bombay-times") == "Local"
    assert topics.lookup("lucknow-times") == "Local"


def test_prefix_patterns_run_after_the_exact_map() -> None:
    topics = load_topic_map()
    # An exact prefix entry must win over a pattern that would also match.
    assert topics.lookup("city.mumbai") == "Local"
    assert topics.lookup("sports.cricket") == "Sports"
    # life-style.health-fitness is Health, not the generic Lifestyle.
    assert topics.lookup("life-style.health-fitness.diet") == "Health"
    assert topics.lookup("life-style.beauty") == "Lifestyle"


def test_every_mapped_topic_exists_in_the_topic_list() -> None:
    topics = load_topic_map()
    known = set(topics.topics)
    for source_topic in topics.prefix_map.values():
        assert source_topic in known, f"{source_topic} missing from topics list"
    for _, source_topic in topics.prefix_patterns:
        assert source_topic in known, f"{source_topic} missing from topics list"
