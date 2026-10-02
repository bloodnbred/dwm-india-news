"""OLAP stage (Phase 4): slice, dice, roll-up, drill-down, pivot, cube,
drill-across.

Built. `dwm/olap/operations.py` holds one named function per operation and
`python -m dwm olap --op <name>` runs one against the warehouse.
"""

from dwm.olap.operations import (
    DEFAULT_PARAMS,
    OPERATIONS,
    Result,
    cube_by_year_topic_band,
    dice_by_topic_and_year,
    drill_across_market_and_headlines,
    drill_down_to_month,
    list_operations,
    pivot_month_by_topic,
    roll_up_to_year,
    run_olap,
    run_operation,
    slice_by_topic,
    slice_by_year,
    top_n_months,
    topic_mix_over_time,
)

__all__ = [
    "DEFAULT_PARAMS",
    "OPERATIONS",
    "Result",
    "cube_by_year_topic_band",
    "dice_by_topic_and_year",
    "drill_across_market_and_headlines",
    "drill_down_to_month",
    "list_operations",
    "pivot_month_by_topic",
    "roll_up_to_year",
    "run_olap",
    "run_operation",
    "slice_by_topic",
    "slice_by_year",
    "topic_mix_over_time",
    "top_n_months",
]
