"""OLAP stage (Phase 4): slice, dice, roll-up, drill-down, pivot, cube, drill-across.

Not built in the first chunk.

Cube totals are stored as SUMS, never averages: sums roll up exactly, averages
do not, so an average must always be recomputed as sum/count at query time
(BLUEPRINT section 6).
"""

from __future__ import annotations

from typing import Any

from dwm.config import Settings

PHASE = "Phase 4 (OLAP)"


def run_olap(settings: Settings, operation: str | None = None) -> dict[str, Any]:
    raise NotImplementedError(
        f"{PHASE} is not built yet. Requested operation: {operation!r}."
    )
