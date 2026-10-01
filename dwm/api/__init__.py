"""FastAPI backend (Phase 8).

Not built in the first chunk. The dashboard stays thin: Streamlit reads from
these endpoints and holds no logic of its own (BLUEPRINT section 1).
"""

from __future__ import annotations

from typing import Any

from dwm.config import Settings

PHASE = "Phase 8 (API)"


def run_api(settings: Settings) -> dict[str, Any]:
    raise NotImplementedError(f"{PHASE} is not built yet.")
