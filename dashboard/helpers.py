"""Design system for the dashboard.

The whole visual layer lives here, in one function, so it can be read in one
place and reverted in one place.

**Deliberately minimal.** This is Apple-minimal rather than a glass-effects
showcase: near-white canvas, one accent, generous space, and soft cards. The
blur appears on the sidebar only. An earlier plan called for a colour-wash
canvas and a three-layer depth stack; both were dropped, because they cost a
lot of CSS, they age badly, and the finished look comes from typography and
spacing rather than from effects.

The one rule this module exists to protect is that a figure never renders
without its caveat. `metric_card` and `outcome_card` both make the caution
mandatory, and `find_uncautoned` lets the dashboard check the whole payload
rather than trusting that every call site remembered.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------

CANVAS = "#F5F5F7"
SURFACE = "#FFFFFF"
INK = "#1D1D1F"
INK_SOFT = "#6E6E73"
HAIRLINE = "rgba(0,0,0,0.08)"
ACCENT = "#0071E3"
POSITIVE = "#34C759"
CAUTION = "#FF9F0A"
NEGATIVE = "#FF3B30"
SERIES = ["#0071E3", "#5AC8FA", "#34C759", "#FF9F0A", "#FF3B30",
          "#AF52DE", "#FF2D55", "#8E8E93"]

# A muted categorical ramp for the charts. Full saturation reads as a toy;
# these are the same hues at a weight that sits behind text.
CHART_SERIES = [
    "#0071E3", "#34C759", "#FF9F0A", "#FF3B30",
    "#5AC8FA", "#AF52DE", "#FF2D55", "#34AADC", "#8E8E93",
]

# The colour each outcome kind wears. A null result is not a failure, so it is
# grey-blue rather than red; only a genuine negative is red.
KIND_COLOUR = {
    "null": "#8E8E93",
    "qualified": CAUTION,
    "positive": POSITIVE,
    "split": ACCENT,
}
KIND_LABEL = {
    "null": "No result",
    "qualified": "Qualified",
    "positive": "Finding",
    "split": "Split answer",
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def css() -> str:
    """The entire stylesheet.

    Selectors are kept to Streamlit's own stable-ish class names plus the
    `dwm-*` hooks used below. Each is wrapped in `:has()` or a descendant
    selector where practical, because Streamlit renames internal classes
    between versions and a smoke test checks that the styling still applies.
    """
    return f"""
<style>
  :root {{
    --dwm-canvas: {CANVAS};
    --dwm-surface: {SURFACE};
    --dwm-ink: {INK};
    --dwm-ink-soft: {INK_SOFT};
    --dwm-hairline: {HAIRLINE};
    --dwm-accent: {ACCENT};
    --dwm-positive: {POSITIVE};
    --dwm-caution: {CAUTION};
    --dwm-negative: {NEGATIVE};
    --dwm-radius: 18px;
    --dwm-shadow: 0 1px 2px rgba(0,0,0,.04), 0 6px 20px rgba(0,0,0,.05);
    --dwm-ease: cubic-bezier(.4,0,.2,1);
  }}

  /* ---- canvas ------------------------------------------------------- */
  .stApp {{
    background: var(--dwm-canvas);
    color: var(--dwm-ink);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                 "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
    color: var(--dwm-ink);
    letter-spacing: -.022em;
    font-weight: 600;
  }}
  .stApp h1 {{ font-size: 2.1rem; line-height: 1.15; }}
  .stApp h2 {{ font-size: 1.4rem; }}
  .stApp h3 {{ font-size: 1.05rem; letter-spacing: -.01em; }}
  .stApp p, .stApp li, .stApp label, .stApp span {{ color: var(--dwm-ink); }}

  /* ---- the sidebar: the one frosted surface ------------------------ */
  section[data-testid="stSidebar"] {{
    background: rgba(255,255,255,.72);
    backdrop-filter: saturate(180%) blur(24px);
    -webkit-backdrop-filter: saturate(180%) blur(24px);
    border-right: 1px solid var(--dwm-hairline);
  }}
  section[data-testid="stSidebar"] .block-container {{ padding-top: 1.6rem; }}
  section[data-testid="stSidebar"] h1 {{
    font-size: 1.02rem; letter-spacing: -.02em; margin-bottom: .1rem;
  }}
  section[data-testid="stSidebar"] [role="radiogroup"] label {{
    padding: .3rem .5rem; border-radius: 10px; font-size: .9rem;
    transition: background 150ms var(--dwm-ease);
  }}
  section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
    background: rgba(0,0,0,.035);
  }}

  /* ---- cards -------------------------------------------------------- */
  .dwm-card {{
    background: var(--dwm-surface);
    border: 1px solid var(--dwm-hairline);
    border-radius: var(--dwm-radius);
    box-shadow: var(--dwm-shadow);
    padding: 1.1rem 1.25rem;
    margin-bottom: .75rem;
  }}
  .dwm-card-label {{
    font-size: .74rem; font-weight: 600; letter-spacing: .05em;
    text-transform: uppercase; color: var(--dwm-ink-soft);
    margin-bottom: .35rem;
  }}
  .dwm-card-value {{
    font-size: 1.9rem; font-weight: 600; letter-spacing: -.03em;
    line-height: 1.1; font-variant-numeric: tabular-nums;
  }}
  .dwm-card-unit {{ font-size: .8rem; color: var(--dwm-ink-soft); margin-top: .2rem; }}

  /* ---- outcome: the answer to a question, set as the page's hero ---- */
  .dwm-answer {{
    font-size: 1.65rem; font-weight: 600; letter-spacing: -.028em;
    line-height: 1.22; margin: .1rem 0 .6rem;
  }}
  .dwm-question {{
    font-size: 1.0rem; font-weight: 500; color: var(--dwm-ink-soft);
    letter-spacing: -.01em; margin-bottom: .2rem;
  }}
  .dwm-tag {{
    display: inline-block; font-size: .7rem; font-weight: 600;
    letter-spacing: .04em; text-transform: uppercase;
    padding: .16rem .5rem; border-radius: 999px; color: #fff;
    vertical-align: middle; margin-left: .5rem;
  }}

  /* ---- caveat: never optional, always close to the number ----------- */
  .dwm-caution {{
    font-size: .84rem; line-height: 1.5; color: var(--dwm-ink);
    background: #FFF8EC; border: 1px solid #FFE0B2;
    border-left: 3px solid var(--dwm-caution);
    border-radius: 12px; padding: .65rem .85rem; margin: .6rem 0;
  }}
  .dwm-source {{
    font-size: .74rem; color: var(--dwm-ink-soft);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}

  /* ---- evidence: supporting detail, visually recessed ---------------- */
  .dwm-evidence {{
    font-size: .92rem; line-height: 1.55; color: var(--dwm-ink-soft);
    border-left: 2px solid var(--dwm-hairline);
    padding-left: .85rem; margin: .5rem 0 .7rem;
  }}

  /* ---- hero strip at the top of the overview ------------------------ */
  .dwm-hero {{
    font-size: 2.4rem; font-weight: 600; letter-spacing: -.035em;
    line-height: 1.1; margin-bottom: .5rem;
  }}

  /* ---- metric tiles: strip Streamlit's own chrome ------------------- */
  [data-testid="stMetricValue"] {{ font-size: 1.7rem; letter-spacing: -.03em; }}
  [data-testid="stMetricLabel"] p {{
    font-size: .8rem; color: var(--dwm-ink-soft); font-weight: 500;
  }}
  [data-testid="stMetric"] {{
    background: var(--dwm-surface);
    border: 1px solid var(--dwm-hairline);
    border-radius: var(--dwm-radius);
    box-shadow: var(--dwm-shadow);
    padding: .9rem 1rem;
  }}
  [data-testid="stVerticalBlockBorderWrapper"] {{
    border-color: var(--dwm-hairline); border-radius: var(--dwm-radius);
  }}

  /* ---- dataframes read as tables, not as debug output ---------------- */
  [data-testid="stDataFrame"] {{
    border: 1px solid var(--dwm-hairline);
    border-radius: 14px; overflow: hidden; background: var(--dwm-surface);
  }}

  /* ---- buttons: pill, quiet ---------------------------------------- */
  .stButton > button, .stDownloadButton > button {{
    border-radius: 999px; border: 1px solid var(--dwm-hairline);
    background: var(--dwm-surface); color: var(--dwm-ink);
    font-weight: 500; font-size: .85rem;
    transition: all 150ms var(--dwm-ease);
  }}
  .stButton > button:hover, .stDownloadButton > button:hover {{
    border-color: var(--dwm-accent); color: var(--dwm-accent);
    box-shadow: 0 2px 10px rgba(0,113,227,.12);
  }}

  /* ---- tabs: underline, not boxes ----------------------------------- */
  .stTabs [data-baseweb="tab-list"] {{ gap: .35rem; border-bottom: 1px solid var(--dwm-hairline); }}
  .stTabs [data-baseweb="tab"] {{
    font-size: .88rem; font-weight: 500; color: var(--dwm-ink-soft);
    padding: .5rem .85rem;
  }}
  .stTabs [aria-selected="true"] {{ color: var(--dwm-accent); }}

  /* ---- altair charts: transparent, no default white slab ------------- */
  .stPlotlyChart, .stVegaLiteChart {{
    background: transparent !important;
  }}

  /* ---- expander: flat, quiet --------------------------------------- */
  [data-testid="stExpander"] {{
    border: 1px solid var(--dwm-hairline); border-radius: 14px;
    background: var(--dwm-surface);
  }}

  /* ---- divider: lighter than Streamlit's default --------------------- */
  hr {{ border-color: var(--dwm-hairline); margin: 1.4rem 0; }}

  /* ---- numerals line up in tables and tiles ------------------------- */
  [data-testid="stDataFrame"] td, .stMarkdown table td {{
    font-variant-numeric: tabular-nums;
  }}

  /* ---- footer ------------------------------------------------------- */
  .dwm-footer {{
    font-size: .76rem; color: var(--dwm-ink-soft); line-height: 1.6;
    border-top: 1px solid var(--dwm-hairline);
    padding-top: .9rem; margin-top: 2rem;
  }}
</style>
"""


# The marker the smoke test looks for. If a Streamlit upgrade changes the
# class names this CSS targets, the styling silently stops applying and the
# dashboard still runs, which is the worst possible failure: it looks fine in
# tests and wrong on screen. So the stylesheet carries a token, and a test
# asserts the token is present and that the selectors it depends on are the
# ones Streamlit is currently shipping.
STYLE_MARKER = "dwm-card"


def stylesheet() -> str:
    """The stylesheet, with a marker comment so its presence is assertable."""
    return f"<!-- dwm-style:{STYLE_MARKER} -->\n{css()}"


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------


def humanise(value: float | int | None) -> str:
    """Thousands-separated integer, or an explicit dash when absent.

    Handles None because a missing count and a zero count must not print the
    same thing.
    """
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def pct(value: float | None, places: int = 2) -> str:
    """A proportion as a percentage. Never renders None as 0%."""
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"


def signed(value: float | None, places: int = 4) -> str:
    return "n/a" if value is None else f"{value:+.{places}f}"


def render_metric(label: str, block: dict[str, Any], fmt=pct) -> dict[str, str]:
    """The three parts of a displayed figure, kept separate so they are testable.

    Returned rather than rendered so a test can assert the caution is never
    dropped, which is the whole reason this exists.
    """
    return {
        "label": label,
        "value": fmt(block.get("value")),
        "unit": block.get("unit") or "",
        "caution": block.get("caution") or "",
        "source": block.get("source") or "",
    }


def find_uncautoned(payload: Any) -> list[str]:
    """Every fact in a payload that has a unit but no caution.

    Used as a startup check on the whole API response rather than trusting that
    each call site remembered to render the caution. Returns the dotted paths
    that are missing one, so a failure names the section.
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
