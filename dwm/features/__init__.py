"""Feature engineering stage (Phase 3): word counts, sentiment, sensationalism.

Not built in the first chunk. Planned outputs, per BLUEPRINT section 2:
    - word count, char count, headline length
    - VADER sentiment: compound, positive, negative, neutral
    - sensationalism: ALL-CAPS token ratio, exclamation/question marks,
      superlative and urgency lexicon hits
    - top-N keywords per row for the Apriori transactions
"""

from __future__ import annotations

from typing import Any

from dwm.config import Settings

PHASE = "Phase 3 (features)"


def run_features(settings: Settings) -> dict[str, Any]:
    raise NotImplementedError(f"{PHASE} is not built yet.")
