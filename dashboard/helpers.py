"""Shared, browser-free helpers for the dashboard.

**Why this exists rather than living in the front end.** Three of the rules
this project holds itself to cannot be enforced from JavaScript: they need to be
asserted in a test suite that runs without a browser, and they need to be
enforceable against the *data* rather than trusted to each call site.

* `find_uncautoned` walks a payload for any figure that has a unit and no
  caution. The front end runs the same logic at start-up (`auditPayload` in
  `static/app.js`) and reports anything it finds, but a test is what stops it
  shipping.
* `pct` refuses to render `None` as `0%`. A missing count and a zero count are
  different facts and must not print the same thing.
* The design system's palette lives here rather than in `static/app.css` so the
  chart specs and the page cannot drift apart. `static/app.css` is the single
  source of truth for the page; this module mirrors the chart-relevant subset
  for the Vega-Lite specs, and `tests/test_ui.py` asserts the two agree.

The Streamlit stylesheet that used to live here is gone. It fought the
framework rather than styling it: on a machine set to dark mode it produced a
light page with dark widgets over it, which is unfixable from the outside
because a CSS-injection layer cannot know what the framework will paint next.
"""

from __future__ import annotations

import json
from typing import Any

# The chart-relevant subset of the palette in `static/app.css`. Duplicated on
# purpose — a Vega-Lite spec is JSON built in Python and cannot read a
# stylesheet — and kept honest by `test_ui.py::test_chart_palette_matches_css`.
CHART_PALETTE = {
    "accent": "#0062C4",
    "positive": "#157F3C",
    "caution": "#9A6200",
    "negative": "#C8102E",
    "muted": "#5E5E63",
}

DARK_CHART_PALETTE = {
    "accent": "#3B9BFF",
    "positive": "#3DD168",
    "caution": "#FFB340",
    "negative": "#FF5C6C",
    "muted": "#A0A0A8",
}


def humanise(value: float | int | None) -> str:
    """Thousands-separated integer, or an explicit dash when absent."""
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def pct(value: float | None, places: int = 2) -> str:
    """A proportion as a percentage. Never renders None as 0%."""
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"


def find_uncautoned(payload: Any) -> list[str]:
    """Every fact in a payload that has a unit but no caution.

    Returns the dotted paths that are missing one, so a failure names the
    section rather than just counting. A bare "10.9%", detached from "risk-signal
    rate on unlabelled headlines", is exactly how a risk-signal rate stops being
    called one — and this is the check that says so before a reader does.
    """
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("unit") and not node.get("caution") and "value" in node:
                problems.append(path or "<root>")
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(payload, "")
    return problems


def payload_has_cautions(payload: Any) -> bool:
    return not find_uncautoned(payload)


def to_json(payload: Any) -> str:
    return json.dumps(payload, default=str, indent=2)
