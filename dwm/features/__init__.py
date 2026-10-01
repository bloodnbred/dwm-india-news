"""Feature stage (Phase 3): sentiment, sensationalism, counts, keywords.

Outputs, consumed by `dwm/warehouse` to build the fact tables:

    feat_headline        one row per cln_headline
    feat_statement       one row per cln_statement
    feat_market_daily    one row per cln_market_daily (returns, volatility)
    dim_keyword          the capped Apriori vocabulary
    bridge_headline_keyword   headline <-> keyword, many to many

Honesty note, enforced in the column names: these are STYLE measures. Over the
unlabelled TOI corpus the output is a risk-signal rate, never a fake-news
rate. Only IFND carries ground truth, and only the classifier in Phase 6 may
make an accuracy claim.
"""

from dwm.features.runner import run_features

__all__ = ["run_features"]
