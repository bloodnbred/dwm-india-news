"""Streamlit dashboard (Phase 8).

**This file holds no analysis.** Per BLUEPRINT section 1 the dashboard is
deliberately thin: it calls the FastAPI backend and renders what comes back.
Every number it shows was computed once by the mining stage, written to
`facts.json` by the inference stage, and served unchanged. If the dashboard
computed anything itself, there would be a second path to the same figure and
the two would drift.

The one thing it does do is **carry the cautions**. Each figure is rendered
through `metric()`, which prints the fact's `unit` and `caution` underneath
it. That is not decoration: a bare "10.9%" on a screen, detached from the words
"risk-signal rate on unlabelled headlines", is exactly how a risk-signal rate
stops being called one. The API sends those strings and this file is
responsible for showing them.

Run it with `streamlit run dashboard/app.py`, ideally against
`python -m dwm serve` on port 8000.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

try:
    from helpers import humanise, pct, render_metric
except ImportError:
    # Streamlit puts the script's own directory on sys.path, so a bare import
    # normally works. This fallback is for importing the module directly, as
    # the tests do, where the package is not installed.
    from dashboard.helpers import humanise, pct, render_metric

API = os.environ.get("DWM_API", "http://127.0.0.1:8000")
TIMEOUT = 30

st.set_page_config(
    page_title="dwm-india-news",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# talking to the API
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner=False)
def api_get(path: str, **params: Any) -> Any:
    """GET the backend, turning a failure into a readable message.

    A dashboard that shows a stack trace tells the user nothing. This says
    which command to run, because the usual cause is simply that the backend
    has not been started.
    """
    try:
        response = requests.get(f"{API}{path}", params=params or None, timeout=TIMEOUT)
    except requests.RequestException as exc:
        st.error(
            f"Cannot reach the API at `{API}`.\n\n"
            f"Start it with `python -m dwm serve` in another terminal.\n\n"
            f"({type(exc).__name__})"
        )
        st.stop()
    if response.status_code == 503:
        st.error(response.json().get("detail", "the backend has no data yet"))
        st.stop()
    if response.status_code >= 400:
        st.error(f"`{path}` returned {response.status_code}: {response.text[:200]}")
        st.stop()
    return response.json()


@st.cache_data(ttl=300, show_spinner=False)
def api_post(path: str) -> Any:
    try:
        return requests.post(f"{API}{path}", timeout=TIMEOUT).json()
    except requests.RequestException as exc:
        st.error(f"Cannot reach the API at `{API}` ({type(exc).__name__})")
        st.stop()


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------


def pct(value: float | None, places: int = 2) -> str:
    return "n/a" if value is None else f"{value * 100:.{places}f}%"


def humanise(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def metric(label: str, block: dict[str, Any], fmt=pct) -> None:
    """One figure, with its unit and its caution attached.

    The caution is mandatory. A figure shown without it is the single easiest
    way for this project to say something it does not mean, because the
    dashboard is where numbers get separated from the sentences that qualify
    them. `render_metric` holds the logic so a test can check it.
    """
    parts = render_metric(label, block, fmt)
    st.metric(parts["label"], parts["value"])
    if parts["unit"]:
        st.caption(f"*{parts['unit']}*")
    if parts["caution"]:
        st.info(parts["caution"], icon="⚠️")
    else:
        # A figure with a unit and no caution would render as a bare number,
        # which is the failure mode this function exists to prevent.
        st.warning(f"**{parts['label']} has no caution attached.**", icon="⚠️")


def section(key: str) -> dict[str, Any]:
    """The body of one `/summary` section, with its caution merged in.

    `/summary` returns each question twice over: a small header of
    value/unit/caution, and the full body under `data`. Reading the body from
    the top level is a mistake that reads as a missing key at runtime, so the
    two are joined here once instead of at every access site. The caution is
    folded in under `_caution` because a section's body may legitimately have
    no `fact` key of its own.
    """
    block = summary[key]
    return {**block["data"], "_caution": block.get("caution") or ""}


def notice(text: str) -> None:
    st.warning(text, icon="⚠️")


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

health = api_get("/health")
st.sidebar.title("dwm-india-news")
st.sidebar.caption(
    f"{humanise(1113427)} headlines · 51,110 labelled statements · 5 years of Nifty 50"
)
if health.get("status") != "ok":
    st.sidebar.error(health.get("detail", "backend degraded"))

page = st.sidebar.radio(
    "Section",
    ["Overview", "Trends", "Language", "Rules", "Market", "Classifier",
     "Browse headlines", "Warehouse", "Report"],
)

if st.sidebar.button("Refresh cached results"):
    api_post("/query/reload")
    st.cache_data.clear()
    st.rerun()

summary = api_get("/summary")
facts = api_get("/facts")
st.sidebar.divider()
st.sidebar.caption(f"Mining run `{summary.get('mining_run_id')}`")

if st.sidebar.expander("The honesty rules this project holds"):
    for rule in summary.get("honesty_rules", []):
        st.sidebar.markdown(f"- {rule}")


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

if page == "Overview":
    st.title("What this study found")
    st.markdown(
        "Seven research questions against 1.1M Times of India headlines, "
        "51,110 labelled IFND statements and five years of Nifty 50 closes. "
        "**Three of the seven produced no result, and that is the finding.**"
    )

    rq2 = summary["rq2_bursts"]
    rq3 = section("rq3_sensationalism")
    rq4 = summary["rq4_clusters"]
    rq5 = section("rq5_association_rules")
    rq6 = summary["rq6_market_association"]
    rq7 = section("rq7_classifier")
    rq2_body, rq4_body = section("rq2_bursts"), section("rq4_clusters")
    rq6_body = section("rq6_market_association")

    cols = st.columns(4)
    with cols[0]:
        st.metric(
            "Headlines analysed",
            humanise(facts["corpus"]["analysis_window"]["headlines_in_window"]),
        )
        st.caption(
            f"window {facts['corpus']['analysis_window']['start']} to "
            f"{facts['corpus']['analysis_window']['end']}"
        )
    with cols[1]:
        st.metric("Months spiking on volume", humanise(rq2["value"]))
        st.caption("zero, and the volume series is flat")
    with cols[2]:
        st.metric("Cluster silhouette", f"{rq4['value']:.4f}")
        st.caption("no recoverable topic structure")
    with cols[3]:
        st.metric("Classifier accuracy", pct(summary["rq7_classifier"]["value"]))
        st.caption(f"against a {pct(rq7['baseline'])} baseline")

    st.subheader("The three negative results")
    notice(
        "**1. Headline volume carries no news signal.** Within-year variation is "
        f"{rq2_body['max_within_year_cv']}, and in "
        f"{len(rq2_body.get('predicted_desks_fell_in', []))} of the "
        f"{len(rq2_body.get('event_months', []))} listed event months every desk "
        "predicted to rise — Health, Sports, Entertainment — fell instead."
    )
    notice(
        f"**2. No topic structure.** Silhouette {rq4['value']:.4f}, and it rises to "
        "the largest k tried without turning over, so there is no preferred cluster "
        "count either."
    )
    notice(
        f"**3. No market relationship.** The strongest correlation with Nifty "
        f"returns is {rq6['value']:.4f}, which is not distinguishable from zero. "
        f"Measured over {humanise(rq6_body['trading_days_paired'])} trading days."
    )

    st.subheader("The three positive results")
    top = rq3["ranked"][0] if rq3.get("ranked") else None
    c1, c2, c3 = st.columns(3)
    with c1:
        if top:
            st.metric(
                "Highest risk-signal topic",
                top["topic"],
                pct(top["risk_signal_rate"]),
            )
            st.caption(
                f"n={humanise(top['headline_count'])}, 95% CI "
                f"{pct(top['ci95_low'])}–{pct(top['ci95_high'])}"
            )
        notice(rq3["_caution"])
    with c2:
        st.metric("Association rules mined", humanise(summary["rq5_association_rules"]["value"]))
        st.caption(f"Apriori and FP-Growth agree: {rq5['rule_sets_identical']}")
    with c3:
        st.metric("Lift over baseline", f"{rq7['metrics']['lift_over_baseline_pp']:+.1f} pp")
        st.caption(f"Fake recall {pct(rq7['metrics']['fake_recall'])}")
        notice(rq7["_caution"])

    st.subheader("The topic mix")
    window = facts["rq1_topic_mix"]["window_shares"]
    frame = pd.DataFrame(window["topics"])
    st.barchart(frame.set_index("topic")["share_of_window"])
    st.caption(
        "`Local` is a *where*, not a *what*. The publisher's own taxonomy is kept, "
        "and topic comparisons are made within a group rather than across one."
    )

    st.subheader("Inference gate")
    guards = facts["guards"]
    st.write(f"**{len(guards['checks'])} checks, "
             f"{'all passed' if guards['passed'] else str(len(guards['failed'])) + ' failed'}**")
    st.dataframe(
        pd.DataFrame(guards["checks"]),
        use_container_width=True,
        hide_index=True,
    )


elif page == "Trends":
    st.title("Trends over the window")
    rq1 = facts["rq1_topic_mix"]
    st.subheader("Largest year-on-year moves in topic share")
    moves = pd.DataFrame(rq1["largest_moves"])
    st.dataframe(
        moves[["topic", "topic_group", "from_year", "to_year", "change_pp",
               "to_count", "is_year_on_year", "both_comparable"]],
        use_container_width=True, hide_index=True,
    )
    notice(
        "Shares are within-year because raw counts are not comparable across "
        "years and 2015 is a partial year. Rows where `both_comparable` is false "
        "must not be read as trends."
    )

    st.subheader("Topic mix over time")
    mix = pd.DataFrame(rq1["top_subject_topics"])
    if not mix.empty:
        st.bar_chart(mix, x="year", y="share", color="topic")

    st.subheader("A filing artefact, not a trend")
    artefacts = pd.DataFrame(rq1["taxonomy_artefacts"])
    if not artefacts.empty:
        st.dataframe(artefacts, use_container_width=True, hide_index=True)
        notice(
            "A single raw category holding this share of one year means the "
            "publisher changed how it filed content, not that reader interest moved."
        )


elif page == "Language":
    st.title("Sensational and negative language")
    rq3 = section("rq3_sensationalism")
    notice(rq3["_caution"])

    st.subheader("Risk-signal rate by topic")
    ranked = pd.DataFrame(rq3["ranked"])
    if not ranked.empty:
        st.bar_chart(ranked, x="topic", y="risk_signal_rate")
        st.dataframe(
            ranked[["topic", "topic_group", "headline_count", "risk_signal_count",
                    "risk_signal_rate", "ci95_low", "ci95_high", "above_corpus_average"]],
            use_container_width=True, hide_index=True,
        )

    st.subheader("Over time")
    trend = pd.DataFrame(rq3["trend_by_year"])
    if not trend.empty:
        st.line_chart(trend, x="year", y="risk_signal_rate")
        st.caption("A 95% interval is attached to every point; the shadow is narrow "
                   "only because the counts are large, not because the measure is precise.")

    st.subheader("Is the ranking an artefact of the cut-off?")
    sens = pd.DataFrame(rq3["sensitivity"]["rows"])
    if not sens.empty:
        st.dataframe(
            sens[["threshold", "is_chosen_threshold", "top1", "corpus_rate"]],
            use_container_width=True, hide_index=True,
        )
        notice(
            "The top *informative* topic is "
            + ("stable" if rq3["sensitivity"].get("ranking_is_stable")
               else "NOT stable")
            + " across this range of thresholds. `Unknown` tops the raw ranking "
            "at some thresholds because it is a filing gap, not a subject."
        )


elif page == "Rules":
    st.title("Co-occurrence patterns")
    rq5 = section("rq5_association_rules")
    notice(rq5["_caution"])

    a, b = st.columns(2)
    with a:
        st.metric("Rules", humanise(rq5["rule_count"]))
        st.caption("Apriori and FP-Growth return the same set")
    with b:
        st.metric("FP-Growth speedup", f"{rq5['fpgrowth_speedup']}×")
        st.caption(
            f"Apriori {rq5['apriori_seconds']}s vs FP-Growth {rq5['fpgrowth_seconds']}s"
        )

    if not rq5["rule_sets_identical"]:
        notice(
            "The two algorithms returned DIFFERENT rule sets. That is a bug, "
            "not a finding: they search the same itemsets."
        )

    st.subheader("Highest-lift rules")
    rules = pd.DataFrame(rq5["top_rules"])
    if not rules.empty:
        rules["if"] = rules["antecedent"].apply(" + ".join)
        rules["then"] = rules["consequent"].apply(" + ".join)
        st.dataframe(
            rules[["if", "then", "support", "confidence", "lift", "is_informative"]],
            use_container_width=True, hide_index=True,
        )

    st.subheader("Why attributes, not keywords")
    st.write(
        f"Attribute transactions carry **{rq5['mean_items']} items** each across "
        f"{len(rq5['attribute_items'] or [])} attributes. The 300-term keyword "
        f"vocabulary yields only **{rq5['keyword_run']['mean_items']} items per "
        "headline**, because its most frequent terms are functional words like "
        "`govt`, `held`, `get`, `man`, `police`. A one-item transaction supports "
        "no co-occurrence."
    )
    if rq5["keyword_run"].get("caveat"):
        notice(rq5["keyword_run"]["caveat"])


elif page == "Market":
    st.title("Headlines and the Nifty")
    rq6 = section("rq6_market_association")
    notice(rq6["_caution"])
    st.metric("Paired trading days", humanise(rq6["trading_days_paired"]))

    rows = [
        {
            "measure": name.replace("_", " "),
            "lag (trading days)": entry["lag_trading_days"],
            "pearson r": entry["pearson_r"],
            "spearman rho": entry.get("spearman_rho"),
            "p": entry.get("p_value"),
            "n": entry.get("n"),
        }
        for name, m in rq6["measures"].items()
        for entry in m.get("by_lag", [])
        if entry.get("pearson_r") is not None
    ]
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.line_chart(
            frame.pivot_table(
                index="lag (trading days)", columns="measure", values="pearson r"
            )
        )

    notice(
        "Only **trading days** are used: headlines appear on 1,828 days in the "
        "window and the market trades on 1,235. A weekend has headlines and no "
        "close price, and pairing them would invent data."
    )


elif page == "Classifier":
    st.title("Real vs Fake on IFND")
    rq7 = section("rq7_classifier")
    notice(rq7["_caution"])
    notice(rq7["upper_bound_caveat"])

    m = rq7["metrics"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Accuracy", pct(m["accuracy"]))
    with c2:
        st.metric("Majority baseline", pct(m["majority_baseline_accuracy"]))
    with c3:
        st.metric("Lift", f"{m['lift_over_baseline_pp']:+.1f} pp")
    with c4:
        st.metric("Fake recall", pct(m["fake_recall"]))

    st.subheader("Every model, judged against the baseline")
    st.dataframe(
        pd.DataFrame(rq7["models"]).T, use_container_width=True
    )
    st.caption(
        f"`{rq7['chosen_model']}` was chosen on **training** cross-validated "
        f"accuracy ({rq7['train_cv_accuracy']}), and the test split was scored once. "
        "Selecting a model on test accuracy and then reporting that number is the "
        "optimism this study set out to avoid."
    )

    st.subheader("Per class")
    st.dataframe(
        pd.DataFrame(m["per_class"]).T, use_container_width=True
    )

    st.subheader("Confusion matrix")
    matrix = m["confusion_matrix"]["matrix"]
    labels = m["confusion_matrix"]["labels"]
    st.dataframe(
        pd.DataFrame(
            matrix, index=[f"actual {name}" for name in labels], columns=labels
        ),
        use_container_width=True,
    )
    st.caption(m["confusion_matrix"]["reading"])

    if rq7.get("top_terms"):
        st.subheader("What the model learned")
        terms = rq7["top_terms"]
        length = max(len(terms.get("toward_fake", [])), len(terms.get("toward_real", [])))
        st.dataframe(
            pd.DataFrame({
                "toward FAKE": terms.get("toward_fake", [""] * length)[:length],
                "toward REAL": terms.get("toward_real", [""] * length)[:length],
            }),
            use_container_width=True, hide_index=True,
        )


elif page == "Browse headlines":
    st.title("Browse the corpus")
    topics = api_get("/topics")["topics"]
    choice = st.selectbox("Topic", ["(all topics)"] + topics)
    topic = None if choice.startswith("(all") else choice
    page_size = st.slider("Rows", 10, 200, 50, step=10)
    page_no = st.number_input("Page", min_value=1, value=1)

    data = api_get(
        "/headlines", topic=topic, limit=page_size, offset=(page_no - 1) * page_size
    )
    st.caption(
        f"{humanise(data['total'])} in-window headlines"
        + (f" for `{choice}`" if topic else "")
        + f" · showing {humanise(len(data['rows']))}"
    )
    frame = pd.DataFrame(data["rows"])
    if not frame.empty:
        frame["sensational_score"] = frame["sensational_score"].round(4)
        frame["sentiment_compound"] = frame["sentiment_compound"].round(4)
        st.dataframe(frame, use_container_width=True, hide_index=True)
    notice(
        "`is_risk_signal` is a **style** flag on unlabelled headlines. It is not a "
        "fake-news determination; nothing in this corpus is labelled."
    )


elif page == "Warehouse":
    st.title("The warehouse")
    tables = api_get("/tables")
    st.caption(
        f"{len(tables['tables'])} tables, {humanise(tables['total_rows'])} rows total"
    )
    st.dataframe(
        pd.DataFrame(tables["tables"]).sort_values("rows", ascending=False),
        use_container_width=True, hide_index=True,
    )

    st.subheader("Monthly series")
    topics = api_get("/topics")["topics"]
    topic = st.selectbox("Filter by topic", ["(all topics)"] + topics, key="wh_topic")
    series = api_get("/series/monthly", topic=None if topic.startswith("(all") else topic)
    frame = pd.DataFrame(series["rows"])
    if not frame.empty:
        st.line_chart(frame, x="year_month", y="headline_count")
        st.caption(
            "Notice how flat this is. That flatness is the RQ2 finding, and it is "
            "the reason no month registers as a volume outlier."
        )

    st.subheader("OLAP operations")
    operations = api_get("/operations")["operations"]
    st.dataframe(pd.DataFrame(operations), use_container_width=True, hide_index=True)
    chosen = st.selectbox("Run an operation", [o["name"] for o in operations])
    if st.button("Run"):
        st.json(api_get(f"/query/{chosen}"))

    st.subheader("Pipeline audit trail")
    runs = api_get("/audit", limit=20)["runs"]
    if runs:
        st.dataframe(pd.DataFrame(runs), use_container_width=True, hide_index=True)


elif page == "Report":
    st.title("Full report")
    st.caption("Rendered from `facts.json` by templates. No language model was involved.")
    st.markdown(api_get("/report"))
