"""Verification for the dashboard front end.

**These tests exist because the build had no way to see the page it was
producing.** Everything here checks something that is invisible in a passing
test suite and obvious on screen: a colour variable that was never defined, a
chart name that does not exist, a data path that silently renders "n/a", text
too faint to read.

That last class is the expensive one. A wrong key in a JavaScript template does
not raise — it renders `undefined`, or an em dash, or nothing. The page still
loads, the server still returns 200, and every other test still passes. Each of
those bugs shipped once during this build and was caught here rather than by a
reader.

One of them was not cosmetic. `build_outcomes` emitted its per-outcome caveat
under the key `caveat` while the rest of the project spells it `caution`, so
**every caution on the conclusions page silently rendered as absent** — on the
single page whose entire job is to state what may not be claimed. Nothing
raised. The only way it surfaced was asserting that each outcome carries one.

The four families:

* **Wiring** — every CSS variable is defined, every element id the JavaScript
  reaches for exists, every chart the JavaScript names is served.
* **Data paths** — every dotted path the front end reads exists in the real
  payload. Asserted against what mining actually produces, not a fixture,
  because the bug is a mismatch with reality.
* **Contrast** — WCAG AA for the text pairs in both themes.
* **Honesty** — no figure anywhere in the payload has a unit and no caution.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "dashboard" / "static"
CSS = STATIC / "app.css"
JS = STATIC / "app.js"
HTML = STATIC / "index.html"

FACTS = ROOT / "reports" / "facts.json"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _facts_from_warehouse():
    """The real payload, or skip.

    Some checks need the warehouse rather than the checked-in results, because
    they exercise the whole request path. The test session points
    `DWM_REPORTS_DIR` at a temporary directory, so these skip unless the
    warehouse has been built — with a reason that says what to run.
    """
    from dwm.api import store

    try:
        return store.load_facts()
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        pytest.skip(f"needs the built warehouse (`dwm mine`): {exc}")


needs_warehouse = pytest.mark.usefixtures("_noop")


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------


def test_static_files_exist() -> None:
    for path in (HTML, CSS, JS):
        assert path.is_file(), f"missing {path}"
    assert "<style" not in _text(HTML), "styles belong in app.css, not inline"


def test_every_css_variable_is_defined() -> None:
    """An undefined `var(--x)` is not an error. It renders nothing.

    The quietest possible defect: the stylesheet parses, the page loads, and one
    property silently does not apply. Devtools would show it immediately; a test
    suite has to be told to look.
    """
    css = _text(CSS)
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    missing = used - defined
    assert not missing, f"used but never defined: {sorted(missing)}"

    # Every core token must exist in both themes. Checked by name so a rename
    # that breaks a theme is caught rather than silently redefined once.
    core = {
        "canvas", "surface", "surface-2", "surface-sunk", "ink", "muted", "faint",
        "hairline", "hairline-firm", "accent", "accent-soft", "positive",
        "positive-soft", "caution", "caution-soft", "caution-edge", "negative",
    }
    names = {f"--{name}" for name in core}
    assert not (names - defined), f"missing core tokens: {sorted(names - defined)}"


def test_every_element_id_the_js_reaches_for_exists() -> None:
    """`$("#foo")` on an undeclared id returns null, and the failure surfaces
    on some unrelated-looking line rather than at the selector."""
    in_html = set(re.findall(r'id="([^"]+)"', _text(HTML)))
    # Ids the JavaScript creates when it renders a section, rather than declaring
    # them in the static markup. Listing them is the price of a client-rendered
    # view: this is the list a missing id has to be added to.
    runtime = {
        "explore-headlines", "ex-topic", "ex-limit", "ex-offset", "ex-go",
        "ex-csv", "ex-results",
        "explore-series", "sr-topic", "sr-go", "sr-csv", "sr-results",
        "ol-op", "ol-topic", "ol-year", "ol-run", "ol-results",
        "pipe-runs", "wh-tables", "how-tables",
        "report-body", "dl-report",
    }
    js = _text(JS)
    used = set(re.findall(r'\$\("#([a-zA-Z0-9_-]+)"\)', js))
    # Chart hosts are `chart-<name>` and `chart-<id>`, built at render time.
    used = {u for u in used if not u.startswith("chart-")}
    missing = used - in_html - runtime
    assert not missing, f"JavaScript reaches for ids not declared anywhere: {sorted(missing)}"


def test_every_chart_the_js_names_is_served() -> None:
    """A chart name with no matching spec renders the error box instead.

    That is deliberate — better than a blank rectangle — but it means a typo
    becomes a permanent error message on a live page, so the names are asserted
    against what the endpoint actually returns.
    """
    from dwm.ui.charts import build_charts

    facts = _facts_from_warehouse()
    served = set(build_charts(facts))

    named = set(re.findall(r'chart\(\s*"([a-z0-9_]+)"', _text(JS)))
    # `__series` is assembled in the browser for the browse view only. It has no
    # published figure behind it, so it has no spec on the server.
    named.discard("__series")

    missing = named - served
    assert not missing, f"the front end asks for charts that are not served: {sorted(missing)}"


def test_the_document_declares_a_theme_before_first_paint() -> None:
    """A flash of the wrong theme reads as a broken page.

    The script must be in `<head>` and before any body content, because anything
    later runs after something has already been painted.
    """
    html = _text(HTML)
    head, _, _ = html.partition("</head>")
    assert "dataset.theme" in head, "the theme script is not in <head>"
    assert "prefers-color-scheme" in head, "the OS preference is not consulted"
    assert 'data-theme="light"' in html[:300], "the root element declares no default theme"
    assert html.index("dataset.theme") < html.index("<body"), (
        "the theme script runs after the body, so the page paints once in the "
        "wrong theme first"
    )


def test_both_themes_define_the_same_tokens() -> None:
    """A token defined only for light means dark silently falls back to
    something the browser guesses. That is how a half-themed page happens."""
    css = _text(CSS)
    light = set(re.findall(r"(--[a-z0-9-]+)\s*:", _block(css, '[data-theme="light"]')))
    dark = set(re.findall(r"(--[a-z0-9-]+)\s*:", _block(css, '[data-theme="dark"]')))
    assert not (light - dark), f"defined for light but not dark: {sorted(light - dark)}"


# ---------------------------------------------------------------------------
# contrast
# ---------------------------------------------------------------------------


def _block(css: str, selector: str) -> str:
    """The body of one rule, brace-matched."""
    start = css.index(selector)
    body = css[css.index("{", start) + 1:]
    depth = 1
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return body[:i]
    return body


def _tokens(css: str, selector: str) -> dict[str, str]:
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", _block(css, selector)))


def _rgb(colour: str) -> tuple[int, int, int]:
    value = colour.strip()
    if value.startswith("#") and len(value) == 7:
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    match = re.match(r"rgba?\(([^)]+)\)", value)
    if match:
        return tuple(int(float(p)) for p in match.group(1).split(",")[:3])  # type: ignore[return-value]
    raise ValueError(f"cannot parse colour {colour!r}")


def _luminance(colour: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(colour)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# Text pairs that must be legible. The third value is the minimum ratio: 4.5 for
# body text, 3.0 for large or non-essential text such as axis labels.
CONTRAST_PAIRS = [
    ("ink on canvas", "--ink", "--canvas", 4.5),
    ("ink on surface", "--ink", "--surface", 4.5),
    ("ink on surface-2", "--ink", "--surface-2", 4.5),
    ("muted on surface", "--muted", "--surface", 4.5),
    ("muted on canvas", "--muted", "--canvas", 4.5),
    ("muted on surface-2", "--muted", "--surface-2", 4.5),
    ("faint on surface", "--faint", "--surface", 3.0),
    ("accent on surface", "--accent", "--surface", 4.5),
    ("accent on accent-soft", "--accent", "--accent-soft", 4.5),
    ("positive on surface", "--positive", "--surface", 4.5),
    ("positive on positive-soft", "--positive", "--positive-soft", 4.5),
    ("caution on surface", "--caution", "--surface", 3.0),
    ("caution on caution-soft", "--caution", "--caution-soft", 4.5),
]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_contrast_meets_wcag_aa(theme: str) -> None:
    """This is the check that would have caught black widgets on a light page.

    It cannot see a *framework* overriding a colour, but it can see a palette
    that was never built for the theme it claims to serve, which is how that
    failure started: a light canvas with dark widgets bolted on it.
    """
    tokens = _tokens(_text(CSS), f'[data-theme="{theme}"]')
    failures = []
    for label, fg, bg, minimum in CONTRAST_PAIRS:
        if fg not in tokens or bg not in tokens:
            failures.append(f"{label}: token missing in {theme}")
            continue
        ratio = _contrast(tokens[fg], tokens[bg])
        if ratio < minimum:
            failures.append(
                f"{label}: {ratio:.2f}:1 in {theme}, needs {minimum}:1 "
                f"({tokens[fg]} on {tokens[bg]})"
            )
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_callout_surfaces_are_distinguishable(theme: str) -> None:
    """A caution callout has to look like a caution.

    If its background matches the surface it is meant to interrupt, it stops
    functioning as an interruption and becomes decoration — which is the one
    job on this page that matters.
    """
    tokens = _tokens(_text(CSS), f'[data-theme="{theme}"]')
    for soft, surface, label in (
        ("--caution-soft", "--surface", "caution"),
        ("--positive-soft", "--surface", "positive"),
        ("--accent-soft", "--surface", "accent"),
    ):
        ratio = _contrast(tokens[soft], tokens[surface])
        assert ratio > 1.03, (
            f"{label} callout is indistinguishable from the surface in {theme} "
            f"(ratio {ratio:.3f})"
        )


def test_chart_palette_matches_the_css() -> None:
    """The chart specs duplicate the CSS palette, so keep them from drifting.

    A Vega-Lite spec is JSON built in Python and cannot read a stylesheet, so
    the values are repeated in `dwm/ui/charts.py`. Duplication is only
    defensible while something checks it: a chart drawn in yesterday's blue next
    to today's blue text is a small wrongness nobody can name.
    """
    from dwm.ui.charts import DARK, LIGHT

    css = _text(CSS)
    pairs = [
        ("light", LIGHT, [
            ("--accent", "accent"), ("--positive", "positive"),
            ("--caution", "caution"), ("--negative", "negative"),
            ("--muted", "muted"), ("--surface", "surface"),
            ("--canvas", "canvas"), ("--grid", "grid"), ("--axis", "axis"),
        ]),
        ("dark", DARK, [
            ("--accent", "accent"), ("--positive", "positive"),
            ("--caution", "caution"), ("--negative", "negative"),
            ("--muted", "muted"), ("--surface", "surface"),
            ("--canvas", "canvas"), ("--grid", "grid"), ("--axis", "axis"),
        ]),
    ]
    failures = []
    for theme_name, palette, mapping in pairs:
        tokens = _tokens(css, f'[data-theme="{theme_name}"]')
        for css_token, palette_key in mapping:
            if palette_key not in palette:
                failures.append(f"{theme_name}: charts.py has no {palette_key!r}")
                continue
            expected = tokens.get(css_token, "").strip().upper()
            actual = palette[palette_key].strip().upper()
            if expected != actual:
                failures.append(
                    f"{theme_name} {css_token}: CSS is {expected}, charts.py is {actual}"
                )
    assert not failures, "\n".join(failures)


def test_no_encoding_damage_in_the_front_end() -> None:
    """Encoding damage is invisible until someone reads the rendered page.

    A PowerShell round-trip double-encoded every non-ASCII character in the
    previous dashboard: a middle dot became two characters and four stray
    symbols appeared in the navigation labels. The app still ran and every other
    test still passed, because the damage is only visible in the output.
    """
    import re as _re

    bad = _re.compile("[\u00c3\u00c2\u00e2]")
    for path in sorted(STATIC.glob("*")) + [ROOT / "dwm" / "ui" / "charts.py"]:
        if path.suffix not in {".html", ".css", ".js", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert not bad.search(text), f"{path.name} contains mojibake"
        assert not text.startswith("\ufeff"), f"{path.name} starts with a BOM"


# ---------------------------------------------------------------------------
# data paths
# ---------------------------------------------------------------------------


def _resolve(payload: dict, path: str):
    node = payload
    for part in path.split("."):
        if isinstance(node, list):
            node = node[0] if node else None
        if not isinstance(node, dict) or part not in node:
            raise AssertionError(
                f"path {path!r} is missing at {part!r}; available: "
                f"{sorted(node) if isinstance(node, dict) else type(node).__name__}"
            )
        node = node[part]
    return node


MANIFEST_PATHS = [
    "title", "subtitle",
    "provenance.generated_at", "provenance.mining_run_id",
    "provenance.config_version", "provenance.source",
    "guards.passed", "guards.total", "guards.succeeded", "guards.failed",
    "corpus.headlines_in_window", "corpus.start", "corpus.end",
    "honesty_rules", "datasets",
]


@pytest.mark.parametrize("path", MANIFEST_PATHS)
def test_manifest_paths_exist(path: str) -> None:
    from dwm.api import store

    _facts_from_warehouse()  # skips with a reason if the warehouse is not built
    _resolve(store.build_manifest(), path)


FINDING_PATHS = {
    "rq2_bursts": ["per_year_cv", "counter_signal_note", "event_months"],
    "rq1_topic_mix": [
        "taxonomy_artefacts.raw_category", "taxonomy_artefacts.share_of_year",
        "taxonomy_artefacts.count",
        "window_shares.topics.share_of_window", "window_shares.topics.topic_group",
    ],
    "rq3_sensationalism": [
        "corpus_rate", "ranked.risk_signal_rate", "ranked.ci95_low", "ranked.ci95_high",
        "ranked.headline_count", "ranked.above_corpus_average",
        "trend_by_year.risk_signal_rate", "trend_by_year.headline_count",
        "sensitivity.rows.threshold", "sensitivity.rows.top1",
        "sensitivity.ranking_is_stable",
    ],
    "rq4_clusters": [
        "silhouette", "chosen_k", "k_candidates.silhouette",
        "clusters.cluster_id", "clusters.share_of_sample", "clusters.size",
        "clusters.top_terms", "k_note", "concentration_note",
    ],
    "rq5_association_rules": [
        "rule_count", "fpgrowth_speedup", "tautological_rules", "mean_items",
        "redundancy_note", "lift_caveat", "top_rules.antecedent",
        "top_rules.consequent", "top_rules.support", "top_rules.confidence",
        "top_rules.lift", "keyword_run.mean_items", "keyword_run.rule_count",
    ],
    "rq6_market_association": [
        "trading_days_paired",
        "measures.mean_sentiment.by_lag.lag_trading_days",
        "measures.mean_sentiment.by_lag.pearson_r",
        "measures.mean_sentiment.by_lag.p_value",
        "measures.mean_sentiment.by_lag.n",
        "measures.mean_sentiment.by_lag.significant_at_alpha",
        "volatility.strongest.pearson_r",
        "significance_accounting.tests_run", "significance_accounting.alpha",
        "significance_accounting.expected_false_positives",
        "significance_accounting.significant_results",
    ],
    "rq7_classifier": [
        "chosen_model", "metrics.accuracy", "metrics.majority_baseline_accuracy",
        "metrics.lift_over_baseline_pp", "metrics.fake_recall",
        "metrics.confusion_matrix.matrix", "metrics.confusion_matrix.labels",
        "metrics.confusion_matrix.reading", "models",
        "top_terms.toward_fake", "top_terms.toward_real", "upper_bound_caveat",
    ],
}


@pytest.mark.parametrize("section,path", [
    (section, path) for section, paths in FINDING_PATHS.items() for path in paths
])
def test_finding_paths_exist(section: str, path: str) -> None:
    """Asserted against `facts.json` itself, which is what the API serves.

    Four of these were wrong on the first pass — `taxonomy_artefacts` uses
    `raw_category` not `category`, the lag rows carry `significant_at_alpha` not
    `significant`, the returns correlation is on the fact header rather than
    under `max_abs_r`, and the per-model rows have no `baseline` — and every one
    rendered a blank or an "n/a" instead of raising.
    """
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    _resolve(facts[section], path)


# ---------------------------------------------------------------------------
# honesty
# ---------------------------------------------------------------------------


def test_every_outcome_carries_a_caution() -> None:
    """The rule the whole project rests on, checked on the synthesis too.

    `outcomes` is a derived block rather than a measurement, so it has no single
    fact header and its cautions are per-outcome instead — which means nothing
    else enforces their presence. They were emitted under the key `caveat` while
    the project spells it `caution`, so all seven silently rendered as absent on
    the one page whose job is stating what may not be claimed.
    """
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    outcomes = facts["outcomes"]["outcomes"]
    assert len(outcomes) == 7, f"expected seven outcomes, found {len(outcomes)}"
    for outcome in outcomes:
        assert outcome.get("caution"), f"{outcome.get('id')} has no caution"
        assert outcome.get("headline"), f"{outcome.get('id')} has no headline"
        assert outcome.get("question"), f"{outcome.get('id')} has no question"
        assert outcome.get("evidence"), f"{outcome.get('id')} has no evidence"
        assert outcome.get("kind") in {"null", "qualified", "positive", "split"}, (
            f"{outcome.get('id')} has an unknown kind {outcome.get('kind')!r}"
        )
    # A null result must survive the synthesis. Dropping it would make "we looked
    # and found nothing" indistinguishable from "we did not look".
    assert facts["outcomes"]["counts"]["null"] >= 1


def test_outcomes_use_the_project_wide_caveat_spelling() -> None:
    """Guards against the key drifting back to `caveat`."""
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    for outcome in facts["outcomes"]["outcomes"]:
        assert "caveat" not in outcome, (
            f"{outcome.get('id')} uses 'caveat'; the fact structure and the "
            "front end both read 'caution'"
        )


def test_no_figure_in_the_payload_lacks_a_caution() -> None:
    from dashboard.helpers import find_uncautoned

    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    problems = find_uncautoned(facts)
    assert not problems, f"figures with a unit but no caution: {problems[:8]}"


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------


def test_nominal_axes_are_sorted_by_their_own_labels() -> None:
    """A nominal axis with no explicit sort defaults to whatever order the data
    arrives in.

    The RQ2 event-month chart sorted its month axis by z-score, which put
    2020-05 beside 2016-12 and made an unordered comparison look chronological.
    Asserted on the built spec rather than trusting the source, so a new chart
    inherits the rule instead of the mistake.
    """
    from dwm.ui.charts import build_charts

    charts = build_charts(_facts_from_warehouse())
    offenders = []
    for name, spec in charts.items():
        if not spec:
            continue
        blob = json.dumps(spec)
        nominal = len(re.findall(r'"type":\s*"nominal"', blob))
        # A legend-only or tooltip-only nominal channel needs no sort, so this
        # is a ceiling rather than an equality.
        sorts = len(re.findall(r'"sort":\s*\[', blob))
        if nominal > sorts + 2:  # colour and tooltip channels are exempt
            offenders.append(f"{name}: {nominal} nominal channels, {sorts} sorted")
    assert not offenders, "possibly unsorted nominal axis(es):\n" + "\n".join(offenders)


def test_the_event_month_chart_is_in_date_order() -> None:
    """The specific regression, pinned rather than left to a general rule."""
    from dwm.ui.charts import build_charts

    spec = build_charts(_facts_from_warehouse())["rq2_event_z"]
    blob = json.dumps(spec)
    sorts = re.findall(r'"sort":\s*\[([^\]]*)\]', blob)
    assert sorts, "the month axis carries no explicit sort at all"
    months = re.findall(r'"(\d{4}-\d{2})"', sorts[0])
    assert months, f"no month labels found in the sort list: {sorts[0][:80]}"
    assert months == sorted(months), f"months are out of date order: {months}"
    # And the data order must match, or the default takes over.
    rows = json.loads(blob)
    def find_values(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "values":
                    return value
                found = find_values(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find_values(item)
                if found is not None:
                    return found
        return None
    values = find_values(rows) or []
    data_months = sorted({r["month"] for r in values if "month" in r})
    assert data_months == sorted(months), (
        f"the sort list and the data disagree: {data_months} vs {sorted(months)}"
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_chart_spec_declares_a_schema(theme: str) -> None:
    """A spec without `$schema` falls back to Vega-Lite 5 semantics."""
    from dwm.ui.charts import build_charts

    for name, spec in build_charts(_facts_from_warehouse(), theme_name=theme).items():
        if not spec:
            continue
        assert "$schema" in spec, f"{name} ({theme}) has no $schema"
        assert "v6" in spec["$schema"], f"{name} declares {spec['$schema']}"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_charts_are_serialisable_and_non_trivial(theme: str) -> None:
    """A spec that cannot be JSON-encoded cannot be embedded, and one with no
    mark draws nothing. Both are silent failures at page load."""
    from dwm.ui.charts import build_charts

    for name, spec in build_charts(_facts_from_warehouse(), theme_name=theme).items():
        if not spec:
            pytest.fail(f"{name} produced an empty spec in {theme}")
        blob = json.dumps(spec)
        assert len(blob) > 400, f"{name} is suspiciously small ({len(blob)} bytes)"
        assert '"mark"' in blob or '"layer"' in blob, f"{name} has no mark"


def test_the_volatility_scatter_reproduces_the_reported_correlation() -> None:
    """The plotted points must be the ones the reported r was computed on.

    An earlier version returned about 13,000 rows mixing every desk, which is a
    different quantity and would not reproduce the coefficient printed beside it.
    """
    from dwm.api import store
    from dwm.ui.charts import build_charts

    facts = _facts_from_warehouse()
    points = store.market_daily()["points"]
    spec = build_charts(facts, market_points=points)["rq6_volatility"]

    blob = json.dumps(spec)
    xs = [float(v) for v in re.findall(r'"x":\s*(-?\d+\.?\d*)', blob)]
    assert len(xs) >= 1000, f"expected the full daily series, found {len(xs)} points"

    ys = [float(v) for v in re.findall(r'"y":\s*(-?\d+\.?\d*)', blob)]
    n = min(len(xs), len(ys))
    a, b = xs[:n], ys[:n]
    mean_a, mean_b = sum(a) / n, sum(b) / n
    num = sum((p - mean_a) * (q - mean_b) for p, q in zip(a, b, strict=True))
    den = (sum((p - mean_a) ** 2 for p in a) * sum((q - mean_b) ** 2 for q in b)) ** 0.5
    recomputed = num / den

    reported = facts["rq6_market_association"]["volatility"]["strongest"]["pearson_r"]
    assert recomputed == pytest.approx(reported, abs=0.002)
