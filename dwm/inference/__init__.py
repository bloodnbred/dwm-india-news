"""Inference stage (Phase 7): facts.json -> report.md.

Not built in the first chunk. Deterministic templates filled from SQL results,
no LLM, so every number in the report traces to a query
(BLUEPRINT section 1, inference decision).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dwm.config import Settings, reports_dir

PHASE = "Phase 7 (inference)"


def run_report(settings: Settings, out: Path | None = None) -> dict[str, Any]:
    raise NotImplementedError(f"{PHASE} is not built yet.")


def default_report_path() -> Path:
    return reports_dir() / "final_report.md"
