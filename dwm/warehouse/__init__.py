"""Warehouse build stage (Phase 3): conformed dimensions, facts, bridge, cubes.

Not built in the first chunk. Planned outputs, per BLUEPRINT section 2:
    dim_date, dim_topic, dim_dataset, dim_label, dim_instrument
    fact_headline, fact_statement, fact_market_daily
    bridge_headline_keyword
    cube_month_topic, cube_year_topic, cube_topic_sentiment
"""

from __future__ import annotations

from typing import Any

from dwm.config import Settings

PHASE = "Phase 3 (warehouse)"


def run_build(settings: Settings) -> dict[str, Any]:
    raise NotImplementedError(f"{PHASE} is not built yet.")
