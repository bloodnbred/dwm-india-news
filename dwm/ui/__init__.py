"""Presentation layer for the dashboard.

Kept separate from `dwm.api`, which owns the warehouse, and from
`dwm.inference`, which owns what the numbers mean. This package turns an
already-measured result into a picture. It measures nothing, and it may not
recompute a published number: if a chart here disagreed with `facts.json`, the
two would be unreviewed paths to the same figure and would drift.
"""
