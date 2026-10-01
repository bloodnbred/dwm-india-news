"""Value parsing shared by ingest and ETL.

Date parsing is deliberately explicit about precision. IFND carries
month-year only ("Oct-20", "Nov 2020"), so a resolved date is returned
together with a precision tag rather than a silently invented day
(BLUEPRINT section 7, "IFND has no dates").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

# Formats that carry no day component. Resolving one of these yields a
# month-start date plus precision="month".
_MONTH_ONLY_FORMATS = {
    "%b-%y", "%b-%Y", "%B-%y", "%B-%Y",
    "%b %y", "%b %Y", "%B %y", "%B %Y",
    "%Y-%m", "%Y",
}

# Formats that carry a day and a month but NO year, e.g. IFND's "20-Sep".
# The calendar date cannot be resolved, so value stays None and the month and
# day are reported separately. The year is never guessed.
_YEARLESS_FORMATS = {"%d-%b", "%d-%B", "%d %b", "%d %B"}

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ParsedDate:
    """A resolved calendar date plus how much of it the source actually had.

    `value` is None whenever the source does not pin down a full date. The
    month and day are still reported when they are known, so a caller can use
    day-of-year seasonality without the year being fabricated.
    """

    value: date | None
    precision: str  # "day" | "month" | "month_day" | "none"
    raw: str | None
    month: int | None = None
    day: int | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None

    def iso(self) -> str | None:
        return self.value.isoformat() if self.value else None


def _clean(raw: str | None) -> str:
    if raw is None:
        return ""
    text = _WHITESPACE.sub(" ", str(raw)).strip()
    # A few sources carry BOMs or trailing separators.
    return text.strip("﻿").strip()


def parse_date(raw: str | None, formats: Iterable[str]) -> ParsedDate:
    """Parse `raw` trying each strptime format in order.

    Never raises: an unparseable value comes back as precision="none" so the
    caller can count it into etl_audit and carry on (BLUEPRINT section 7,
    "Dates in mixed formats").
    """
    text = _clean(raw)
    if not text:
        return ParsedDate(None, "none", raw)

    for fmt in formats:
        pattern = _compile_format(fmt)
        if pattern is None:
            continue
        match = pattern.fullmatch(text)
        if not match:
            continue
        groups = match.groupdict()
        if fmt in _YEARLESS_FORMATS:
            # Day and month known, year absent: report them, resolve nothing.
            month = _month_from(groups)
            day = int(groups["d"]) if groups.get("d") else None
            return ParsedDate(None, "month_day", raw, month=month, day=day)
        try:
            value = date(*_assemble(groups))
        except (ValueError, KeyError):
            continue
        precision = "month" if fmt in _MONTH_ONLY_FORMATS else "day"
        month = _month_from(groups)
        day = int(groups["d"]) if groups.get("d") else 1
        return ParsedDate(value, precision, raw, month=month, day=day)

    # Last resort: a bare YYYYMMDD that no configured format matched.
    if text.isdigit() and len(text) == 8:
        try:
            value = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            pass
        else:
            return ParsedDate(value, "day", raw, month=value.month, day=value.day)
    return ParsedDate(None, "none", raw)


def _month_from(groups: dict[str, str | None]) -> int | None:
    if groups.get("m"):
        return int(groups["m"])
    if groups.get("b"):
        return _MONTHS_ABBR[str(groups["b"])[:3].lower()]
    return None


_MONTHS_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH_ALTERNATION = "|".join(_MONTHS_ABBR)

# strptime directive -> regex fragment. Literals in the format are escaped, so
# "%b-%Y" and "%B-%Y" both work regardless of month-name length.
_DIRECTIVE_RE: dict[str, str] = {
    "Y": r"(?P<Y>\d{4})",
    "y": r"(?P<y>\d{2})",
    "m": r"(?P<m>\d{2})",
    "d": r"(?P<d>\d{2})",
    "b": rf"(?P<b>{_MONTH_ALTERNATION})",
    "B": rf"(?P<b>{_MONTH_ALTERNATION})",
}

_FORMAT_CACHE: dict[str, re.Pattern[str]] = {}


def _compile_format(fmt: str) -> re.Pattern[str] | None:
    """Turn a strptime format into a case-insensitive regex, or None if unsupported."""
    cached = _FORMAT_CACHE.get(fmt)
    if cached is not None:
        return cached or None

    parts: list[str] = []
    i = 0
    supported = True
    while i < len(fmt):
        ch = fmt[i]
        if ch == "%" and i + 1 < len(fmt):
            directive = fmt[i + 1]
            fragment = _DIRECTIVE_RE.get(directive)
            if fragment is None:
                supported = False
                break
            parts.append(fragment)
            i += 2
            continue
        parts.append(re.escape(ch))
        i += 1

    pattern = re.compile("".join(parts), re.IGNORECASE) if supported else None
    _FORMAT_CACHE[fmt] = pattern if pattern is not None else re.compile(r"(?!)")
    return pattern


def _assemble(out: dict[str, str | None]) -> tuple[int, int, int]:
    """Build (year, month, day) from regex groups.

    A year-only format yields January 1st, which parse_date tags as
    precision="month" so no caller mistakes it for a real day-level date.
    """
    if out.get("Y"):
        year = int(out["Y"])
    elif out.get("y"):
        year = _two_digit_year(str(out["y"]))
    else:
        raise ValueError("no year in match")

    if out.get("m"):
        month = int(out["m"])
    elif out.get("b"):
        month = _MONTHS_ABBR[str(out["b"])[:3].lower()]
    else:
        month = 1

    day = int(out["d"]) if out.get("d") else 1
    return year, month, day


def _two_digit_year(value: str) -> int:
    """Map a 2-digit year onto 1900-2099, matching the pivot everyone uses."""
    n = int(value)
    return 1900 + n if n >= 70 else 2000 + n


def parse_date_column(
    values: Iterable[str | None], formats: Iterable[str]
) -> list[ParsedDate]:
    """Vector-friendly wrapper: parse a whole column, order preserved."""
    fmts = list(formats)
    return [parse_date(v, fmts) for v in values]


def normalise_label(raw: str | None, label_values: dict[str, list[str]]) -> int | None:
    """Map a raw label to 1 = real / 0 = fake / None when unrecognised."""
    text = _clean(raw).lower()
    if not text:
        return None
    for canonical, accepted in label_values.items():
        if text in {str(a).strip().lower() for a in accepted}:
            return 1 if canonical == "real" else 0
    return None


def category_prefix(category: str | None, separator: str | None) -> str | None:
    """Top-level segment of a hierarchical category, e.g. sports.wwe -> sports."""
    text = _clean(category)
    if not text:
        return None
    if separator:
        return text.split(separator)[0].strip().lower() or None
    return text.strip().lower() or None
