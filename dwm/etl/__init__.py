"""ETL stage: clean, dedupe, parse dates, map topics, apply the window.

Not implemented in the first build chunk (Phase 2). The stub exists so the CLI
contract is stable and `python -m dwm etl` fails with a clear message instead
of an ImportError.
"""

from __future__ import annotations

from typing import Any

from dwm.config import Settings

PHASE = "Phase 2 (ETL + dimensions)"


def run_etl(settings: Settings) -> dict[str, Any]:
    raise NotImplementedError(
        f"{PHASE} is not built yet. Expected outputs: cleaned tables, dim_date, "
        "dim_topic, dim_dataset, dim_label, dim_instrument."
    )
