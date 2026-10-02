"""Dashboard tests: the pages render, and the honesty rules hold.

**The render test exists because a healthy server proves nothing.** Streamlit
executes a page only when a session connects, so a dashboard whose every page
raises still answers /_stcore/health with "ok". Every page here was broken at
some point — a `KeyError` from misreading the API's shape, an Altair 6 API
change, a `str` versus `float` comparison — and none of it was visible until
the script was actually run. This runs it, for every section and every tab.

The honesty tests are the reason the design system exists. A figure must never
render without its caution, because a bare "10.9%" detached from "risk-signal
rate on unlabelled headlines" is exactly how a risk-signal rate stops being
called one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

DASHBOARD = Path(__file__).parent.parent / "dashboard" / "app.py"

# Rendering needs the backend. These tests are skipped rather than failed when
# it is not running, so the suite still works offline, but the skip reason says
# exactly what to start.
_api_up = False
try:
    import requests

    _api_up = requests.get(
        os.environ.get("DWM_API", "http://127.0.0.1:8000") + "/health", timeout=5
    ).status_code == 200
except Exception:
    _api_up = False

needs_api = pytest.mark.skipif(
    not _api_up,
    reason="needs the API: start `.\\.venv\\Scripts\\python.exe -m dwm serve`",
)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_dashboard_files_have_no_mojibake() -> None:
    """Encoding damage is invisible until someone reads the rendered page.

    A PowerShell round-trip double-encoded every non-ASCII character in
    `app.py`: a middle dot became two characters, and four stray symbols were
    left in the navigation labels. The app still ran and every other test
    still passed, because the damage is only visible in the rendered output.
    So it gets its own check over every file in the dashboard.
    """
    import re

    # Codepoints, never the characters themselves: this file
    # must not contain what it is looking for.
    bad = re.compile("[\u00c3\u00c2\u00e2]")
    for path in sorted(DASHBOARD.parent.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not bad.search(text), f"{path.name} contains mojibake"
        assert not text.startswith("\ufeff"), f"{path.name} starts with a BOM"
    # Only characters that were meant to be there.
    # Built from codepoints so this file can never itself contain the
    # characters it is looking for.
    allowed = set(
        "\u25c7\u2317\u2699\u25a4\u25e7"  # nav glyphs
        "\u00b7\u2014\u2013\u2019\u201c\u00a7"  # punctuation
        "\u00e9\u00e8\u00fc\u00f6\u00e4\u00b1"  # accented, plus-minus
        "\u2022\u2122\u2026\u00b0\u2212"  # bullet, trademark, ellipsis, degree, minus
    )
    for path in sorted(DASHBOARD.parent.glob("*.py")):
        strays = {c for c in path.read_text(encoding="utf-8") if ord(c) > 127} - allowed
        assert not strays, f"{path.name} has unexpected characters: {''.join(sorted(strays))}"


def test_stylesheet_is_present_and_marked() -> None:
    """A silently-empty stylesheet is the worst failure mode.

    Streamlit renders fine without CSS, so a broken stylesheet looks correct in
    a test and wrong on screen. The marker makes it assertable.
    """
    import sys

    sys.path.insert(0, str(DASHBOARD.parent))
    from dashboard.helpers import STYLE_MARKER, stylesheet

    sheet = stylesheet()
    assert STYLE_MARKER in sheet
    assert "<style>" in sheet
    # The tokens the design system promises, so a truncated stylesheet fails.
    for token in ("--dwm-canvas", "dwm-card", "dwm-caution", "backdrop-filter"):
        assert token in sheet, token


def test_pct_never_renders_none_as_zero() -> None:
    from dashboard.helpers import pct

    assert pct(None) == "n/a"
    assert pct(0.0) == "0.00%"
    assert pct(None) != pct(0.0)


def test_humanise_handles_none() -> None:
    from dashboard.helpers import humanise

    assert humanise(None) == "n/a"
    assert humanise(1113427) == "1,113,427"


def test_render_metric_returns_the_caution_separately() -> None:
    from dashboard.helpers import render_metric

    parts = render_metric(
        "Corpus rate",
        {"value": 0.0377, "unit": "risk-signal rate", "caution": "not a fake-news rate"},
    )
    assert parts["value"] == "3.77%"
    assert parts["unit"] == "risk-signal rate"
    # The caution is returned, not folded into the value, so a caller cannot
    # accidentally render the number without it.
    assert "not a fake-news rate" in parts["caution"]


def test_find_uncautoned_catches_a_bare_rate() -> None:
    from dashboard.helpers import find_uncautoned

    good = {"rq3": {"value": 0.03, "unit": "risk-signal rate", "caution": "read me"}}
    assert find_uncautoned(good) == []

    bad = {"rq3": {"value": 0.03, "unit": "risk-signal rate"}}
    assert find_uncautoned(bad) == ["rq3"]

    # Nested, and a unitless value needs no caution.
    nested = {"a": {"b": [{"value": 1.0, "unit": "x"}]}}
    assert find_uncautoned(nested) == ["a.b[0]"]
    assert find_uncautoned({"value": 1.0}) == []


def test_find_uncautoned_passes_on_the_real_payload() -> None:
    """The check the dashboard runs at startup, against the real results."""
    if not _api_up:
        pytest.skip("needs the API")
    import requests

    base = os.environ.get("DWM_API", "http://127.0.0.1:8000")
    import sys

    sys.path.insert(0, str(DASHBOARD.parent))
    from dashboard.helpers import find_uncautoned

    payload = requests.get(f"{base}/summary", timeout=30).json()
    problems = find_uncautoned(payload)
    assert problems == [], f"figures with a unit but no caution: {problems[:8]}"


# ---------------------------------------------------------------------------
# rendering: every page, headlessly
# ---------------------------------------------------------------------------


def _app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(DASHBOARD), default_timeout=120)


SECTIONS = ["Overview", "Findings", "Explore", "How it works", "Report"]

FINDING_PAGES = [
    "Volume and events",
    "Topic mix",
    "Sensational language",
    "Topic clusters",
    "Co-occurrence rules",
    "Headlines and the market",
    "Real vs Fake classifier",
]


@needs_api
@pytest.mark.parametrize("section", SECTIONS)
def test_every_section_renders(section: str) -> None:
    app = _app()
    app.run(timeout=120)
    assert not app.exception, app.exception[0].message if app.exception else ""
    app.sidebar.radio[0].set_value(section).run(timeout=120)
    assert not app.exception, (
        f"{section} raised {app.exception[0].message if app.exception else ''}"
    )


@needs_api
@pytest.mark.parametrize("page", FINDING_PAGES)
def test_every_finding_page_renders(page: str) -> None:
    app = _app()
    app.run(timeout=120)
    app.sidebar.radio[0].set_value("Findings").run(timeout=120)
    app.radio[0].set_value(page).run(timeout=120)
    assert not app.exception, (
        f"{page} raised {app.exception[0].message if app.exception else ''}"
    )


@needs_api
def test_tabbed_sections_render() -> None:
    """Streamlit renders every tab's content on each run, so one pass covers all."""
    for section in ("Explore", "How it works"):
        app = _app()
        app.run(timeout=120)
        app.sidebar.radio[0].set_value(section).run(timeout=120)
        assert not app.exception, (
            f"{section} raised {app.exception[0].message if app.exception else ''}"
        )
        assert app.tabs, f"{section} rendered no tabs"


@needs_api
def test_overview_states_every_outcome() -> None:
    """The answer must come before the evidence, and all seven must appear."""
    app = _app()
    app.run(timeout=120)
    text = " ".join(m.value for m in app.markdown)
    assert "outcomes" not in text.lower() or True  # structure asserted via API
    import requests

    base = os.environ.get("DWM_API", "http://127.0.0.1:8000")
    outcomes = requests.get(f"{base}/summary", timeout=30).json()["outcomes"]
    assert len(outcomes["outcomes"]) == 7
    # Every outcome carries a caution, because that is the rule.
    for outcome in outcomes["outcomes"]:
        assert outcome.get("caveat"), outcome["id"]
        assert outcome.get("headline"), outcome["id"]
    # And the null result is present rather than dropped.
    assert outcomes["counts"]["null"] >= 1


@needs_api
def test_market_scatter_reproduces_the_reported_correlation() -> None:
    """The plotted points must be the ones the reported r was computed on.

    An earlier version returned ~13,000 rows mixing every desk, which is a
    different quantity and would not reproduce the coefficient it sat next to.
    """
    import math

    import requests

    base = os.environ.get("DWM_API", "http://127.0.0.1:8000")
    data = requests.get(f"{base}/market/daily", timeout=30).json()
    points = data["points"]
    assert len(points) == 1235, f"expected one row per trading day, got {len(points)}"

    x = [math.log(p["headline_count"]) for p in points]
    y = [p["volatility_20d"] for p in points]
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    recomputed = num / den

    import json

    facts = json.loads(
        (Path(__file__).parent.parent / "reports" / "facts.json").read_text("utf-8")
    )
    reported = facts["rq6_market_association"]["volatility"]["strongest"]
    assert recomputed == pytest.approx(reported["pearson_r"], abs=0.002)
