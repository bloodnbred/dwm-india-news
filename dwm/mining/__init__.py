"""Mining stage (Phases 5-6): trends, bursts, clustering, rules, classifier.

Not built in the first chunk. Per BLUEPRINT section 3 the questions are:
    1. topic mix change over the window
    2. which months spike, and which known events they coincide with
    3. which categories use sensational or negative language
    4. natural topic clusters (TF-IDF + K-Means)
    5. co-occurrence rules (Apriori and FP-Growth, runtime compared)
    6. business sentiment vs Nifty returns, lagged. Association, not causation
    7. classifier Real vs Fake on labelled IFND vs the majority baseline

On the unlabelled TOI headlines the output is a "risk-signal rate", never a
"fake news rate" (BLUEPRINT section 3, honesty rule).
"""

from __future__ import annotations

from typing import Any

from dwm.config import Settings

PHASE = "Phases 5-6 (mining)"


def run_mining(settings: Settings) -> dict[str, Any]:
    raise NotImplementedError(f"{PHASE} is not built yet.")
