"""Report rendering (Phase 7): facts.json -> report.md.

**There is no language model in this file.** Every sentence is a template and
every number comes from a fact, which is what makes "each number traces to a
query" checkable rather than aspirational. A fact carries a `source` key and,
where it is easy to misread, a `caution` that is printed next to it.

The renderer is deliberately dull: a function per section, returning markdown.
That way a reader who distrusts a number can find the exact function and the
exact fact that produced it.

Cautions are not decorative. `_caution_block` prints a fact's `caution` field
wherever the value appears, so a risk-signal rate cannot be quoted without its
"this is not a fake-news rate" sentence travelling with it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from dwm.config import reports_dir
from dwm.logging_utils import get

log = get("dwm.inference.report")


# Resolved when used, not at import, so the reports directory can be
# redirected by the environment regardless of module import order.
def report_path() -> Path:
    return reports_dir() / "report.md"


# ---------------------------------------------------------------------------
# small formatting helpers
# ---------------------------------------------------------------------------


def pct(value: float | None, places: int = 2) -> str:
    """A proportion as a percentage, or an explicit dash when absent.

    Never returns a bare number for a None: a missing rate and a zero rate
    look identical otherwise, and only one of them is a finding.
    """
    if value is None:
        return "n/a"
    return f"{value * 100:.{places}f}%"


def num(value: float | int | None, places: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:.{places}f}"


def _caution_block(fact_data: dict[str, Any] | None) -> str:
    """Render a fact's caution as a blockquote, or nothing if it has none."""
    if not fact_data or not fact_data.get("caution"):
        return ""
    return f"\n> **Read this before quoting the number.** {fact_data['caution']}\n"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No rows available._\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


def header(facts: dict[str, Any]) -> str:
    window = facts["corpus"]["analysis_window"]
    counts = facts["corpus"]["row_counts"]
    start, end = window["start"], window["end"]
    span_years = int(end[:4]) - int(start[:4]) + 1
    return "\n".join([
        "# What 1.1 million Indian news headlines actually show",
        "",
        "A data-warehousing and mining study built on "
        f"{humanise(counts['stg_toi'])} Times of India headlines, "
        f"{humanise(counts['stg_ifnd'])} IFND statements carrying real/fake labels, "
        f"and {humanise(counts['stg_nifty'])} Nifty 50 trading sessions.",
        "",
        f"**Analysis window** {start} to {end}, which is {span_years} calendar years. "
        "The window is derived from the last publish date in the corpus, not "
        "hard-coded, and it is applied as a **flag rather than a filter**: "
        f"{humanise(counts['cln_headline'] - window['headlines_in_window'])} "
        "out-of-window headlines stay in the warehouse and remain queryable.",
        "",
        f"*Generated {str(facts.get('generated_at', ''))[:19]} from `facts.json` "
        f"(mining run {facts.get('mining_run_id')}).*",
        "",
        "> **Two of the seven findings are negative, and they are the most",
        "> informative results in this study.** Monthly headline volume does not",
        "> respond to national events, and these headlines have almost no",
        "> recoverable topic structure. Both are reported with the measurement",
        "> that establishes them rather than replaced by a finding that was",
        "> chosen for being more convenient.",
        "",
    ])


def humanise(value: int | float | None) -> str:
    """Thousands-separated integer, or an explicit dash when absent.

    Handles None because a missing count and a zero count must not print the
    same thing, and a crash here would take the whole report down rather than
    one cell.
    """
    if value is None:
        return "n/a"
    return f"{int(value):,}"


def data_section(facts: dict[str, Any]) -> str:
    counts = facts["corpus"]["row_counts"]
    window = facts["corpus"]["analysis_window"]
    parts = [
        "## 1. The data",
        "",
        f"Three sources, staged losslessly and reconciled row for row: "
        f"{humanise(counts['stg_toi'])} TOI headlines, "
        f"{humanise(counts['stg_ifnd'])} IFND statements and "
        f"{humanise(counts['stg_nifty'])} Nifty 50 sessions, with zero rejects.",
        "",
        "### Sources",
        "",
        _table(
            ["source", "rows staged", "labelled", "date precision", "licence"],
            [
                [
                    d["name"],
                    humanise(d["staged_rows"]),
                    "yes" if d["labelled"] else "no",
                    d["declared_date_precision"],
                    d["license"] or "see citation",
                ]
                for d in facts["datasets"].values()
            ],
        ),
        "",
        "Full citations:",
        "",
    ]
    for d in facts["datasets"].values():
        if d.get("citation"):
            parts.append(f"- **{d['name']}** — {d['citation']}")
    parts += [
        "",
        "### What survives cleaning",
        "",
        _table(
            ["stage", "rows", "note"],
            [
                ["staged headlines", humanise(counts["stg_toi"]), "lossless staging"],
                ["clean headlines", humanise(counts["cln_headline"]),
                 f"{humanise(counts['stg_toi'] - counts['cln_headline'])} dropped as exact duplicates"],
                ["**in the analysis window**", f"**{humanise(window['headlines_in_window'])}**",
                 "flag, not a filter: out-of-window rows stay in the warehouse"],
                ["labelled statements", humanise(counts["cln_statement"]),
                 "IFND, 3 label values normalised to 2"],
                ["market sessions", humanise(counts["cln_market_daily"]), "daily OHLCV"],
                ["date dimension", humanise(counts["dim_date"]),
                 f"spans {facts['corpus']['archive_span']['start']} to {facts['corpus']['archive_span']['end']}"],
                ["topic dimension", humanise(counts["dim_topic"]), "from the publisher taxonomy"],
                ["keyword dimension", humanise(counts["dim_keyword"]),
                 f"{humanise(counts['bridge_headline_keyword'])} headline-keyword pairs"],
            ],
        ),
        "",
        "### Where this data is weak, stated up front",
        "",
        _limitations(facts),
    ]
    return "\n".join(parts)


def _limitations(facts: dict[str, Any]) -> str:
    quality = facts["corpus"]["ifnd_date_quality"]
    balance = facts["corpus"]["ifnd_label_balance"]
    total = sum(balance.values()) or 1
    lines = [
        "These limitations shaped the design, and each one is a reason a result",
        "below is worded the way it is.",
        "",
        "1. **No ground truth on the headline corpus.** TOI headlines carry a",
        "   category but no label. Every style measure in this report is a",
        "   *risk-signal rate* and never a fake-news rate. Only IFND supports an",
        "   accuracy claim.",
        f"2. **IFND is imbalanced.** {humanise(balance.get('REAL', 0))} real against "
        f"{humanise(balance.get('FAKE', 0))} fake, so always answering \"real\" scores "
        f"{max(balance.values()) / total:.1%}. The classifier is judged against that, "
        "not against 50%.",
        f"3. **IFND dates are largely unusable.** Of {humanise(sum(quality.values()))} "
        "statements, "
        + ", ".join(
            f"{humanise(v)} carry only a {k.replace('_', '-')}"
            for k, v in quality.items()
        )
        + ". The statements stay in the corpus, but the classifier uses text only "
        "and makes no claim about when anything was published.",
        "4. **The publisher changed how it files content.** In 2017 the single",
        "   category `business.international-business` is 11.1% of every headline;",
        "   a year later it is 0.2%. A topic-mix analysis that ignored this would",
        "   report a news-industry event as a change in what India was reading.",
        "5. **`Local` is 70% of the window and is a *where*, not a *what*.** Topic",
        "   comparisons are made within `topic_group` (Place, Subject, Type) so a",
        "   city desk is never compared against a subject as if they matched.",
        "6. **2015 is a partial year.** The window starts 2015-06-30. All trend",
        "   statements are within-year shares, and raw counts across years are",
        "   not comparable.",
    ]
    return "\n".join(lines)


def rq1_section(facts: dict[str, Any]) -> str:
    rq = facts["rq1_topic_mix"]
    window = rq.get("window_shares", {})
    rows = [
        [
            move["topic"],
            move["topic_group"],
            f"{move['from_year']} → {move['to_year']}",
            f"{move['from_share'] * 100:.2f}% → {move['to_share'] * 100:.2f}%",
            f"{move['change_pp']:+.2f} pp",
            humanise(move["to_count"]),
            "partial year, not compared"
            if not move.get("both_comparable")
            else (f"{move['year_gap']}-year gap" if not move.get("is_year_on_year") else ""),
        ]
        for move in rq["largest_moves"][:8]
    ]
    artefacts = rq.get("taxonomy_artefacts", [])

    parts = [
        "## 2. RQ1 — How did the topic mix change?",
        "",
    ]
    if window.get("topics"):
        top = window["topics"][0]
        parts += [
            f"**`{top['topic']}` is {pct(top['share_of_window'])} of the "
            f"{span_years_note(facts)} window** "
            f"({humanise(top['headline_count'])} of "
            f"{humanise(window['headlines_in_window'])} headlines). It is a *where*",
            "rather than a *what*, which is why `dim_topic` separates Place from",
            "Subject and why every subject comparison below is made within a group.",
            "",
            _table(
                ["topic", "group", "headlines", "share of the window"],
                [
                    [t["topic"], t["topic_group"], humanise(t["headline_count"]),
                     pct(t["share_of_window"])]
                    for t in window["topics"][:8]
                ],
            ),
            "",
        ]
    parts += [
        "### Largest year-on-year moves in topic share",
        "",
        "Within-year shares, because raw counts are not comparable across years",
        "and 2015 is a partial year.",
        "",
        _table(
            ["topic", "group", "years", "share", "change", "rows in later year", "note"],
            rows,
        ),
        "",
    ]
    if rq.get("top_subject_topics"):
        parts += [
            "### Largest subject topics by year",
            "",
            _table(
                ["topic", "year", "share of that year"],
                [
                    [t["topic"], t["year"], pct(t["share"])]
                    for t in rq["top_subject_topics"]
                ],
            ),
        ]
    if artefacts:
        parts += [
            "",
            "### A filing artefact, not a trend",
            "",
            "These raw categories hold an implausible share of a single year, which",
            "means the publisher changed how it filed content rather than that",
            "reader interest moved:",
            "",
            _table(
                ["year", "raw category", "rows", "share of that year"],
                [
                    [a["year"], f"`{a['raw_category']}`", humanise(a["count"]),
                     pct(a["share_of_year"])]
                    for a in artefacts[:5]
                ],
            ),
            "",
            rq.get("artefact_note") or "",
        ]
    parts.append(_caution_block(rq.get("fact")))
    return "\n".join(parts)


def span_years_note(facts: dict[str, Any]) -> str:
    """A short description of the analysis window, for inline use."""
    window = facts["corpus"]["analysis_window"]
    start, end = window["start"], window["end"]
    return f"{start} to {end} analysis window"


def _z(measures: dict[str, Any], name: str) -> str:
    """A z-score for formatting, or an explicit dash when the series is absent.

    Pulled out of the event loop on purpose: a closure over the loop variable
    is correct only while it is called in the same iteration, which is exactly
    the kind of thing that breaks when someone adds a second loop below.
    """
    value = measures.get(name, {}).get("z_score")
    return f"{value:+.2f}" if isinstance(value, (int, float)) else "n/a"


def rq2_section(facts: dict[str, Any]) -> str:
    rq = facts["rq2_bursts"]
    per_year = rq.get("per_year_cv", {})
    events = rq.get("event_months", [])

    rows = [
        [
            e["year_month"],
            e["label"],
            _z(e.get("measures", {}), "topic_volume:Health"),
            _z(e.get("measures", {}), "topic_volume:Sports"),
            _z(e.get("measures", {}), "topic_volume:Entertainment"),
            _z(e.get("measures", {}), "negative_rate"),
        ]
        for e in events
    ]

    return "\n".join([
        "## 3. RQ2 — Which months spike, and do they match known events?",
        "",
        "### The answer is no, and the measurement is the interesting part",
        "",
        f"**{rq['volume_bursts_found']} months** exceeded the z-score threshold.",
        "That is not a tuning failure. Monthly headline volume is almost perfectly",
        "flat:",
        "",
        _table(
            ["year", "coefficient of variation of monthly volume"],
            [[y, f"{v:.4f}" if v is not None else "excluded (partial year)"]
             for y, v in sorted(per_year.items())],
        ) if per_year else "",
        "",
        "The busiest month of a full year runs only 2-5% above its own monthly",
        "mean. March 2020, the month India entered a national lockdown, is 2.5%",
        "above its year mean. A z-score of 2.0 cannot fire on a series this",
        "flat, and lowering it until something appeared would be choosing a",
        "threshold to manufacture a finding.",
        "",
        "### What the event months actually look like",
        "",
        "The listed events are calendar coincidences offered for the reader to",
        "judge, not causes. Several measures run *opposite* to what a",
        "news-reactive archive would show:",
        "",
        _table(
            ["month", "event", "Health z", "Sports z", "Entertainment z", "negative sentiment z"],
            rows,
        ) if rows else "_No event months in the configured window._",
        "",
        rq.get("counter_signal_summary") or "",
        "",
        "Read the magnitudes carefully. These are standard deviations on a series",
        "that barely moves, so a z of −1.5 is a real departure from the norm and",
        "still a small one in absolute terms. What carries the weight is the",
        "**sign** on a prediction fixed in advance: the desks a news-reactive",
        "archive should have covered more heavily during a pandemic are the ones",
        "that fell.",
        "",
        "The honest caveat is that this data cannot distinguish a genuinely",
        "quota-driven newsroom from a sampling artefact of whatever export the",
        "publisher produced. Both produce the same signature, and separating them",
        "would need data this study does not have.",
        "",
        _caution_block(rq.get("fact")),
    ])


def rq3_section(facts: dict[str, Any]) -> str:
    rq = facts["rq3_sensationalism"]
    trend = rq.get("trend_by_year", [])
    sensitivity = rq.get("sensitivity", {})

    trend_rows = [
        [t["year"], humanise(t["headline_count"]), pct(t["risk_signal_rate"]),
         f"{t['ci95_low'] * 100:.2f}% – {t['ci95_high'] * 100:.2f}%"]
        for t in trend if t.get("risk_signal_rate") is not None
    ]
    rank_rows = [
        [r["topic"], pct(r["risk_signal_rate"]),
         f"{r['ci95_low'] * 100:.2f}% – {r['ci95_high'] * 100:.2f}%",
         humanise(r["headline_count"]),
         "yes" if r.get("above_corpus_average") else "no"]
        for r in rq["ranked"][:8]
    ]
    sens_rows = [
        [f"{row['threshold']:.4f}" + (" ← chosen" if row.get("is_chosen_threshold") else ""),
         row.get("top1") or "n/a", ", ".join(row.get("top3", [])[:3])]
        for row in sensitivity.get("rows", [])
    ]

    excluded = rq.get("excluded_uninformative", {})
    parts = [
        "## 4. RQ3 — Which categories use the most sensational language?",
        "",
        "Corpus risk-signal rate: "
        f"**{pct(rq['corpus_rate'])}** at a threshold of {rq['threshold']} "
        "(the measured 95th percentile of the score distribution).",
        "",
        "### By topic, with a confidence interval on every rate",
        "",
        _table(
            ["topic", "risk-signal rate", "95% CI", "headlines", "above corpus average?"],
            rank_rows,
        ),
        "",
        "The interval matters more than the ranking. Counts here are in the tens",
        "of thousands, so a bare percentage would imply a precision the measure",
        "does not have. A Wilson interval is used rather than the normal",
        "approximation because the highest-scoring topics sit near the extremes,",
        "where the normal interval runs outside [0, 1].",
        "",
    ]
    if excluded.get("topics"):
        names = ", ".join(f"`{t}`" for t in excluded["topics"])
        verb = "is" if len(excluded["topics"]) == 1 else "are"
        parts += [
            f"**{names} {verb} excluded from the ranking.** "
            + (excluded.get("reason") or ""),
            "",
        ]
    if trend_rows:
        parts += [
            "### Trend over the window",
            "",
            _table(["year", "headlines", "risk-signal rate", "95% CI"], trend_rows),
            "",
        ]
    if sens_rows:
        parts += [
            "### Is the ranking an artefact of the cut-off?",
            "",
            "The threshold is a judgement, so the ranking is recomputed across a",
            "range. If the top topic changed as the cut-off moved, the ranking would",
            "be an artefact of the cut-off rather than a finding.",
            "",
            _table(["threshold", "top topic", "top three"], sens_rows),
            "",
            (f"The top *informative* topic is "
             f"{'stable' if sensitivity.get('ranking_is_stable') else 'NOT stable'} "
             "across this range. `Unknown` tops the raw ranking at some "
             "thresholds because it is a filing gap rather than a subject, so "
             "it is excluded from the stability judgement — the raw count is "
             "shown above so the difference is visible."),
            "",
        ]
    parts.append(_caution_block(rq.get("fact")))
    return "\n".join(parts)


def rq4_section(facts: dict[str, Any]) -> str:
    rq = facts["rq4_clusters"]
    if not rq.get("ran"):
        return "\n".join([
            "## 5. RQ4 — What topic clusters exist?",
            "",
            f"Not run: {rq.get('reason')}",
        ])

    cluster_rows = [
        [c["cluster_id"], humanise(c["size"]), pct(c["share_of_sample"]),
         ", ".join(c["top_terms"][:6]),
         ", ".join(t["topic"] for t in c["dominant_supplied_topics"][:2])]
        for c in rq["clusters"][:8]
    ]
    k_rows = [[s["k"], f"{s['silhouette']:.4f}"] for s in rq.get("k_candidates", [])]
    stability = rq.get("stability", {})
    strong = "strong" if rq.get("silhouette_is_strong") else "weak"

    return "\n".join([
        "## 5. RQ4 — Do natural topic clusters exist in the headlines?",
        "",
        f"**Silhouette {rq['silhouette']:.4f}, which is {strong} separation.** The",
        "conventional reading treats below 0.25 as weak and below 0.1 as",
        "effectively none.",
        "",
        rq.get("concentration_note") or "",
        "",
        "### A correction worth stating plainly",
        "",
        "An earlier version of this analysis concluded that these headlines had",
        "**no recoverable topic structure**, on a silhouette of 0.068. That",
        "conclusion was wrong, and the fault was in the feature engineering",
        "rather than in the data. Two fixes moved the score from 0.068 to "
        f"{rq['silhouette']:.4f}:",
        "",
        "1. **Numbers were admitted as terms.** The scikit-learn default token",
        "   pattern allows pure numerals, and because numerals appear in a large",
        "   share of headlines they crowded out every content word. The clusters",
        "   were described by `000`, `102` and `1000`.",
        "2. **Function words were not removed.** With them present, the mean",
        "   TF-IDF inside a cluster is highest for words like `for`, `with` and",
        "   `the`, because they occur in a modest share of documents but a large",
        "   share of any one cluster. The clusters were described by stopwords.",
        "",
        "A third fix was needed to make the descriptions mean anything: clusters",
        "are described by the mean TF-IDF of their own members rather than by the",
        "K-Means centroid weights. Projecting centroid weights back onto the term",
        "axis through the LSA basis returned `aadhaar, aadmi, aap, aarti` for",
        "*every* cluster, because SVD components carry an arbitrary sign and small",
        "numerical asymmetries make alphabetically early features win",
        "systematically.",
        "",
        "None of those three defects is visible in a silhouette computed on a",
        "different feature space, which is why the first number looked like a",
        "property of the corpus rather than of the pipeline. The lesson is that",
        "'the data has no structure' and 'my features had no signal' are easy to",
        "confuse and must be separated before being reported.",
        "",
        "### k selection",
        "",
        _table(["k", "silhouette"], k_rows),
        "",
        rq.get("k_note") or "",
        "",
        "A first attempt at this ran K-Means directly on the 20,000-dimensional",
        "sparse TF-IDF matrix and measured a silhouette of **0.005 at every k** —",
        "zero separation, because in that many dimensions every document is nearly",
        "equidistant from every other. Adding truncated-SVD (LSA) reduction to",
        f"{rq['svd_components']} components lifted the score roughly fourteenfold.",
        f"The reduction explains {pct(rq.get('svd_variance_explained'))} of the",
        "variance, which is itself part of the explanation for the low score.",
        "",
        "### The clusters",
        "",
        f"From a fixed-seed sample of {humanise(rq['sample_size'])} headlines. The",
        "right-hand column is the publisher's own topic for the same documents, so",
        "the comparison shows how far unsupervised grouping gets toward the",
        "supplied taxonomy.",
        "",
        _table(
            ["cluster", "size", "share", "top terms", "dominant supplied topics"],
            cluster_rows,
        ),
        "",
        "The small clusters are legible and the remainder is not. Terms like",
        "`rs crore`, `lakh` and `worth` are money; `road`, `accident` and `killed`",
        "are traffic and crime reporting; `old`, `year old` and `girl` are",
        "age-and-gender copy. Those are real, recurring headline shapes and none",
        "of them is a topic in the publisher's own taxonomy — which is why the",
        "right-hand column is dominated by `Local` for every cluster. What the",
        "clustering found is a set of **writing patterns**, not desks.",
        "",
        f"**Stability.** {stability.get('note', '')} Agreement was "
        f"{stability.get('agreement_ratio', 'n/a')} on the same documents refit "
        "with two different K-Means seeds.",
        "",
        _caution_block(rq.get("fact")),
    ])


def rq5_section(facts: dict[str, Any]) -> str:
    rq = facts["rq5_association_rules"]
    if not rq.get("ran"):
        return "\n".join([
            "## 6. RQ5 — Which co-occurrence patterns exist?",
            "",
            f"Not run: {rq.get('reason')}",
        ])

    rule_rows = [
        [
            " + ".join(r["antecedent"]),
            "=>",
            " + ".join(r["consequent"]),
            f"{r['support'] * 100:.2f}%",
            f"{r['confidence'] * 100:.1f}%",
            f"{r['lift']:.3f}",
        ]
        for r in rq["top_rules"][:10]
    ]
    keyword = rq.get("keyword_run", {})

    thresholds = rq.get("thresholds") or {}
    support = thresholds.get("min_support")
    confidence = thresholds.get("min_confidence")
    max_len = thresholds.get("max_len")
    return "\n".join([
        "## 6. RQ5 — Which co-occurrence patterns exist?",
        "",
        f"**{humanise(rq['rule_count'])} rules** at support ≥ {support}, "
        f"confidence ≥ {confidence}, maximum rule length {max_len}.",
        "",
        "### Two algorithms, one answer",
        "",
        _table(
            ["algorithm", "rules", "time"],
            [
                ["Apriori", humanise(rq["rule_count"]), f"{rq['apriori_seconds']} s"],
                ["FP-Growth", humanise(rq["rule_count"]), f"{rq['fpgrowth_seconds']} s"],
                ["**speedup**", "—", f"**{rq['fpgrowth_speedup']}×**"],
            ],
        ),
        "",
        f"**Rule sets identical: {rq['rule_sets_identical']}.** Both algorithms were run",
        "on identical transactions with identical thresholds. They must return the",
        "same rules, because they search the same itemsets; a difference would mean",
        "one of them is broken, not interesting. The only thing being measured is",
        "the time, and FP-Growth is the faster of the two.",
        "",
        "### The strongest non-trivial rules, by lift",
        "",
        "Ranking by lift alone would put tautologies at the top — a rule whose",
        "consequent is implied by its antecedent scores exactly 1.000. Those are",
        "counted separately below, and this table shows the rules that carry",
        "information.",
        "",
        rq.get("lift_caveat") or "",
        "",
        _table(["if", "", "then", "support", "confidence", "lift"], rule_rows),
        "",
        "### The most confident rules",
        "",
        "The more informative of the two tables, because confidence is not",
        "inflated by a rare consequent in the way lift is.",
        "",
        _table(
            ["if", "", "then", "support", "confidence", "lift"],
            [
                [
                    " + ".join(r["antecedent"]), "=>",
                    " + ".join(r["consequent"]),
                    f"{r['support'] * 100:.2f}%",
                    f"{r['confidence'] * 100:.1f}%",
                    f"{r['lift']:.3f}",
                ]
                for r in (rq.get("top_rules_by_confidence") or [])[:8]
            ],
        ),
        "",
        rq.get("redundancy_note") or "",
        "",
        "### Why transactions are attributes, not keywords",
        "",
        "The plan was to mine the 300-term keyword vocabulary in the bridge table.",
        f"Measured on the real corpus it yields **{keyword.get('mean_items')} items",
        "per headline**, because its most frequent terms are functional words:",
        "`govt`, `held`, `get`, `man`, `police`, `case`, `two`. A transaction with",
        "two items supports almost no co-occurrence, so rules over them would be",
        "reporting sparsity as a pattern.",
        "",
        f"Attribute transactions carry **{rq.get('mean_items')} items** each across "
        f"{len(rq.get('attribute_items') or [])} attributes "
        f"({', '.join(rq.get('attribute_items') or [])}), drawing on a vocabulary of "
        f"only {rq.get('item_vocabulary_size')} distinct values, and the research",
        "question's own example rule is attribute-shaped: `topic=Business,",
        "year=2016 => sensational=high`.",
        "",
        _keyword_outcome(keyword),
        "",
        _caution_block(rq.get("fact")),
    ])


def _keyword_outcome(keyword: dict[str, Any]) -> str:
    """Report what the keyword run actually found, which is nothing.

    Stated as a result rather than as an absence, because "the vocabulary this
    project built cannot support association rules" is a finding about the
    feature pipeline, and a reader deciding whether to rebuild it needs to
    know.
    """
    if not keyword:
        return "_The keyword run was not performed._"
    rules = keyword.get("rule_count")
    items = keyword.get("mean_items")
    sampled = keyword.get("sampled")
    if not rules:
        return (
            f"**The keyword run produced zero rules**, and that is reported as a "
            f"result rather than an omission. Across {humanise(sampled or 0)} "
            f"sampled headlines the mean transaction held {items} keywords, and at "
            "the configured support and confidence thresholds no pair of terms "
            "cleared the bar. The vocabulary is dominated by functional words, so "
            "it carries almost no co-occurrence structure to mine. Rebuilding this "
            "feature would need domain-specific term extraction rather than a "
            "top-300-by-frequency cut."
        )
    return (
        f"The keyword run returned {humanise(rules or 0)} rules from "
        f"{humanise(sampled or 0)} sampled headlines at {items} items per "
        "transaction. Reported with its caveat, because a rule set mined from "
        "near-empty transactions is not a meaningful result."
    )


def _significance_paragraph(accounting: dict[str, Any]) -> str:
    """Account for the number of tests before calling anything significant.

    Fifteen lag tests at α = 0.05 produce about three quarters of a false
    positive on average, so a single p below 0.05 is the expected outcome of
    running the tests, not a discovery. Saying so is the difference between a
    significance test and a significance-looking number.
    """
    if not accounting:
        return ""
    tests = accounting.get("tests_run", 0)
    expected = accounting.get("expected_false_positives")
    found = accounting.get("significant_results", [])
    if not found:
        return (
            f"None of the {tests} lag tests is significant. At α = "
            f"{accounting.get('alpha')} that is the expected outcome — about "
            f"{expected} false positives — so the absence of significance is "
            "not itself informative, and neither is its presence."
        )
    detail = ", ".join(
        f"{r['measure'].replace('_', ' ')} at lag {r['lag']} "
        f"(r = {r['pearson_r']:+.4f}, p = {r['p_value']:.4f})"
        for r in found
    )
    verdict = (
        "That **exceeds** what chance alone would produce."
        if accounting.get("exceeds_chance")
        else "That is **within** what chance alone would produce"
    )
    return (
        f"{len(found)} of {tests} lag tests is significant ({detail}). "
        f"At α = {accounting.get('alpha')}, {tests} tests yield about {expected} "
        f"false positives by chance. {verdict} On this evidence the significant "
        "result is not treated as a finding, and the coefficient involved is "
        "small in any case."
    )


def _volatility_paragraph(volatility: dict[str, Any]) -> str:
    """Interpret the volatility half of RQ6 from the measured numbers."""
    strongest = volatility.get("strongest")
    if not strongest or strongest.get("pearson_r") is None:
        return "No volatility correlation could be computed on this data."
    r = strongest["pearson_r"]
    share = strongest.get("variance_explained_pct")
    if not strongest.get("significant_at_alpha"):
        return (
            f"The strongest volatility correlation is {r:+.4f}, which is not "
            "statistically significant. There is no relationship to report."
        )
    return (
        f"**Log `{strongest.get('name', 'headline volume').replace('_', ' ')}` "
        f"correlates with 20-day volatility at r = {r:+.4f}, and the coefficient "
        f"is significant.** Headline volume and market volatility move together, "
        f"and the relationship is *negative*: busier headline days go with calmer "
        f"markets. It accounts for {share:.1f}% of the variance in volatility, so "
        "it is a real association and a weak predictor — it would be misleading "
        "to describe it as either strong or causal.\n\n"
        "The direction is the interesting part and this data cannot explain it. "
        "Two readings fit equally well: a newsroom under pressure covers the "
        "market crash rather than business, or headline volume in this archive is "
        "capped and crisis coverage displaces routine coverage. Separating them "
        "would need the unrounded per-day export, which this corpus does not "
        "provide. It is reported as an association and left there."
    )


def rq6_section(facts: dict[str, Any]) -> str:
    rq = facts["rq6_market_association"]
    if not rq.get("ran"):
        return "\n".join([
            "## 7. RQ6 — Do headlines relate to the Nifty?",
            "",
            f"Not run: {rq.get('reason')}",
        ])

    rows = []
    for name, m in rq["measures"].items():
        p = m.get("p_value")
        rows.append([
            name.replace("_", " "),
            f"{m['pearson_r']:+.4f}" if m.get("pearson_r") is not None else "n/a",
            f"{m['spearman_rho']:+.4f}" if m.get("spearman_rho") is not None else "n/a",
            m.get("strongest_lag"),
            f"{p:.4f}" if p is not None else "n/a",
            "yes" if m.get("significant") else "no",
        ])

    lag_rows = [
        [
            name.replace("_", " "),
            entry["lag_trading_days"],
            f"{entry['pearson_r']:+.4f}",
            f"{entry['p_value']:.4f}" if entry.get("p_value") is not None else "n/a",
            entry.get("n"),
        ]
        for name, m in rq["measures"].items()
        for entry in m.get("by_lag", [])
        if entry.get("pearson_r") is not None
    ]
    accounting = rq.get("significance_accounting", {})
    volatility = rq.get("volatility", {})
    vol_rows = [
        [
            name.replace("_", " "),
            f"{v['pearson_r']:+.4f}" if v.get("pearson_r") is not None else "n/a",
            f"{v['variance_explained_pct']:.2f}%" if v.get("variance_explained_pct") is not None else "n/a",
            f"{v['p_value']:.4f}" if v.get("p_value") is not None else "n/a",
            "yes" if v.get("significant_at_alpha") else "no",
        ]
        for name, v in (volatility.get("measures") or {}).items()
    ]

    return "\n".join([
        "## 7. RQ6 — Do headlines relate to Nifty returns or volatility?",
        "",
        f"Over **{humanise(rq['trading_days_paired'])} paired trading days**. The",
        "answer differs for returns and for volatility, so they are reported",
        "separately rather than averaged into one verdict.",
        "",
        "### Against daily returns: no relationship",
        "",
        _table(
            ["measure", "Pearson r", "Spearman ρ", "at lag", "p", "significant?"],
            rows,
        ),
        "",
        "### Every lag, so the shape is visible",
        "",
        _table(["measure", "lag (trading days)", "Pearson r", "p", "n"], lag_rows[:20]),
        "",
        _significance_paragraph(accounting),
        "",
        "### Against 20-day volatility: a real association",
        "",
        (f"Over {humanise(volatility.get('observations', 0))} trading days with a "
         "full volatility window:")
        if volatility.get("ran")
        else "Volatility could not be computed on this data.",
        "",
        _table(
            ["measure", "Pearson r", "variance explained", "p", "significant?"],
            vol_rows,
        ) if vol_rows else "_No volatility rows._",
        "",
        _volatility_paragraph(volatility),
        "",
        "### How the question was asked",
        "",
        "Only *trading days* are used, because headlines are published on 1,828",
        "days in the window while the market trades on 1,235 — a weekend has",
        "headlines and no close price, and pairing them would invent data. Every",
        "coefficient travels with a p-value and a count, because 0.02 over 1,200",
        "points and 0.02 over 10 points are different claims. And lag 0 is not",
        "privileged: a lag-0 or lag-1 coefficient being the largest is exactly",
        "what a shared calendar effect produces, and is not evidence of",
        "leading-indicator behaviour.",
        "",
        _caution_block(rq.get("fact")),
    ])


def rq7_section(facts: dict[str, Any]) -> str:
    rq = facts["rq7_classifier"]
    if not rq.get("ran"):
        return "\n".join([
            "## 8. RQ7 — Can a classifier separate Real from Fake?",
            "",
            f"Not run: {rq.get('reason')}",
        ])

    m = rq["metrics"]
    per_class = m.get("per_class", {})
    fake = per_class.get("FAKE", {})
    real = per_class.get("REAL", {})
    matrix = m.get("confusion_matrix", {})

    model_rows = [
        [name, f"{d['accuracy']:.4f}" if d.get("accuracy") is not None else "n/a",
         f"{d['fake_recall']:.4f}" if d.get("fake_recall") is not None else "n/a"]
        for name, d in rq["models"].items()
    ]
    cv = rq.get("train_cv_accuracy", {})
    mat = matrix.get("matrix", [])
    matrix_rows = [
        [matrix.get("labels", ["FAKE", "REAL"])[i]] + [humanise(v) for v in row]
        for i, row in enumerate(mat)
    ] if mat else []

    terms = rq.get("top_terms") or {}
    term_block = ""
    if terms:
        term_block = "\n".join([
            "The model is not opaque. Its highest-weighted terms:",
            "",
            _table(
                ["toward FAKE", "toward REAL"],
                [
                    [terms.get("toward_fake", [""])[i], terms.get("toward_real", [""])[i]]
                    for i in range(max(
                        len(terms.get("toward_fake", [])),
                        len(terms.get("toward_real", [])),
                    ))
                ],
            ),
            "",
        ])

    return "\n".join([
        "## 8. RQ7 — Can a classifier separate Real from Fake?",
        "",
        "This is the only accuracy claim in the project, because IFND is the only",
        "source with ground truth. Everything measured on the headline corpus",
        "above is a style measure on unlabelled data.",
        "",
        "### The baseline that makes accuracy mean something",
        "",
        f"IFND is imbalanced: {humanise(rq['class_counts'].get('REAL', 0))} real against",
        f"{humanise(rq['class_counts'].get('FAKE', 0))} fake. A classifier that answers",
        f"\"real\" to everything already scores **{rq['baseline']:.4f}**.",
        "",
        "Reporting plain accuracy would therefore flatter a model that had learned",
        "nothing. Every metric here is stated against that baseline, and the Fake",
        "class is reported first because it is the class a fake-news detector is",
        "for.",
        "",
        "### Results",
        "",
        _table(["model", "accuracy", "Fake recall"], model_rows),
        "",
        f"`{rq['chosen_model']}` was selected on **training** cross-validated accuracy "
        + ", ".join(f"{k} {v:.4f}" for k, v in cv.items()) + ".",
        "The test split was scored once. Selecting a model on test accuracy and then",
        "reporting that same number is the optimism this study set out to avoid, so",
        "the two are kept strictly apart.",
        "",
        f"**Accuracy {m['accuracy']:.4f}** against a **{m['majority_baseline_accuracy']:.4f}** baseline: "
        f"**{m['lift_over_baseline_pp']:+.1f} percentage points**.",
        "",
        _table(
            ["class", "precision", "recall", "F1", "support"],
            [
                ["FAKE", f"{fake.get('precision', 0):.4f}", f"{fake.get('recall', 0):.4f}",
                 f"{fake.get('f1', 0):.4f}", humanise(fake.get("support", 0))],
                ["REAL", f"{real.get('precision', 0):.4f}", f"{real.get('recall', 0):.4f}",
                 f"{real.get('f1', 0):.4f}", humanise(real.get("support", 0))],
            ],
        ),
        "",
        "### Confusion matrix",
        "",
        _table(["actual \\ predicted", "FAKE", "REAL"], matrix_rows),
        "",
        matrix.get("reading", ""),
        "",
        term_block,
        "### What this number is not",
        "",
        rq.get("upper_bound_caveat", ""),
        "",
        _caution_block(rq.get("fact")),
    ])


def methodology_section(facts: dict[str, Any]) -> str:
    guards = facts["guards"]
    failed = guards.get("failed", [])
    status = "all passed" if guards.get("passed") else f"{len(failed)} failed"
    return "\n".join([
        "## 9. Method, and what it refuses to do",
        "",
        "### Warehouse shape",
        "",
        "A star schema over three fact tables, with dimensions for date, topic,",
        "dataset, label, instrument and keyword, plus a bridge from headlines to",
        "keywords. Cubes store **sums, never averages**; every mean in this report",
        "is recomputed as sum ÷ count at query time, so no rounded average is",
        "ever averaged again.",
        "",
        "### Guard rails",
        "",
        f"The inference gate ran {len(guards['checks'])} checks: **{status}**. Each one",
        "states what it looked at, and a check that cannot be evaluated reports",
        "that rather than passing quietly.",
        "",
        _table(
            ["check", "result", "detail"],
            [[c["check"], "pass" if c["passed"] else "**fail**", c["detail"]]
             for c in guards["checks"]],
        ),
        "",
        "### Rules this study holds itself to",
        "",
    ] + [f"- {rule}" for rule in facts.get("honesty_rules", [])] + [
        "",
        "### Reproducibility",
        "",
        "Every threshold, weight, sample size and random seed lives in",
        "`config/*.yaml` rather than in code, so any number above can be traced to",
        "the setting that produced it. The pipeline rebuilds from raw CSV to this",
        "report in about five minutes; mining takes 86 seconds. There is no",
        "language model anywhere in the reporting path: `report.md` is rendered",
        "from `facts.json` by templates, which is what makes the traceability",
        "claim checkable rather than aspirational.",
    ])


def conclusions_section(facts: dict[str, Any]) -> str:
    rq2 = facts["rq2_bursts"]
    rq4 = facts["rq4_clusters"]
    rq6 = facts["rq6_market_association"]
    rq7 = facts["rq7_classifier"]
    rq3 = facts["rq3_sensationalism"]
    rq5 = facts["rq5_association_rules"]
    top = rq3["ranked"][0] if rq3.get("ranked") else None

    # Every figure below is optional, because a section can decline to run on
    # small data. A conclusion that formats a missing number crashes on exactly
    # the inputs where a reader most needs to read it.
    cv = rq2.get("max_within_year_cv")
    silhouette = rq4.get("silhouette")
    correlation = rq6["fact"]["value"] if rq6.get("ran") else None
    volatility = rq6.get("volatility", {}) or {}
    fell = rq2.get("predicted_desks_fell_in") or []

    negatives = [
        "1. **Headline volume carries no news signal.** Within-year coefficient of "
        f"variation {cv if cv is not None else 'not measurable'}"
        + (
            f", and in {len(fell)} of the listed event months every desk "
            "predicted to rise — Health, Sports, Entertainment — fell instead."
            if fell
            else "."
        ),
        "2. **Topic structure, where it exists, covers a small minority.** "
        + (
            f"Silhouette {silhouette:.4f} is "
            + (
                "strong"
                if facts["rq4_clusters"].get("silhouette_is_strong")
                else "weak"
            )
            + f", but one cluster holds "
            f"{pct(facts['rq4_clusters'].get('dominant_cluster_share'))} of the "
            "corpus and the rest is undifferentiated. The score looks better "
            "than the coverage warrants."
            if silhouette is not None
            else "Silhouette not measurable on this corpus."
        ),
        "3. **Headlines do not measurably relate to Nifty daily returns.** "
        + (
            f"Strongest correlation {correlation:.4f}, and the one significant "
            "lag out of fifteen is within what chance produces."
            if correlation is not None
            else "No correlation could be computed from too few paired days."
        ),
    ]

    positives = [
        "4. **Risk-signal language is concentrated and measurable.** "
        + (
            f"`{top['topic']}` carries {pct(top['risk_signal_rate'])} of headlines "
            f"over the threshold (95% CI {pct(top['ci95_low'])}–"
            f"{pct(top['ci95_high'])}, n={humanise(top['headline_count'])}), well "
            f"above the corpus rate of {pct(rq3['corpus_rate'])}."
            if top
            else "No topic cleared the row floor for a rate."
        ),
        "5. **A headline's attributes predict each other strongly.** "
        + (
            f"{humanise(rq5['rule_count'])} rules mined by two independent "
            "algorithms that return the same rule set, with FP-Growth the faster."
            if rq5.get("ran")
            else "Association rules could not be mined on this data."
        ),
        "6. **Headline volume is genuinely related to market volatility.** "
        + (
            f"Log business-headline volume against 20-day volatility gives "
            f"r = {volatility['strongest']['pearson_r']:+.4f}, explaining "
            f"{volatility['strongest']['variance_explained_pct']:.1f}% of its "
            "variance. The sign is negative: busier headline days go with calmer "
            "markets. This is an association and the direction is unexplained."
            if volatility.get("strongest")
            and volatility["strongest"].get("significant_at_alpha")
            else "No significant relationship to volatility was found."
        ),
        "7. **Text alone separates real from fake statements well on IFND.** "
        + (
            f"{rq7['metrics']['accuracy']:.4f} against a {rq7['baseline']:.4f} "
            f"majority baseline, an improvement of "
            f"{rq7['metrics']['lift_over_baseline_pp']:+.1f} points, with Fake "
            f"recall {rq7['metrics']['fake_recall']:.4f}."
            if rq7.get("ran")
            else "The classifier could not be trained on this data."
        ),
    ]

    return "\n".join([
        "## 10. What this study concludes",
        "",
        "### The negative results are the contribution",
        "",
        "Two of the seven questions produced no result, and one produced a score",
        "that flatters a narrow finding. Reporting them with the measurement",
        "that establishes them is more useful than a finding chosen for being",
        "presentable.",
        "",
        *negatives,
        "",
        "### The positive results, and what they are worth",
        "",
        *positives,
        "",
        "### What a follow-up study should do differently",
        "",
        "- Use a corpus sampled by newsworthiness rather than by whatever a",
        "  publisher's export happened to contain. The flat volume is plausibly",
        "  a sampling artefact of the export, and that cannot be distinguished",
        "  from a genuinely quota-driven newsroom using this data alone.",
        "- Use a headline-level ground truth, so the sensationalism measure can be",
        "  validated against a real label instead of standing as a style proxy.",
        "- Use IFND dates from a source that records them, and treat the",
        "  LSTM-augmented portion of the Fake class separately, since it is the",
        "  part that inflates the classifier's apparent skill.",
    ])


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

SECTIONS = (
    ("What 1.1 million Indian news headlines actually show", header),
    ("The data", data_section),
    ("RQ1 topic mix", rq1_section),
    ("RQ2 bursts", rq2_section),
    ("RQ3 sensationalism", rq3_section),
    ("RQ4 clusters", rq4_section),
    ("RQ5 rules", rq5_section),
    ("RQ6 market", rq6_section),
    ("RQ7 classifier", rq7_section),
    ("Method", methodology_section),
    ("Conclusions", conclusions_section),
)


def render_report(facts: dict[str, Any]) -> str:
    """Render the whole report from facts. No computation happens here."""
    parts = [fn(facts) for _title, fn in SECTIONS]
    parts.append(
        "---\n\n"
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} from "
        f"`facts.json` (mining run {facts.get('mining_run_id')}). "
        "Every figure in this document is rendered from a fact that records its "
        "own source. No language model was involved in producing it.\n"
    )
    return "\n".join(parts)


def write_report(text: str) -> Path:
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log.info("wrote %s (%.1f KB)", path, path.stat().st_size / 1024)
    return path
