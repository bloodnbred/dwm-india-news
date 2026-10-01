"""Value parsing: dates with honest precision, labels, category prefixes."""

from __future__ import annotations

from datetime import date

from dwm.config import load_datasets_config
from dwm.parse import ParsedDate, category_prefix, normalise_label, parse_date

# Read the format lists from config so these tests cannot drift away from
# what the pipeline actually uses.
_SPECS = load_datasets_config()
TOI_FORMATS = _SPECS["toi"].date_formats
IFND_FORMATS = _SPECS["ifnd"].date_formats


def test_toi_compact_date_is_day_precision() -> None:
    result = parse_date("20010101", TOI_FORMATS)
    assert result.value == date(2001, 1, 1)
    assert result.precision == "day"


def test_ifnd_month_year_is_downgraded_to_month_precision() -> None:
    result = parse_date("Oct-20", IFND_FORMATS)
    assert result.value == date(2020, 10, 1)
    # The whole point: we do not invent a day for month-only sources.
    assert result.precision == "month"


def test_ifnd_long_month_name_with_year() -> None:
    result = parse_date("Nov 2020", IFND_FORMATS)
    assert result.value == date(2020, 11, 1)
    assert result.precision == "month"


def test_bare_year_resolves_to_january_first() -> None:
    result = parse_date("2019", IFND_FORMATS)
    assert result.value == date(2019, 1, 1)
    assert result.precision == "month"


def test_two_digit_year_pivot() -> None:
    assert parse_date("Oct-20", IFND_FORMATS).value == date(2020, 10, 1)
    assert parse_date("Oct-99", IFND_FORMATS).value == date(1999, 10, 1)


def test_day_month_without_a_year_is_never_guessed() -> None:
    """IFND ships "20-Sep": a day and month but no year.

    The calendar date cannot be resolved, so value stays None. The month and
    day are still reported for seasonality work. Inventing a year would put
    rows in the wrong analysis window.
    """
    result = parse_date("20-Sep", IFND_FORMATS)
    assert result.value is None
    assert result.precision == "month_day"
    assert result.month == 9
    assert result.day == 20
    assert not result.ok


def test_bare_day_month_is_counted_not_failed() -> None:
    result = parse_date("01-Jan", IFND_FORMATS)
    assert result.precision == "month_day"
    assert (result.month, result.day) == (1, 1)


def test_resolved_dates_report_month_and_day() -> None:
    result = parse_date("20010101", TOI_FORMATS)
    assert (result.month, result.day) == (1, 1)
    result = parse_date("Oct-20", IFND_FORMATS)
    assert (result.month, result.day) == (10, 1)


def test_garbage_never_raises() -> None:
    for raw in ("", "   ", "not-a-date", "99999999", "32-Jan-2020", None):
        result = parse_date(raw, TOI_FORMATS)
        assert isinstance(result, ParsedDate)
        assert not result.ok
        assert result.precision == "none"
        assert result.month is None


def test_fallback_for_undelcared_compact_date() -> None:
    # A source that only declared %Y-%m-%d but ships YYYYMMDD still parses.
    result = parse_date("20150630", ["%Y-%m-%d"])
    assert result.value == date(2015, 6, 30)
    assert result.precision == "day"


def test_whitespace_and_bom_are_tolerated() -> None:
    assert parse_date("  20010101  ", TOI_FORMATS).value == date(2001, 1, 1)
    assert parse_date("﻿20010101", TOI_FORMATS).value == date(2001, 1, 1)


def test_label_normalisation() -> None:
    mapping = {"real": ["TRUE", "True", "1", "real"], "fake": ["FALSE", "0", "fake"]}
    assert normalise_label("TRUE", mapping) == 1
    assert normalise_label("true", mapping) == 1
    assert normalise_label("1", mapping) == 1
    assert normalise_label("FALSE", mapping) == 0
    assert normalise_label(" Fake ", mapping) == 0
    assert normalise_label("REAL", mapping) == 1
    assert normalise_label("maybe", mapping) is None
    assert normalise_label(None, mapping) is None
    assert normalise_label("", mapping) is None


def test_label_values_come_from_config() -> None:
    # The real IFND mapping handles the source's mixed casing.
    mapping = _SPECS["ifnd"].label_values
    assert normalise_label("TRUE", mapping) == 1
    assert normalise_label("Fake", mapping) == 0


def test_category_prefix() -> None:
    assert category_prefix("sports.wwe", ".") == "sports"
    assert category_prefix("Sports.WWE", ".") == "sports"
    assert category_prefix("unknown", ".") == "unknown"
    assert category_prefix("", ".") is None
    assert category_prefix(None, ".") is None
    # Without a separator the whole value is the prefix.
    assert category_prefix("COVID-19", None) == "covid-19"
