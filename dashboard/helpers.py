"""Shared helpers for the Streamlit dashboard.

The dashboard is deliberately thin (BLUEPRINT section 1): it calls the API and
renders what comes back, and computes nothing. These helpers exist so that
"renders what comes back" is testable without launching a browser.

**The one rule these helpers enforce** is that a figure is never shown without
its caution. A bare "10.9%" detached from "risk-signal rate on unlabelled
headlines" is precisely how a risk-signal rate stops being called one, and the
dashboard is the last place that wording survives contact with a reader.
`render_metric` returns the three parts separately so a test can assert the
caution is present.
"""

from __future__ import annotations

from typing import Any

# Shown when the backend has no data yet, rather than an empty screen that
# reads as "there is nothing to see".
NO_DATA = (
    "No data yet. Build the warehouse with `run_all.ps1 -clean`, then run "
    "`python -m dwm mine` and `python -m dwm report`."
)


def humanise(value: float | int | None) -> str:
    """Thousands-separated integer, or an explicit `n/a`."""
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def pct(value: float | None, places: int = 2) -> str:
    """A proportion as a percentage. Never returns a bare 0 for a None."""
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"


def render_metric(label: str, block: dict[str, Any], fmt=pct) -> dict[str, str]:
    """Return the three parts of a displayed figure: value, unit, caution.

    Split out from the Streamlit calls so a test can check that the caution is
    never dropped, which is the whole reason this function exists.
    """
    return {
        "label": label,
        "value": fmt(block.get("value")),
        "unit": block.get("unit") or "",
        "caution": block.get("caution") or "",
    }


def has_all_cautions(summary: dict[str, Any]) -> bool:
    """True when every section carrying a rate also carries a caution.

    Used by the dashboard's own startup check: if a section ever loses its
    caution, the dashboard says so rather than quietly rendering the number.
    """
    for block in summary.values():
        # `honesty_rules` and `corpus` are lists, not fact blocks.
        if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
            continue
        fact = block["data"].get("fact")
        if not isinstance(fact, dict):
            continue
        if fact.get("unit") and not fact.get("caution"):
            return False
    return True
