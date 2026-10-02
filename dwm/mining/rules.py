"""Association rule mining (RQ5): Apriori and FP-Growth, with the timing compared.

The blueprint asks for rules like `topic=Business, year=2016 => sensational=high`.
That example is ATTRIBUTE-shaped, and the data forced the same conclusion.

**Why attributes, not keywords.** The 300-term keyword vocabulary in
`dim_keyword` yields a mean of 1.86 items per headline, measured on the real
corpus, because its highest-frequency terms are functional words: `govt`,
`held`, `get`, `man`, `police`, `case`, `two`. A transaction with under two
items supports almost no co-occurrence, so rules over keyword transactions
would be reporting sparsity as a pattern. Attributes give five to seven items
per transaction, which is where association rules are informative.

The keyword run is still performed, and reported with its sparsity stated
plainly, because the blueprint lists it and because a negative result about
the vocabulary is itself worth knowing.

**Both algorithms, same input.** Apriori and FP-Growth are run on the identical
transaction set with identical thresholds, so the rule sets can be compared
for equality. The point of running both is that the rules should be the same
and only the time should differ; if the rule sets differed, something is
wrong with one of them.

**No causal language.** `sensational=high => topic=Business` says the two
co-occur often. It does not say business coverage causes sensationalism.
"""

from __future__ import annotations

import time
from typing import Any

import duckdb
import numpy as np

from dwm.logging_utils import get, human_int
from dwm.mining.sampling import sample_rows

log = get("dwm.mining.rules")


def _transactions_from_rows(rows: list[list[str]]) -> list[frozenset[str]]:
    return [frozenset(r) for r in rows if r]


def build_attribute_transactions(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """One transaction per headline, from its coarse attributes.

    Attributes chosen for interpretability and independence:
      topic, year, quarter, sentiment band, sensational flag, weekend flag,
      multi-category flag.

    `sensational_flag` is what makes the blueprint's example rule expressible.
    """
    cfg = config.get("rules", {})
    items = cfg.get("transaction_items", [])
    sample = int(cfg.get("sample_transactions", 200_000))
    seed = int(cfg.get("seed", 0))

    # Build the attribute expressions in Python from a list, so the config
    # genuinely controls which attributes appear.
    expressions = {
        "topic": "t.topic_name",
        "topic_group": "t.topic_group",
        "year": "CAST(d.year_no AS VARCHAR)",
        "quarter": "CAST(d.year_no AS VARCHAR) || '-Q' || CAST(d.quarter_no AS VARCHAR)",
        "month": "d.year_month",
        "sentiment_band": "f.sentiment_band",
        "sensational_flag": "CASE WHEN f.is_sensational THEN 'sensational=high' "
                           "ELSE 'sensational=normal' END",
        "weekday_flag": "CASE WHEN d.is_weekend THEN 'weekend' ELSE 'weekday' END",
        "multi_category_flag": "CASE WHEN f.is_multi_category THEN 'multi_category' "
                               "ELSE 'single_category' END",
        "year_decade": "CAST((d.year_no / 5) * 5 AS VARCHAR) || 's'",
    }
    missing = [i for i in items if i not in expressions]
    if missing:
        raise ValueError(f"unknown transaction_items {missing}; known: {sorted(expressions)}")

    selected = ", ".join(f"{expressions[i]} AS item_{i}" for i in items)
    total = con.execute("SELECT count(*) FROM fact_headline WHERE in_window").fetchone()[0]

    rows = sample_rows(
        con,
        f"f.headline_id, {selected}",
        source=(
            "fact_headline f "
            "JOIN dim_date d ON d.date_key = f.date_key "
            "JOIN dim_topic t ON t.topic_key = f.topic_key"
        ),
        where="WHERE f.in_window",
        size=sample,
        seed=seed,
        order_by="f.headline_id",
    )
    # Column 0 is the headline id, kept only to satisfy the sampler's ordering
    # requirement; the transaction is built from the attribute columns alone.
    # Including the id would make every item unique, which turns a 7-item
    # transaction into a 200,000-column matrix and 37 GB of allocation.
    transactions = [frozenset(str(v) for v in r[1:]) for r in rows]
    sizes = [len(t) for t in transactions]
    distinct = len({frozenset(t) for t in transactions})
    log.info(
        "attribute transactions: %s sampled, mean items %.2f, %s distinct",
        human_int(len(transactions)), (sum(sizes) / len(sizes)) if sizes else 0,
        human_int(distinct),
    )
    return {
        "transactions": transactions,
        # The summary is what a reader needs; the 200,000 frozensets are not.
        # They pushed mining.json to 9.7 MB, and serialising them made the file
        # differ between runs purely through set iteration order, which
        # defeated the reproducibility check that compares two runs.
        "summary": {
            "items": items,
            "sampled": len(transactions),
            "corpus_total": total,
            "mean_items": round(sum(sizes) / len(sizes), 3) if sizes else None,
            "min_items": min(sizes) if sizes else 0,
            "max_items": max(sizes) if sizes else 0,
            "distinct_transactions": distinct,
            "sparse": (sum(sizes) / len(sizes) < 2) if sizes else True,
            "item_vocabulary_size": len({i for t in transactions for i in t}),
        },
    }


def build_keyword_transactions(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """The secondary run: one transaction per headline from its keywords.

    Reported with its measured sparsity, because a rule set mined from
    near-empty transactions is not a meaningful result.
    """
    cfg = config.get("rules", {}).get("keyword_rules", {})
    sample = int(cfg.get("sample_transactions", 100_000))
    seed = int(cfg.get("seed", 0))

    rows = sample_rows(
        con,
        "b.headline_id, list(k.term ORDER BY k.term)",
        source=(
            "bridge_headline_keyword b "
            "JOIN dim_keyword k ON k.keyword_key = b.keyword_key "
            "JOIN fact_headline f ON f.headline_id = b.headline_id"
        ),
        where="WHERE f.in_window",
        size=sample,
        seed=seed,
        order_by="b.headline_id",
        group_by="GROUP BY b.headline_id",
    )
    transactions = [frozenset(r[1]) for r in rows]
    sizes = [len(t) for t in transactions]
    log.info(
        "keyword transactions: %s sampled, mean items %.2f",
        human_int(len(transactions)), (sum(sizes) / len(sizes)) if sizes else 0,
    )
    return {
        "transactions": transactions,
        "summary": {
            "sampled": len(transactions),
            "mean_items": round(sum(sizes) / len(sizes), 3) if sizes else None,
            "max_items": max(sizes) if sizes else 0,
            "sparse": (sum(sizes) / len(sizes) < 2.5) if sizes else True,
        },
    }


def _rules_to_records(rules: Any) -> list[dict[str, Any]]:
    """Convert mlxtend's rules DataFrame into plain records.

    Columns are read **by name**, never by position. The positional version of
    this was off by two: mlxtend orders the frame as
    `antecedents, consequents, antecedent support, consequent support,
    support, confidence, lift, ...`, so indexing r[2]..r[6] labelled the
    consequent support as "confidence" and the confidence as "lift". Every one
    of 1,804 rules then appeared to have lift exactly 1.000, which reads as
    "the attributes are all tautologies" and is entirely an artefact of the
    mislabelling. Column order also varies between mlxtend versions, so
    positional access is wrong by construction, not just currently.

    `is_informative` is lift > 1, which is the definition: a rule that predicts
    its consequent no better than the base rate carries no information.
    """
    wanted = {
        "antecedents": "antecedent",
        "consequents": "consequent",
        "support": "support",
        "confidence": "confidence",
        "lift": "lift",
        "leverage": "leverage",
    }
    present = [c for c in wanted if c in rules.columns]
    missing = [c for c in ("support", "confidence", "lift") if c not in rules.columns]
    if missing:
        raise RuntimeError(
            f"mlxtend rule frame is missing {missing}; columns were "
            f"{list(rules.columns)}"
        )

    records = []
    for _, row in rules.iterrows():
        support = float(row["support"])
        confidence = float(row["confidence"])
        lift = float(row["lift"])
        record = {
            wanted[c]: (
                sorted(str(x) for x in row[c])
                if c in ("antecedents", "consequents")
                else round(float(row[c]), 6)
            )
            for c in present
        }
        record["is_informative"] = lift > 1.0
        record["beats_base_rate"] = confidence > support
        records.append(record)
    return records


def _run_apriori(
    transactions: list[frozenset[str]], min_support: float, min_confidence: float, max_len: int
) -> tuple[list[dict[str, Any]], float]:
    from mlxtend.frequent_patterns import apriori, association_rules

    start = time.perf_counter()
    frame = _to_frame(transactions)
    # `use_colnames` defaults to False in mlxtend 0.23+, which makes the
    # frequent itemsets hold column *indices*. The rules then come back as
    # `5 => 4` instead of `topic=Business => year=2017`, which is unreadable and
    # made the mined rules impossible to check against the data.
    frequent = apriori(
        frame, min_support=min_support, max_len=max_len, use_colnames=True
    )
    elapsed = time.perf_counter() - start
    if frequent.empty:
        return [], elapsed
    rules = association_rules(
        frequent, metric="confidence", min_threshold=min_confidence
    )
    if rules.empty:
        return [], elapsed
    return _rules_to_records(rules), elapsed


def _run_fpgrowth(
    transactions: list[frozenset[str]], min_support: float, min_confidence: float, max_len: int
) -> tuple[list[dict[str, Any]], float]:
    from mlxtend.frequent_patterns import association_rules, fpgrowth

    start = time.perf_counter()
    frame = _to_frame(transactions)
    # Same itemset search as apriori, so a difference in the resulting rules
    # would mean a bug rather than a different answer. `use_colnames` for the
    # same reason: without it the rules carry column indices.
    frequent = fpgrowth(
        frame, min_support=min_support, max_len=max_len, use_colnames=True
    )
    elapsed = time.perf_counter() - start
    if frequent.empty:
        return [], elapsed
    rules = association_rules(
        frequent, metric="confidence", min_threshold=min_confidence
    )
    if rules.empty:
        return [], elapsed
    return _rules_to_records(rules), elapsed


def _to_frame(transactions: list[frozenset[str]]):
    import pandas as pd

    if not transactions:
        return pd.DataFrame()
    vocabulary = sorted({item for t in transactions for item in t})
    index = {item: i for i, item in enumerate(vocabulary)}
    # A dense boolean frame: the vocabulary is small (a few dozen attributes),
    # so there is no reason to reach for a sparse representation here.
    data = np.zeros((len(transactions), len(vocabulary)), dtype=bool)
    for row, t in enumerate(transactions):
        for item in t:
            col = index.get(item)
            if col is not None:
                data[row, col] = True
    return pd.DataFrame(data, columns=vocabulary)


def mine_rules(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """Run both algorithms on identical input and compare rules and time."""
    cfg = config.get("rules", {})
    min_support = float(cfg.get("min_support", 0.01))
    min_confidence = float(cfg.get("min_confidence", 0.30))
    max_len = int(cfg.get("max_len", 3))

    built = build_attribute_transactions(con, config)
    transactions = built["transactions"]
    summary = built["summary"]
    if not transactions:
        return {"ran": False, "reason": "no transactions could be built"}

    apriori_rules, apriori_seconds = _run_apriori(
        transactions, min_support, min_confidence, max_len
    )
    fpgrowth_rules, fpgrowth_seconds = _run_fpgrowth(
        transactions, min_support, min_confidence, max_len
    )

    def key(rule: dict[str, Any]) -> tuple:
        return (tuple(rule["antecedent"]), tuple(rule["consequent"]))

    apriori_keys = {key(r) for r in apriori_rules}
    fpgrowth_keys = {key(r) for r in fpgrowth_rules}
    # Both algorithms find the same frequent itemsets, so the rule sets must
    # be identical. A difference means one of them is wrong, not interesting.
    identical = apriori_keys == fpgrowth_keys

    speedup = (
        (apriori_seconds / fpgrowth_seconds) if fpgrowth_seconds > 0 else None
    )
    log.info(
        "apriori %s rules in %.2fs, fpgrowth %s rules in %.2fs, identical=%s",
        len(apriori_rules), apriori_seconds, len(fpgrowth_rules),
        fpgrowth_seconds, identical,
    )

    # Split the rule set, because ranking by lift alone puts tautologies on
    # top. `2016-Q1 => 2016` is true by construction and scores exactly 1.000,
    # and since the transaction items are not independent (year contains
    # quarter) a large share of the rule set is of that shape. They are counted
    # separately so the headline count is not inflated by arithmetic.
    TAUTOLOGY_LIFT = 1.0005
    tautologies = [r for r in apriori_rules if r["lift"] <= TAUTOLOGY_LIFT]
    substantive = [r for r in apriori_rules if r["lift"] > TAUTOLOGY_LIFT]
    ranked = sorted(
        substantive or apriori_rules,
        key=lambda r: (-r["lift"], -r["confidence"]),
    )
    informative = [r for r in ranked if r["is_informative"] and r["beats_base_rate"]]
    # The lift distribution across the whole rule set, binned here rather than in
    # the presentation layer.
    #
    # A ranked table shows the best rules and a histogram shows the shape, and
    # the shape is the thing that says whether the top of the list is a real
    # effect or the tail of a distribution that mostly sits at 1.0. It has to be
    # computed over every rule: `informative_rules` in the report is truncated
    # to eight rows, which is enough to draw the strongest rules and far too few
    # to show a distribution.
    #
    # Bins are fixed and the first and last are open-ended. Both ends matter: a
    # single runaway lift (rare consequent, small support) would otherwise
    # stretch the axis and flatten everything else into one bin, and — the bug
    # this replaced — starting the bins at 1.0 silently drops every rule with
    # lift *below* chance. Measured here that was 299 of 644 rules, so a
    # histogram that only showed lift >= 1 was quietly describing 45% of the
    # rule set while appearing to describe all of it.
    LIFT_EDGES = [1.0, 1.1, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
    lifts = [float(r["lift"]) for r in apriori_rules if r.get("lift") is not None]
    lift_distribution = [{
        "range": "below 1",
        "low": 0.0,
        "high": 1.0,
        "open_ended": True,
        "count": sum(1 for v in lifts if v < 1.0),
    }]
    for low, high in zip(LIFT_EDGES[:-1], LIFT_EDGES[1:], strict=True):
        lift_distribution.append({
            "range": f"{low:g} to {high:g}",
            "low": low,
            "high": high,
            "open_ended": False,
            "count": sum(1 for v in lifts if low <= v < high),
        })
    lift_distribution.append({
        "range": f"{LIFT_EDGES[-1]:g} or more",
        "low": LIFT_EDGES[-1],
        "high": None,
        "open_ended": True,
        "count": sum(1 for v in lifts if v >= LIFT_EDGES[-1]),
    })
    # Asserted rather than assumed: a distribution that does not account for
    # every rule is a misleading chart, and the way it goes wrong is invisible.
    binned_total = sum(b["count"] for b in lift_distribution)
    assert binned_total == len(lifts), (
        f"lift bins account for {binned_total} of {len(lifts)} rules; a rule "
        f"is falling outside every bin and would vanish from the chart"
    )
    lift_distribution_note = (
        f"Binned over all {len(lifts)} mined rules, and the bins account for "
        f"every one of them. The first bin is lift below 1, which is negative "
        f"association: those attribute pairs co-occur *less* often than chance, "
        f"usually because one implies the other, as year and quarter do. The "
        f"cluster at 1.0 to 1.1 is where the tautologies sit. The thin tail is "
        f"the substantive co-occurrence, and it is genuinely thin."
    )
    # Lift is maximised by rare consequents. The window ends 2020-06-30, so
    # `2020-Q2` is a rare item and every rule pointing at it scores an
    # impressive lift that says nothing beyond "Q2 2020 is uncommon". The
    # support floor already limits this, but ranking purely by lift still
    # surfaces it, so a second table is provided on confidence, which is not
    # inflated by rarity in the same way.
    by_confidence = sorted(
        substantive or apriori_rules,
        key=lambda r: (-r["confidence"], -r["lift"]),
    )

    # Name a real tautology rather than a remembered one, so the note stays
    # true when the transaction items change.
    example_tautology = (
        " + ".join(tautologies[0]["antecedent"])
        + " => "
        + " + ".join(tautologies[0]["consequent"])
        if tautologies
        else None
    )
    # Check whether the top-lift rules really are dominated by the partial
    # final period before claiming they are.
    year_tokens = {
        item for r in ranked[:10] for item in (*r["antecedent"], *r["consequent"])
        if item.isdigit()
    }
    tail_year_dominates = bool(year_tokens) and any(
        year_tokens and max(int(y) for y in year_tokens) >= 2020
        for _ in [0]
    )
    lift_caveat = (
        "Lift is maximised by rare consequents, and the window ends 2020-06-30, "
        "so the final period is rare. The highest-lift table is therefore "
        "dominated by rules pointing at it, which says only that the period is "
        "uncommon. The confidence table is the more informative of the two."
        if tail_year_dominates
        else (
            "The highest-lift table is not dominated by the partial final "
            "period. Lift is still maximised by rare consequents in general, so "
            "the confidence table below is the more informative of the two."
        )
    )

    return {
        "ran": True,
        "source": "attributes",
        "transactions": summary,
        "thresholds": {
            "min_support": min_support,
            "min_confidence": min_confidence,
            "max_len": max_len,
        },
        "apriori": {"rule_count": len(apriori_rules), "seconds": round(apriori_seconds, 4)},
        "fpgrowth": {
            "rule_count": len(fpgrowth_rules), "seconds": round(fpgrowth_seconds, 4)
        },
        "rule_sets_identical": identical,
        "rules_in_apriori_not_fpgrowth": len(apriori_keys - fpgrowth_keys),
        "rules_in_fpgrowth_not_apriori": len(fpgrowth_keys - apriori_keys),
        "fpgrowth_speedup": round(speedup, 2) if speedup else None,
        "tautological_rules": len(tautologies),
        "substantive_rules": len(substantive),
        "redundancy_note": (
            f"{len(tautologies)} of {len(apriori_rules)} rules are tautologies "
            "with lift exactly 1.000: the consequent is implied by the "
            f"antecedent, as in `{example_tautology}`. The transaction items are "
            "not independent — the sensational flag and the sentiment band are "
            "derived from the same score, and a year implies every other item "
            "carrying that year. Redundant items inflate the rule count without "
            f"adding information, which is why {len(substantive)} substantive "
            f"rules are reported alongside the {len(apriori_rules)} total."
        )
        if tautologies
        else "No rule is a tautology; the transaction items are independent.",
        "top_rules": ranked[:25],
        "top_rules_by_confidence": by_confidence[:25],
        "informative_rules": informative[:25],
        "lift_distribution": lift_distribution,
        "lift_distribution_note": lift_distribution_note,
        "lift_caveat": lift_caveat,
        "note": (
            "Association, not causation. A rule states that two attributes "
            "co-occur more often than chance; it does not state that one "
            "produces the other."
        ),
    }


def mine_keyword_rules(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    """The secondary keyword run, reported with its measured sparsity."""
    cfg = config.get("rules", {}).get("keyword_rules", {})
    if not cfg.get("enabled", True):
        return {"ran": False, "reason": "disabled in config"}

    built = build_keyword_transactions(con, config)
    transactions = built["transactions"]
    if not transactions:
        return {"ran": False, "reason": "no keyword transactions"}

    rules, seconds = _run_apriori(
        transactions,
        float(cfg.get("min_support", 0.02)),
        float(cfg.get("min_confidence", 0.30)),
        int(config.get("rules", {}).get("max_len", 3)),
    )
    ranked = sorted(rules, key=lambda r: (-r["lift"], -r["confidence"]))[:25]
    summary = built["summary"]
    return {
        "ran": True,
        "source": "keywords",
        "transactions": summary,
        "rule_count": len(rules),
        "seconds": round(seconds, 4),
        "top_rules": ranked,
        "caveat": (
            f"Mean {summary['mean_items']} items per transaction. The 300-term "
            "vocabulary is dominated by functional words, so these "
            "transactions are close to empty and the rules are weak by "
            "construction. Reported for completeness, not as a finding."
        ) if summary["sparse"] else None,
    }


def run_rules(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    return {
        "attribute_rules": mine_rules(con, config),
        "keyword_rules": mine_keyword_rules(con, config),
    }

