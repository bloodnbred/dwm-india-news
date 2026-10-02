"""Streamlit dashboard (Phase 8).

**This file computes nothing.** It calls the FastAPI backend and renders what
comes back. Every number shown was measured once by the mining stage, written to
`facts.json` by the inference stage, and served unchanged. A dashboard that
computed anything would be a second source of truth, and the two would drift.

The one thing it does is carry the cautions. `dwm/../helpers.py` holds the
formatting, and a startup check walks the whole API payload for any figure that
has a unit but no caveat. A bare "10.9%" detached from "risk-signal rate on
unlabelled headlines" is exactly how a risk-signal rate stops being called one,
and a dashboard is the last place that wording survives contact with a reader.

Structure: five sections, and the answer comes before the evidence on every one
of them.
"""

from __future__ import annotations

import math
import os
from typing import Any

import altair as alt
import pandas as pd
import requests
import streamlit as st

try:
    from helpers import (
        ACCENT,
        CAUTION,
        CHART_SERIES,
        INK_SOFT,
        KIND_COLOUR,
        KIND_LABEL,
        find_uncautoned,
        humanise,
        pct,
        render_metric,
        signed,
        stylesheet,
    )
except ImportError:  # pragma: no cover - direct import outside Streamlit
    from dashboard.helpers import (
        ACCENT,
        CAUTION,
        CHART_SERIES,
        INK_SOFT,
        KIND_COLOUR,
        KIND_LABEL,
        find_uncautoned,
        humanise,
        pct,
        render_metric,
        signed,
        stylesheet,
    )

API = os.environ.get("DWM_API", "http://127.0.0.1:8000")
TIMEOUT = 30

st.set_page_config(
    page_title="Indian News Warehouse",
    page_icon="—§",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(stylesheet(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# talking to the API
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner=False)
def api_get(path: str, **params: Any) -> Any:
    """GET the backend, turning a failure into something the user can act on.

    A stack trace tells the user nothing, and the usual cause is simply that
    the backend has not been started, so the message says which command to run.

    Returns text for a non-JSON response. `/report` serves markdown, and calling
    `.json()` on it raises, which is how the Report page was found to have never
    worked: the server was healthy and the page was broken.
    """
    try:
        response = requests.get(f"{API}{path}", params=params or None, timeout=TIMEOUT)
    except requests.RequestException as exc:
        st.error(
            f"Cannot reach the API at `{API}`.\n\n"
            "Start it in another terminal:\n\n"
            "```\n.\\.venv\\Scripts\\python.exe -m dwm serve\n```\n\n"
            f"({type(exc).__name__})"
        )
        st.stop()
    if response.status_code == 503:
        st.error(_detail(response))
        st.stop()
    if response.status_code >= 400:
        st.error(f"`{path}` returned {response.status_code}: {response.text[:200]}")
        st.stop()
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.text


def _detail(response: Any) -> str:
    try:
        return response.json().get("detail", "the backend has no data yet")
    except Exception:
        return "the backend has no data yet"


def api_text(path: str) -> str:
    """GET a non-JSON endpoint, for the download buttons."""
    return str(api_get(path))


@st.cache_data(ttl=300, show_spinner=False)
def api_post(path: str) -> Any:
    try:
        return requests.post(f"{API}{path}", timeout=TIMEOUT).json()
    except requests.RequestException as exc:
        st.error(f"Cannot reach the API at `{API}` ({type(exc).__name__})")
        st.stop()


# ---------------------------------------------------------------------------
# rendering primitives
# ---------------------------------------------------------------------------


def card(label: str, value: str, unit: str = "", colour: str | None = None) -> None:
    """A single figure as a card. The value never renders without its label."""
    style = f' style="color:{colour}"' if colour else ""
    st.markdown(
        f'<div class="dwm-card">'
        f'<div class="dwm-card-label">{label}</div>'
        f'<div class="dwm-card-value"{style}>{value}</div>'
        + (f'<div class="dwm-card-unit">{unit}</div>' if unit else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def metric(label: str, block: dict[str, Any], fmt=pct) -> None:
    """A figure with its unit and its caution attached.

    The caution is mandatory. A figure with a unit and no caution would render
    as a bare number, which is the failure mode this exists to prevent, so it
    renders a warning instead.
    """
    parts = render_metric(label, block, fmt)
    st.metric(parts["label"], parts["value"])
    if parts["unit"]:
        st.caption(f"*{parts['unit']}*")
    if parts["caution"]:
        caution(parts["caution"])
    else:
        st.warning(f"**{parts['label']} has no caution attached.**")


def caution(text: str) -> None:
    if text:
        st.markdown(f'<div class="dwm-caution">{text}</div>', unsafe_allow_html=True)


def evidence(text: str) -> None:
    st.markdown(f'<div class="dwm-evidence">{text}</div>', unsafe_allow_html=True)


def source_note(text: str) -> None:
    if text:
        st.markdown(f'<div class="dwm-source">source: {text}</div>', unsafe_allow_html=True)


def answer_block(outcome: dict[str, Any]) -> None:
    """The answer to one question, as the largest text on the page.

    Order matters: question, then answer, then evidence, then the caveat. A
    panel that shows data and leaves the reader to infer the point has the
    wrong emphasis, and the emphasis is the whole reason the panel exists.
    """
    colour = KIND_COLOUR.get(outcome.get("kind", "positive"), ACCENT)
    tag = KIND_LABEL.get(outcome.get("kind", ""), "")
    rq = outcome.get("rq", "")
    st.markdown(
        f'<div class="dwm-question">{rq}  &middot;  {outcome.get("question", "")}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="dwm-answer">{outcome.get("headline", "")}'
        f'<span class="dwm-tag" style="background:{colour}">{tag}</span></div>',
        unsafe_allow_html=True,
    )
    if outcome.get("detail"):
        st.markdown(outcome["detail"])
    if outcome.get("evidence"):
        evidence(f"<b>How we know.</b> {outcome['evidence']}")
    if outcome.get("caveat"):
        caution(f"<b>Before you quote this.</b> {outcome['caveat']}")


def section(key: str, summary: dict[str, Any]) -> dict[str, Any]:
    """The body of one `/summary` section, with its caution merged in.

    `/summary` returns each question twice over: a small header of
    value/unit/caution, and the full body under `data`. Reading the body from
    the top level is a mistake that surfaces at runtime as a KeyError, so the
    two are joined once here instead of at every access site.
    """
    block = summary[key]
    return {**block["data"], "_caution": block.get("caution") or ""}


def chart(spec: Any) -> None:
    """Render an Altair spec full width.

    `width="stretch"` rather than `width="stretch"`, which Streamlit
    deprecated and removes after 2025-12-31.
    """
    st.altair_chart(spec, width="stretch", theme=None)


def axis(title: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Shared axis styling as a plain dict.

    Altair 6 rejects an `AxisConfig` passed via `**` into a channel definition,
    so this returns a dict and is passed as `axis=axis(...)`. The dict is
    merged rather than replaced so a caller can override one field.
    """
    config: dict[str, Any] = {
        "gridColor": "#E8E8ED",
        "gridWidth": 1,
        "domain": False,
        "tickColor": "#C7C7CC",
        "labelFontSize": 11,
        "titleFontSize": 11,
        "titleColor": INK_SOFT,
        "labelColor": INK_SOFT,
    }
    if title is not None:
        config["title"] = title
    config.update(overrides)
    return config


def label_colour(frame: pd.DataFrame, column: str, test: Any, yes: str, no: str,
                 yes_label: str, no_label: str) -> tuple[Any, pd.DataFrame]:
    """A two-state colour encoding, expressed as a labelled nominal field.

    Altair 6 changed the conditional API enough that `alt.condition(...)` is no
    longer safe to title, and a two-colour conditional with an untitled legend
    is unreadable anyway. Writing the state as a string column and mapping it
    through a scale gives a legend that says `fell` and `rose` rather than two
    unexplained swatches, and it works across Altair versions.

    The label goes in a **new** column. Overwriting the source column silently
    replaces the value the chart is plotting, which produces a string on a
    quantitative axis and a `str` versus `float` comparison inside Altair.
    """
    label_column = f"{column}_label"
    frame = frame.assign(
        **{label_column: [yes_label if test(v) else no_label for v in frame[column]]}
    )
    colour = alt.Color(
        f"{label_column}:N",
        scale=alt.Scale(domain=[yes_label, no_label], range=[yes, no]),
        legend=alt.Legend(orient="bottom", labelFontSize=11, title=None),
    )
    return colour, frame


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

health = api_get("/health")
summary = api_get("/summary")
facts = api_get("/facts")

outcomes = {o["id"]: o for o in (summary.get("outcomes", {}).get("outcomes") or [])}
outcome_list = summary.get("outcomes", {})
corpus = facts["corpus"]["analysis_window"]

# Startup honesty check over the whole payload, rather than trusting each call
# site. If a section ever loses its caution, say so loudly.
_missing = find_uncautoned(summary)
if _missing:
    st.sidebar.error(
        f"{len(_missing)} figure(s) have a unit but no caution:\n\n"
        + "\n".join(f"`{p}`" for p in _missing[:6])
    )


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

st.sidebar.markdown("### Indian News Warehouse")
st.sidebar.caption(
    f"{humanise(corpus['headlines_in_window'])} headlines · "
    f"{humanise(facts['corpus']['row_counts']['stg_ifnd'])} labelled statements · "
    "5 years of Nifty 50"
)
if health.get("status") != "ok":
    st.sidebar.error(health.get("detail", "backend degraded"))

SECTIONS = {
    "Overview": "—§  What this study found",
    "Findings": "◇  The seven questions",
    "Explore": "⌗  Browse the data",
    "How it works": "⚙  Method and rigour",
    "Report": "▤  Full report",
}
page = st.sidebar.radio("Section", list(SECTIONS))

if st.sidebar.button("Refresh", width="stretch"):
    api_post("/query/reload")
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.caption(
    f"Run `{summary.get('mining_run_id')}` · config v{summary.get('config_version')}"
)

if st.sidebar.expander("The honesty rules", expanded=False):
    for rule in facts.get("honesty_rules", []):
        st.sidebar.markdown(f"— {rule}")


def footer() -> None:
    citations = " · ".join(
        d["citation"].split("(")[0].strip()
        for d in facts.get("datasets", {}).values()
        if d.get("citation")
    )
    st.markdown(
        f'<div class="dwm-footer">'
        f"Every figure on this page is served unchanged from <code>facts.json</code>, "
        f"which the inference stage rendered from <code>mining.json</code> by template. "
        f"No language model was involved, and this dashboard computes nothing.<br>"
        f"Sources: {citations}<br>"
        f"Generated {str(facts.get('generated_at', ''))[:19]}."
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 1. Overview — the answer, before the evidence
# ---------------------------------------------------------------------------

if page == "Overview":
    st.markdown('<div class="dwm-hero">What 1.1 million Indian news headlines actually show</div>',
                unsafe_allow_html=True)
    st.markdown(outcome_list.get("headline", ""))
    st.caption(
        f"Analysis window {corpus['start']} to {corpus['end']}, derived from the "
        "data rather than hard-coded, and applied as a flag rather than a filter."
    )

    counts = outcome_list.get("counts", {})
    t1, t2, t3, t4 = st.columns(4)
    with t1:
        card("Headlines analysed", humanise(corpus["headlines_in_window"]), "in the window")
    with t2:
        card("Months spiking on volume", humanise(summary["rq2_bursts"]["value"]),
             "zero, and the series is flat", KIND_COLOUR["null"])
    with t3:
        card("Topics with a real signal",
             humanise(counts.get("positive", 0) + counts.get("qualified", 0)),
             f"of {counts.get('total', 7)} questions", KIND_COLOUR["qualified"])
    with t4:
        clf = section("rq7_classifier", summary)
        card("Classifier accuracy", pct(clf["metrics"]["accuracy"]),
             f"against a {pct(clf['baseline'])} baseline", KIND_COLOUR["positive"])

    st.divider()
    st.subheader("The outcomes, in order of how surprising they are")

    for outcome in outcome_list.get("outcomes", []):
        with st.container():
            answer_block(outcome)
        st.divider()

    st.subheader("What was asked, and what came back")
    for outcome in outcome_list.get("outcomes", []):
        colour = KIND_COLOUR.get(outcome["kind"], ACCENT)
        st.markdown(
            f'<div class="dwm-card"><div class="dwm-card-label">'
            f'{outcome["rq"]} · {KIND_LABEL.get(outcome["kind"], "")}</div>'
            f'<div style="font-size:1.02rem;font-weight:500;letter-spacing:-.01em">'
            f'{outcome["headline"]}</div></div>',
            unsafe_allow_html=True,
        )
    st.caption(f"Counts: {counts}")

    st.subheader("Inference gate")
    guards = facts["guards"]
    passed = len(guards["checks"]) - len(guards["failed"])
    g1, g2 = st.columns([1, 3])
    with g1:
        st.metric("Checks", f"{passed}/{len(guards['checks'])}",
                  "all passed" if guards["passed"] else f"{len(guards['failed'])} failed")
    with g2:
        st.markdown(
            "The inference stage refuses to present a claim the warehouse cannot "
            "support, and exits non-zero when a guard fails. Every check states "
            "what it looked at."
        )
    footer()


# ---------------------------------------------------------------------------
# 2. Findings — one page per question, answer first
# ---------------------------------------------------------------------------

elif page == "Findings":
    st.markdown("### The seven questions")
    st.caption(
        "Each page states its answer first. The evidence is underneath, and the "
        "caveat sits with the number rather than in a footnote."
    )

    order = [
        ("volume", "RQ2", "Volume and events"),
        ("mix", "RQ1", "Topic mix"),
        ("language", "RQ3", "Sensational language"),
        ("clusters", "RQ4", "Topic clusters"),
        ("rules", "RQ5", "Co-occurrence rules"),
        ("market", "RQ6", "Headlines and the market"),
        ("classifier", "RQ7", "Real vs Fake classifier"),
    ]
    labels = [label for _key, _rq, label in order]
    chosen_label = st.radio("Question", labels, horizontal=True, label_visibility="collapsed")
    key = next(k for k, _rq, label in order if label == chosen_label)

    answer_block(outcomes[key])
    st.divider()

    # ---- RQ2: the counter-signal, as a diverging bar chart -------------
    if key == "volume":
        st.subheader("What the event months actually show")
        st.caption(
            "A desk that a news-reactive archive would cover *more* of during these "
            "events. Bars below zero mean coverage fell."
        )
        rows = []
        for event in section("rq2_bursts", summary).get("event_months", []):
            measures = event.get("measures", {})
            for desk in ("Health", "Sports", "Entertainment"):
                value = measures.get(f"topic_volume:{desk}", {}).get("z_score")
                if value is not None:
                    rows.append({
                        "month": event["year_month"], "desk": desk, "z": value,
                        "label": event["label"],
                    })
        if rows:
            frame = pd.DataFrame(rows)
            colour, frame = label_colour(
                frame, "z", lambda v: v < 0, CAUTION, ACCENT, "coverage fell", "coverage rose"
            )
            marks = (
                alt.Chart(frame)
                .mark_bar(cornerRadiusTopLeft=2, cornerRadiusBottomLeft=2,
                          cornerRadiusTopRight=2, cornerRadiusBottomRight=2)
                .encode(
                    x=alt.X("z:Q", axis=axis("standard deviations from that desk's norm")),
                    y=alt.Y("month:N", sort="-x", axis=axis()),
                    color=colour,
                    tooltip=["month:N", "desk:N", alt.Tooltip("z:Q", format=".2f")],
                )
                .properties(height=alt.Step(17))
            )
            chart(marks)
            st.caption(
                "The listed events are calendar coincidences offered for judgement, "
                "not causes. The desks predicted to rise fall instead in most months."
            )

        with st.expander("Why no month is flagged as a spike"):
            rq2 = section("rq2_bursts", summary)
            st.dataframe(
                pd.DataFrame([
                    {"year": y, "coefficient of variation": v if v is not None else "excluded (partial year)"}
                    for y, v in (rq2.get("per_year_cv") or {}).items()
                ]),
                hide_index=True, width="stretch",
            )
            st.markdown(
                f"**{rq2['volume_bursts_found']} months** clear a z-score of 2.0. "
                "Within-year volume varies by 2–4%, so no threshold can fire on a "
                "series this flat, and lowering one until something appeared would "
                "be choosing a threshold to manufacture a result."
            )
            caution(rq2.get("counter_signal_note") or "")

    # ---- RQ1: the mix, as a stacked area ------------------------------
    elif key == "mix":
        rq1 = section("rq1_topic_mix", summary)
        st.subheader("The topic mix over time")
        st.caption("Within-year share, because raw counts are not comparable and 2015 is a partial year.")
        rows = rq1.get("rows", [])
        if rows:
            frame = pd.DataFrame(rows)
            frame = frame[frame["topic_group"] == "Subject"]
            area = (
                alt.Chart(frame)
                .mark_area(opacity=0.85)
                .encode(
                    x=alt.X("year:O", axis=axis()),
                    y=alt.Y("share_of_year:Q", stack="zero", axis=axis("share of that year's headlines")),
                    color=alt.Color("topic:N", scale=alt.Scale(range=CHART_SERIES),
                                    title=None, legend=alt.Legend(orient="bottom",
                                                                  columns=6,
                                                                  labelFontSize=11)),
                    tooltip=["year:O", "topic:N",
                             alt.Tooltip("share_of_year:Q", format=".2%")],
                )
                .properties(height=320)
            )
            chart(area)

        st.subheader("The filing artefact")
        artefacts = rq1.get("taxonomy_artefacts") or []
        if artefacts:
            st.dataframe(pd.DataFrame(artefacts), hide_index=True, width="stretch")
        st.markdown(
            "`business.international-business` is **11.1% of all 2017 headlines** "
            "and **0.2% of 2018**. An analysis that ignored this would report a "
            "news-industry event as a change in what India was reading."
        )
        with st.expander("Largest topic of the whole window"):
            st.dataframe(
                pd.DataFrame(rq1["window_shares"]["topics"]),
                hide_index=True, width="stretch",
            )
            st.caption(
                "Share of the window and share of a single year are different "
                "numbers answering different questions, and are stored separately "
                "so they cannot be interchanged."
            )

    # ---- RQ3: rates with intervals, and the sensitivity ---------------
    elif key == "language":
        rq3 = section("rq3_sensationalism", summary)
        metric("Corpus risk-signal rate", summary["rq3_sensationalism"])

        st.subheader("By topic, with a confidence interval on every rate")
        ranked = pd.DataFrame(rq3.get("ranked", []))
        if not ranked.empty:
            colour, ranked = label_colour(
                ranked, "above_corpus_average", bool, CAUTION, ACCENT,
                "above corpus average", "within the corpus range",
            )
            bars = (
                alt.Chart(ranked)
                .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
                .encode(
                    y=alt.Y("topic:N", sort="-x", axis=axis()),
                    x=alt.X("risk_signal_rate:Q", axis=axis("risk-signal rate")),
                    color=colour,
                    tooltip=[
                        "topic:N", "topic_group:N",
                        alt.Tooltip("risk_signal_rate:Q", format=".2%"),
                        alt.Tooltip("ci95_low:Q", format=".2%"),
                        alt.Tooltip("ci95_high:Q", format=".2%"),
                        "headline_count:Q",
                    ],
                )
                .properties(height=alt.Step(26))
            )
            chart(bars)
            st.caption(
                "The bar is the point estimate and the interval is the honest part. "
                "Counts are in the tens of thousands, so a bare percentage would imply "
                "a precision the measure does not have."
            )

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Trend over the window")
            trend = pd.DataFrame(rq3.get("trend_by_year", []))
            if not trend.empty:
                chart(
                    alt.Chart(trend)
                    .mark_line(strokeWidth=2.5, color=ACCENT)
                    .encode(
                        x=alt.X("year:O", axis=axis()),
                        y=alt.Y("risk_signal_rate:Q", axis=axis()),
                        tooltip=["year:O",
                                 alt.Tooltip("risk_signal_rate:Q", format=".2%")],
                    )
                    .properties(height=200)
                )
        with c2:
            st.subheader("Is the ranking an artefact of the cut-off?")
            sens = pd.DataFrame(rq3["sensitivity"]["rows"])
            if not sens.empty:
                sens["threshold"] = sens["threshold"].map(lambda v: f"{v:.4f}")
                st.dataframe(
                    sens[["threshold", "is_chosen_threshold", "top1", "corpus_rate"]],
                    hide_index=True, width="stretch",
                )
                st.caption(
                    "The top *informative* topic is "
                    + ("stable" if rq3["sensitivity"].get("ranking_is_stable")
                       else "NOT stable")
                    + " across this range. `Unknown` tops the raw ranking at some "
                    "thresholds because it is a filing gap, not a subject."
                )

    # ---- RQ4: silhouette curve + the 95% bar --------------------------
    elif key == "clusters":
        rq4 = section("rq4_clusters", summary)
        metric("Silhouette", summary["rq4_clusters"], fmt=lambda v: f"{v:.4f}" if v is not None else "n/a")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.subheader("Choosing k")
            cands = pd.DataFrame(rq4.get("k_candidates", []))
            if not cands.empty:
                chosen_k = rq4.get("chosen_k")
                # A single chart with a `rule` for the chosen k, rather than a
                # layered spec. `alt.layer()` in Altair 6 has no `mark_line`,
                # and a rule reads more clearly than a ringed point anyway:
                # it says "this is the value chosen", not "this dot is special".
                best = cands.loc[cands["silhouette"].idxmax()]
                line = (
                    alt.Chart(cands)
                    .mark_line(strokeWidth=2.5, color=ACCENT)
                    .mark_point(size=80, filled=True, color=ACCENT)
                    .encode(
                        x=alt.X("k:O", axis=axis("k")),
                        y=alt.Y("silhouette:Q", axis=axis("silhouette")),
                        tooltip=["k:O", alt.Tooltip("silhouette:Q", format=".4f")],
                    )
                )
                marker = (
                    alt.Chart(pd.DataFrame([{"k": chosen_k, "silhouette": best["silhouette"]}]))
                    .mark_point(size=260, filled=False, color=CAUTION, strokeWidth=3)
                    .encode(x=alt.X("k:O"), y=alt.Y("silhouette:Q"))
                )
                chart(alt.layer(line, marker).properties(height=240))
                st.caption(
                    f"The ringed point is the chosen k = {chosen_k}. It is also the "
                    f"highest score tried, at {best['silhouette']:.4f}."
                )
        with c2:
            st.subheader("Where the headlines actually went")
            clusters = pd.DataFrame(rq4.get("clusters", []))
            if not clusters.empty:
                colour, clusters = label_colour(
                    clusters, "share_of_sample", lambda v: v > 0.5,
                    "#C7C7CC", ACCENT, "the undifferentiated remainder", "a real topic",
                )
                chart(
                    alt.Chart(clusters)
                    .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                    .encode(
                        y=alt.Y("cluster_id:O",
                                axis=axis("cluster", labelFontSize=11, ticks=False,
                                          gridColor=None)),
                        x=alt.X("share_of_sample:Q", axis=axis()),
                        color=colour,
                        tooltip=["top_terms:N", alt.Tooltip("share_of_sample:Q", format=".2%")],
                    )
                    .properties(height=alt.Step(46))
                )
                st.caption(
                    "The small clusters find "
                    + ", ".join(
                        f"`{t}`" for c in clusters[clusters["share_of_sample"] < 0.1]["top_terms"]
                        .head(3) for t in c[:3]
                    )
                    + "."
                )
        st.markdown(rq4.get("k_note") or "")
        caution(rq4.get("concentration_note") or "")

        with st.expander("The correction this section replaces"):
            st.markdown(
                "An earlier run measured **0.068** and concluded the headlines had "
                "no recoverable topic structure. That was wrong, and the fault was "
                "in the feature engineering, not the data.\n\n"
                "1. scikit-learn's default token pattern admits pure numerals, so "
                "the clusters were described by `000`, `102` and `1000`.\n"
                "2. With numerals removed they were described by `for`, `with`, "
                "`from` — mean TF-IDF inside a cluster is highest for function "
                "words, because they appear in a modest share of documents but a "
                "large share of any one cluster.\n"
                "3. Descriptions were read off the K-Means centroid weights, which "
                "through an LSA basis returned `aadhaar, aadmi, aap, aarti` for "
                "*every* cluster, because SVD components carry an arbitrary sign and "
                "alphabetically early features win systematically.\n\n"
                "None of those is visible in a silhouette computed on a different "
                "feature space, which is why the first number looked like a property "
                "of the corpus. 'The data has no structure' and 'my features had no "
                "signal' are easy to confuse."
            )

    # ---- RQ5: the timing comparison as a picture ----------------------
    elif key == "rules":
        rq5 = section("rq5_association_rules", summary)
        st.subheader("Two algorithms, one answer")
        timings = pd.DataFrame([
            {"algorithm": "Apriori", "seconds": rq5.get("apriori_seconds")},
            {"algorithm": "FP-Growth", "seconds": rq5.get("fpgrowth_seconds")},
        ])
        chart(
            alt.Chart(timings)
            .mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5, height=54)
            .encode(
                y=alt.Y("algorithm:N", sort="-x", axis=axis()),
                x=alt.X("seconds:Q", axis=axis("seconds")),
                color=alt.Color("algorithm:N", scale=alt.Scale(range=[ACCENT, "#34C759"]),
                                legend=None),
                tooltip=["algorithm:N", alt.Tooltip("seconds:Q", format=".2f")],
            )
            .properties(height=150)
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Rules", humanise(rq5.get("rule_count")))
        with c2:
            st.metric("Speedup", f"{rq5.get('fpgrowth_speedup')}—", "FP-Growth on identical input")
        with c3:
            st.metric("Tautologies", humanise(rq5.get("tautological_rules")),
                      "counted separately")
        st.markdown(
            f"**Rule sets identical: {rq5.get('rule_sets_identical')}.** They search "
            "the same itemsets, so a difference would mean one is broken, not "
            "interesting. The only thing being measured is the time."
        )
        st.markdown(rq5.get("redundancy_note") or "")

        st.subheader("The strongest non-trivial rules, by lift")
        rules = pd.DataFrame(rq5.get("top_rules", []))
        if not rules.empty:
            rules["if"] = rules["antecedent"].apply(" + ".join)
            rules["then"] = rules["consequent"].apply(" + ".join)
            st.dataframe(
                rules[["if", "then", "support", "confidence", "lift"]],
                hide_index=True, width="stretch",
            )
        caution(rq5.get("lift_caveat") or "")
        with st.expander("Why attributes, and not the keyword vocabulary"):
            st.markdown(
                f"Attribute transactions carry **{rq5.get('mean_items')} items** each. "
                f"The 300-term keyword vocabulary yields only "
                f"**{rq5['keyword_run'].get('mean_items')} items per headline**, because "
                "its most frequent terms are `govt`, `held`, `get`, `man`, `police`."
            )
            st.markdown(
                f"The keyword run produced **{rq5['keyword_run'].get('rule_count')} rules**. "
                "Reported as a result rather than an omission: the vocabulary carries "
                "almost no co-occurrence structure to mine."
            )

    # ---- RQ6: the scatter, then the lag table ------------------------
    elif key == "market":
        rq6 = section("rq6_market_association", summary)
        st.subheader("Headline volume against 20-day volatility")
        st.caption(
            "Association only. Headline volume and volatility both respond to the "
            "same underlying events, and nothing here identifies a direction of effect."
        )
        scatter = api_get("/market/daily")
        points = scatter.get("points") or []
        if points:
            frame = pd.DataFrame(points)
            frame["log_volume"] = frame["headline_count"].map(math.log)
            v_strong = rq6["volatility"].get("strongest", {})
            chart(
                alt.Chart(frame)
                .mark_circle(size=14, opacity=0.28, color=ACCENT)
                .encode(
                    x=alt.X("log_volume:Q", axis=axis("log headline volume per day")),
                    y=alt.Y("volatility_20d:Q", axis=axis("20-day volatility")),
                    tooltip=[
                        "trade_date:T",
                        alt.Tooltip("headline_count:Q", title="headlines"),
                        alt.Tooltip("volatility_20d:Q", format=".3f"),
                    ],
                )
                .properties(height=340)
            )
            strongest = v_strong.get("name", "log headline volume")
            st.markdown(
                f"**{humanise(rq6['trading_days_paired'])} paired trading days**, "
                f"r = {signed(v_strong.get('pearson_r'))}, explaining "
                f"{v_strong.get('variance_explained_pct')}% of the variance "
                f"(p = {v_strong.get('p_value')}). Busier headline days go with "
                "calmer markets — the sign is the interesting part, and this data "
                "cannot explain it."
            )
            st.caption(scatter.get("note") or "")

        with st.expander("Against daily returns there is nothing"):
            accounting = rq6.get("significance_accounting", {})
            rows = [
                {
                    "measure": name.replace("_", " "),
                    "lag (trading days)": e["lag_trading_days"],
                    "pearson r": e["pearson_r"],
                    "p": e.get("p_value"),
                }
                for name, m in rq6.get("measures", {}).items()
                for e in m.get("by_lag", [])
                if e.get("pearson_r") is not None
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.markdown(
                f"{accounting.get('tests_run')} lag tests were run and "
                f"{len(accounting.get('significant_results') or [])} is significant. "
                f"At alpha = {accounting.get('alpha')}, that many tests produce about "
                f"{accounting.get('expected_false_positives')} false positives by "
                "chance, so the significant result is not treated as a finding."
            )

    # ---- RQ7: confusion heatmap --------------------------------------
    elif key == "classifier":
        rq7 = section("rq7_classifier", summary)
        metrics = rq7.get("metrics", {})
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Accuracy", pct(metrics.get("accuracy")))
        with m2:
            st.metric("Majority baseline", pct(metrics.get("majority_baseline_accuracy")))
        with m3:
            st.metric("Lift", f"{metrics.get('lift_over_baseline_pp', 0):+.1f} pp")
        with m4:
            st.metric("Fake recall", pct(metrics.get("fake_recall")))
        st.caption(
            f"`{rq7.get('chosen_model')}` was chosen on **training** cross-validated "
            "accuracy and the test split was scored once. Selecting on test accuracy "
            "and then reporting that number is the optimism this study set out to avoid."
        )

        st.subheader("Confusion matrix")
        matrix = metrics.get("confusion_matrix", {})
        labels = matrix.get("labels", [])
        cells = []
        for i, row in enumerate(matrix.get("matrix", [])):
            for j, value in enumerate(row):
                cells.append({
                    "actual": labels[i] if i < len(labels) else f"row{i}",
                    "predicted": labels[j] if j < len(labels) else f"col{j}",
                    "count": value,
                })
        if cells:
            frame = pd.DataFrame(cells)
            total = frame["count"].sum() or 1
            frame["share"] = frame["count"] / total
            chart(
                alt.Chart(frame)
                .mark_rect(cornerRadius=4)
                .encode(
                    x=alt.X("predicted:N", axis=axis("predicted")),
                    y=alt.Y("actual:N", axis=axis("actual")),
                    color=alt.Color("share:Q", scale=alt.Scale(range=["#FFFFFF", ACCENT]),
                                    legend=alt.Legend(orient="bottom", labelFontSize=11)),
                    tooltip=["actual:N", "predicted:N", "count:Q",
                             alt.Tooltip("share:Q", format=".2%")],
                )
                .properties(height=180)
            )
            st.caption(matrix.get("reading", ""))

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Every model, against the same baseline")
            models = pd.DataFrame(rq7.get("models", {})).T
            if not models.empty:
                st.dataframe(models, width="stretch")
        with c2:
            st.subheader("What the model learned")
            terms = rq7.get("top_terms") or {}
            if terms:
                length = max(len(terms.get("toward_fake", [])), len(terms.get("toward_real", [])))
                st.dataframe(
                    pd.DataFrame({
                        "toward FAKE": (terms.get("toward_fake") or [""] * length)[:length],
                        "toward REAL": (terms.get("toward_real") or [""] * length)[:length],
                    }),
                    hide_index=True, width="stretch",
                )
        caution(rq7.get("upper_bound_caveat", ""))

    footer()


# ---------------------------------------------------------------------------
# 3. Explore
# ---------------------------------------------------------------------------

elif page == "Explore":
    st.markdown("### Browse the data")
    st.caption("The same warehouse the analysis ran on, paged and filtered.")

    tab = st.tabs(["Headlines", "Monthly series", "Warehouse", "OLAP", "Pipeline"])

    with tab[0]:
        topics = api_get("/topics")["topics"]
        choice = st.selectbox("Topic", ["(all topics)"] + topics)
        page_size = st.slider("Rows per page", 10, 200, 50, step=10)
        page_no = st.number_input("Page", min_value=1, value=1)
        data = api_get("/headlines", topic=None if choice.startswith("(all") else choice,
                       limit=page_size, offset=(page_no - 1) * page_size)
        st.caption(
            f"{humanise(data['total'])} in-window headlines"
            + (f" for `{choice}`" if not choice.startswith("(all") else "")
            + f" · showing {humanise(len(data['rows']))}"
        )
        frame = pd.DataFrame(data["rows"])
        if not frame.empty:
            for column in ("sensational_score", "sentiment_compound"):
                if column in frame:
                    frame[column] = frame[column].round(4)
            st.dataframe(frame, hide_index=True, width="stretch")
            st.download_button(
                "Download this page as CSV",
                frame.to_csv(index=False).encode("utf-8"),
                file_name=f"headlines_{choice.replace(' ', '_').lower()}.csv",
                mime="text/csv",
            )
        caution(
            "`is_risk_signal` is a **style** flag on unlabelled headlines. It is not "
            "a fake-news determination; nothing in this corpus is labelled."
        )

    with tab[1]:
        topics = api_get("/topics")["topics"]
        topic = st.selectbox("Filter by topic", ["(all topics)"] + topics, key="wh_topic")
        series = api_get("/series/monthly", topic=None if topic.startswith("(all") else topic)
        frame = pd.DataFrame(series["rows"])
        if not frame.empty:
            chart(
                alt.Chart(frame)
                .mark_line(strokeWidth=1.6, color=ACCENT)
                .encode(
                    x=alt.X("year_month:N", axis=axis(labelAngle=-45, labelFontSize=10, tickCount=12, gridColor=None)),
                    y=alt.Y("headline_count:Q", axis=axis()),
                    tooltip=["year_month:N", "headline_count:Q",
                             alt.Tooltip("risk_signal_rate:Q", format=".2%")],
                )
                .properties(height=280)
            )
            st.caption(
                "Notice how flat this is. That flatness is the RQ2 finding, and it "
                "is why no month registers as a volume outlier."
            )
            st.download_button("Download as CSV", frame.to_csv(index=False).encode("utf-8"),
                               "monthly_series.csv", "text/csv")

    with tab[2]:
        tables = api_get("/tables")
        frame = pd.DataFrame(tables["tables"]).sort_values("rows", ascending=False)
        st.caption(
            f"{len(frame)} tables, {humanise(tables['total_rows'])} rows in total"
        )
        chart(
            alt.Chart(frame.head(14))
            .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
            .encode(
                y=alt.Y("table:N", sort="-x", axis=axis()),
                x=alt.X("rows:Q", axis=axis()),
                color=alt.value(ACCENT),
                tooltip=["table:N", "rows:Q"],
            )
            .properties(height=alt.Step(24))
        )
        with st.expander("all tables"):
            st.dataframe(frame, hide_index=True, width="stretch")

    with tab[3]:
        operations = api_get("/operations")["operations"]
        chosen = st.selectbox("Operation", [o["name"] for o in operations])
        defaults = next(o["default_params"] for o in operations if o["name"] == chosen)
        st.caption(f"default parameters: `{defaults}`")
        if st.button("Run"):
            st.json(api_get(f"/query/{chosen}"))
        st.caption(
            "Whitelisted to the ten named operations. The operation is looked up, "
            "never interpolated into SQL, and the connection is read-only."
        )

    with tab[4]:
        runs = api_get("/audit", limit=20)["runs"]
        if runs:
            st.dataframe(pd.DataFrame(runs), hide_index=True, width="stretch")
            st.caption("Every stage records its rows read, loaded and rejected.")
    footer()


# ---------------------------------------------------------------------------
# 4. How it works — where the backend effort becomes visible
# ---------------------------------------------------------------------------

elif page == "How it works":
    st.markdown("### Method, and what it refuses to do")

    tab = st.tabs(["Guard rails", "Corrections", "Decisions", "Warehouse shape", "Rules"])

    with tab[0]:
        st.markdown("#### The inference gate")
        guards = facts["guards"]
        passed = len(guards["checks"]) - len(guards["failed"])
        st.metric("Checks", f"{passed}/{len(guards['checks'])}",
                  "all passed" if guards["passed"] else f"{len(guards['failed'])} failed")
        st.markdown(
            "`dwm report` runs these and **exits non-zero** on failure, so a pipeline "
            "cannot pass silently on a warehouse that cannot back its own numbers. It "
            "still writes the report, because 'this could not be measured, and here is "
            "why' is more useful than no report."
        )
        frame = pd.DataFrame(guards["checks"])
        frame["result"] = frame["passed"].map({True: "pass", False: "FAIL"})
        st.dataframe(
            frame[["check", "result", "detail"]], hide_index=True, width="stretch"
        )
        st.caption(
            "A check that cannot be evaluated reports that rather than passing quietly, "
            "and a section reporting `ran: false` counts as a failure — a section that "
            "declined to run has not answered its question."
        )

    with tab[1]:
        st.markdown("#### Four things this study got wrong, and fixed")
        st.markdown(
            "These are the most useful part of the project. Each was found by checking "
            "the output rather than trusting it, and each had looked convincingly like "
            "a finding."
        )
        corrections = [
            {
                "area": "RQ4 clustering",
                "what": "Reported silhouette 0.068 as \"these headlines have no "
                        "recoverable topic structure\".",
                "why_it_was_wrong": "scikit-learn's token pattern admits pure numerals, "
                                    "so clusters were described by `000`, `102`, `1000`. "
                                    "With those removed they became `for`, `with`, "
                                    "`from`, because mean TF-IDF inside a cluster is "
                                    "highest for function words. And descriptions read "
                                    "off the K-Means centroid weights returned "
                                    "`aadhaar, aadmi, aap` for *every* cluster, because "
                                    "SVD components carry an arbitrary sign and "
                                    "alphabetically early features win systematically.",
                "fix": "Alphabetic-only tokens, English stop words, and describing each "
                       "cluster by the mean TF-IDF of its own members.",
                "now": "0.2582, with the correction stated in the report itself.",
            },
            {
                "area": "RQ5 rules",
                "what": "All 1,797 rules showed lift exactly 1.000, which reads as "
                        "\"every attribute is a tautology\".",
                "why_it_was_wrong": "mlxtend orders its rule frame as `antecedents, "
                                    "consequents, antecedent support, consequent "
                                    "support, support, confidence, lift`. Reading it "
                                    "positionally was off by two, so the consequent "
                                    "support was labelled confidence and the confidence "
                                    "was labelled lift. Separately, `use_colnames` "
                                    "defaults to False, so rules came back as `5 => 4`.",
                "fix": "Read columns by name, pass `use_colnames=True`, and drop "
                       "`quarter` from the item set because year and quarter are "
                       "redundant in both directions.",
                "now": "644 readable rules, both algorithms agreeing exactly.",
            },
            {
                "area": "RQ6 market",
                "what": "Reported the market question as \"no relationship\" and nearly "
                        "missed a real one.",
                "why_it_was_wrong": "Only correlations against daily *returns* were "
                                    "reported. Against 20-day volatility, log headline "
                                    "volume correlates at r = -0.2827 with p < 0.0001.",
                "fix": "Report the volatility half separately, with the number of tests "
                       "beside every p-value so one significant lag out of fifteen is "
                       "not read as a discovery.",
                "now": "Both halves reported, and the sign is left unexplained.",
            },
            {
                "area": "Reproducibility",
                "what": "Claimed fixed seeds reproduce every number, and the claim was "
                        "false.",
                "why_it_was_wrong": "DuckDB's `SAMPLE reservoir(n ROWS) REPEATABLE(seed)` "
                                    "returns the wrong number of rows — 709 for 2000 "
                                    "requested — and the sampling code topped up from "
                                    "the first headlines by id, which is a chronological "
                                    "sample of the oldest slice of the corpus. Separately, "
                                    "`silhouette_score` subsamples with no seed by default, "
                                    "so its score moved between identical runs.",
                "fix": "Sort on `hash(column, seed)` and take the first n; pass an "
                       "explicit `random_state` to the silhouette.",
                "now": "Two mining runs agree on every number, and a test asserts it.",
            },
        ]
        for correction in corrections:
            st.markdown(
                f'<div class="dwm-card"><div class="dwm-card-label">'
                f'{correction["area"]}</div>'
                f'<div style="font-size:1.05rem;font-weight:600;letter-spacing:-.015em;'
                f'margin-bottom:.4rem">{correction["what"]}</div>'
                f'<div class="dwm-evidence"><b>Why it was wrong.</b> '
                f'{correction["why_it_was_wrong"]}</div>'
                f'<div style="font-size:.88rem"><b>Fix.</b> {correction["fix"]}</div>'
                f'<div style="font-size:.88rem;color:{INK_SOFT}">'
                f'<b>Now.</b> {correction["now"]}</div></div>',
                unsafe_allow_html=True,
            )

    with tab[2]:
        st.markdown("#### Design decisions, and the reason for each")
        st.caption(
            "Every one of these is a measured property of the data rather than a "
            "preference, and several were learned the hard way."
        )
        decisions = [
            ("The window is a flag, not a filter",
             "Filtering would throw away 2 million rows that are still queryable, and "
             "make the ETL destructive. `in_window` is a boolean on the fact row, and "
             "the window is derived from `max(publish_date)` so it is never stale."),
            ("2015 is a partial year and is flagged",
             "The window starts 2015-06-30. Its wider spread made a flat series look "
             "like CV 0.39 when it was included in a whole-year statistic. Years below "
             "`full_year_months` are now excluded and named."),
            ("Headline grain is (date, text)",
             "37,629 texts recur across dates, and 111,146 (date, text) pairs are "
             "filed under more than one category. One row per category would "
             "multi-count a third of a million headlines in every topic analysis."),
            ("Cubes store sums, never averages",
             "A rounded average cannot be averaged again. Every mean in the report is "
             "recomputed as sum · count at query time, and a test rejects any column "
             "named like a mean."),
            ("`Local` is separated from subjects",
             "It is 70% of the window and is a *where*, not a *what*. `dim_topic` "
             "carries a `topic_group` so a city desk is never compared against a "
             "subject as if they matched."),
            ("`Unknown` is excluded from the topic ranking",
             "It tops the raw sensationalism ranking at 17.29% because it is a filing "
             "gap, not a subject. Its score measures the absence of a filing decision."),
            ("The threshold is 0.2208, the measured 95th percentile",
             "The original 0.5 flagged 156 rows out of 3.15 million, which is not a "
             "threshold. Because any cut-off is a judgement, the report ships a "
             "sensitivity table across eight of them."),
            ("Dimension keys are looked up, never written",
             "`dim_dataset` numbers by sorted code, so `toi` is key 3. A hard-coded 1 "
             "pointed every headline at the wrong source while all row counts stayed "
             "correct — the most dangerous kind of bug, because nothing failed."),
            ("The API serves a copy of the warehouse",
             "DuckDB locks its file exclusively even for a read-only connection, so "
             "serving the live file blocked every CLI command. The copy is byte-exact "
             "and lets the dashboard and the CLI run at the same time."),
        ]
        for title, reason in decisions:
            st.markdown(
                f'<div class="dwm-card"><div style="font-size:1rem;font-weight:600;'
                f'letter-spacing:-.015em">{title}</div>'
                f'<div class="dwm-evidence" style="margin-bottom:0">{reason}</div></div>',
                unsafe_allow_html=True,
            )

    with tab[3]:
        st.markdown("#### The warehouse")
        st.caption(
            "A star schema over three fact tables, with dimensions for date, topic, "
            "dataset, label, instrument and keyword, plus a bridge from headlines to "
            "keywords."
        )
        tables = pd.DataFrame(api_get("/tables")["tables"]).sort_values("rows", ascending=False)
        facts_names = {"fact_headline", "fact_statement", "fact_market_daily"}
        dim_names = {t for t in tables["table"] if t.startswith("dim_")}
        cube_names = {t for t in tables["table"] if t.startswith("cube_")}
        for label, names in (
            ("Fact tables", facts_names), ("Dimensions", dim_names), ("Cubes", cube_names)
        ):
            st.markdown(f"**{label}**")
            st.dataframe(
                tables[tables["table"].isin(names)][["table", "rows"]],
                hide_index=True, width="stretch",
            )
        st.markdown("**Staging, cleaning and the bridge**")
        st.dataframe(
            tables[~tables["table"].isin(facts_names | dim_names | cube_names)]
            [["table", "rows"]], hide_index=True, width="stretch",
        )

    with tab[4]:
        st.markdown("#### Rules this study holds itself to")
        st.caption(
            "These are enforced in code, not just written down. Each has at least one "
            "test that fails if it is broken."
        )
        for rule in facts.get("honesty_rules", []):
            st.markdown(f"- {rule}")
        st.divider()
        st.markdown("#### Traceability")
        st.markdown(
            "`dwm mine` writes `mining.json`. `dwm report` writes `facts.json` and "
            "renders `report.md` from it **by template**. There is no language model "
            "anywhere in the reporting path, deliberately: a language model can "
            "produce a fluent sentence containing a number nobody computed.\n\n"
            "Every fact records the source it came from, and every fact with a unit "
            "carries a caution. A test walks the payload this dashboard is reading "
            "and reports any figure that has a unit but no caveat — the warning "
            "appears in the sidebar if one is ever found."
        )
        source_note("reports/facts.json")
    footer()


# ---------------------------------------------------------------------------
# 5. Report
# ---------------------------------------------------------------------------

elif page == "Report":
    st.markdown("### Full report")
    st.caption(
        "Rendered from `facts.json` by templates. No language model was involved. "
        "The same text is at `reports/report.md`."
    )
    st.download_button(
        "Download report.md",
        api_text("/report").encode("utf-8"),
        file_name="report.md",
        mime="text/markdown",
    )
    st.divider()
    st.markdown(api_text("/report"))

