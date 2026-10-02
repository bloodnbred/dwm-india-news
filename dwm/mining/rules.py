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
    take = min(sample, total)

    rows = con.execute(
        f"""
        SELECT {selected}
        FROM fact_headline f
        JOIN dim_date d  ON d.date_key = f.date_key
        JOIN dim_topic t ON t.topic_key = f.topic_key
        WHERE f.in_window
        USING SAMPLE reservoir({take} ROWS) REPEATABLE ({seed})
        """
    ).fetchall()

    transactions = [frozenset(str(v) for v in r) for r in rows]
    sizes = [len(t) for t in transactions]
    distinct = len({frozenset(t) for t in transactions})
    log.info(
        "attribute transactions: %s sampled, mean items %.2f, %s distinct",
        human_int(len(transactions)), (sum(sizes) / len(sizes)) if sizes else 0,
        human_int(distinct),
    )
    return {
        "transactions": transactions,
        "items": items,
        "sampled": take,
        "corpus_total": total,
        "mean_items": round(sum(sizes) / len(sizes), 3) if sizes else None,
        "min_items": min(sizes) if sizes else 0,
        "max_items": max(sizes) if sizes else 0,
        "distinct_transactions": distinct,
        "sparse": (sum(sizes) / len(sizes) < 2) if sizes else True,
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

    total = con.execute(
        "SELECT count(DISTINCT headline_id) FROM bridge_headline_keyword"
    ).fetchone()[0]
    take = min(sample, total)
    rows = con.execute(
        f"""
        SELECT b.headline_id, list(k.term ORDER BY k.term)
        FROM bridge_headline_keyword b
        JOIN dim_keyword k ON k.keyword_key = b.keyword_key
        JOIN fact_headline f ON f.headline_id = b.headline_id
        WHERE f.in_window
        GROUP BY 1
        USING SAMPLE reservoir({take} ROWS) REPEATABLE ({seed})
        """
    ).fetchall()
    transactions = [frozenset(r[1]) for r in rows]
    sizes = [len(t) for t in transactions]
    log.info(
        "keyword transactions: %s sampled, mean items %.2f",
        human_int(len(transactions)), (sum(sizes) / len(sizes)) if sizes else 0,
    )
    return {
        "transactions": transactions,
        "sampled": len(transactions),
        "mean_items": round(sum(sizes) / len(sizes), 3) if sizes else None,
        "max_items": max(sizes) if sizes else 0,
        "sparse": (sum(sizes) / len(sizes) < 2.5) if sizes else True,
    }


def _rules_to_records(rules: Any) -> list[dict[str, Any]]:
    return [
        {
            "antecedent": sorted(str(x) for x in r[0]),
            "consequent": sorted(str(x) for x in r[1]),
            "support": round(float(r[2]), 6),
            "confidence": round(float(r[3]), 6),
            "leverage": round(float(r[4]), 6),
            "lift": round(float(r[5]), 6),
            "consequence": round(float(r[6]), 6),
            "is_informative": float(r[3]) > float(r[2]),
        }
        for r in rules
    ]


def _run_apriori(
    transactions: list[frozenset[str]], min_support: float, min_confidence: float, max_len: int
) -> tuple[list[dict[str, Any]], float]:
    from mlxtend.frequent_patterns import apriori, association_rules

    start = time.perf_counter()
    frame = _to_frame(transactions)
    # mlxtend 0.25 dropped `use_ylib`; the flag is gone from both signatures.
    frequent = apriori(frame, min_support=min_support, max_len=max_len)
    elapsed = time.perf_counter() - start
    if frequent.empty:
        return [], elapsed
    rules = association_rules(
        frequent, metric="confidence", min_threshold=min_confidence
    )
    if rules.empty:
        return [], elapsed
    return _rules_to_records(rules.values), elapsed


def _run_fpgrowth(
    transactions: list[frozenset[str]], min_support: float, min_confidence: float, max_len: int
) -> tuple[list[dict[str, Any]], float]:
    from mlxtend.frequent_patterns import association_rules, fpgrowth

    start = time.perf_counter()
    frame = _to_frame(transactions)
    # Same itemset search as apriori, so a difference in the resulting rules
    # would mean a bug rather than a different answer.
    frequent = fpgrowth(frame, min_support=min_support, max_len=max_len)
    elapsed = time.perf_counter() - start
    if frequent.empty:
        return [], elapsed
    rules = association_rules(
        frequent, metric="confidence", min_threshold=min_confidence
    )
    if rules.empty:
        return [], elapsed
    return _rules_to_records(rules.values), elapsed


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

    ranked = sorted(
        apriori_rules, key=lambda r: (-r["lift"], -r["confidence"])
    )
    return {
        "ran": True,
        "source": "attributes",
        "transactions": built,
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
        "top_rules": ranked[:25],
        "informative_rules": [r for r in ranked if r["is_informative"]][:25],
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
    ranked = sorted(rules, key=lambda r: -r["lift"])[:25]
    return {
        "ran": True,
        "source": "keywords",
        "transactions": built,
        "rule_count": len(rules),
        "seconds": round(seconds, 4),
        "top_rules": ranked,
        "caveat": (
            f"Mean {built['mean_items']} items per transaction. The 300-term "
            "vocabulary is dominated by functional words, so these "
            "transactions are close to empty and the rules are weak by "
            "construction. Reported for completeness, not as a finding."
        ) if built["sparse"] else None,
    }


def run_rules(
    con: duckdb.DuckDBPyConnection, config: dict[str, Any]
) -> dict[str, Any]:
    return {
        "attribute_rules": mine_rules(con, config),
        "keyword_rules": mine_keyword_rules(con, config),
    }
