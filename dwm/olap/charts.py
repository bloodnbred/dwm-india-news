"""Vega-Lite specs for OLAP results, chosen from the shape of the data.

**One renderer, not ten charts.** Each of the ten operations returns a
cross-tabulation of a slightly different shape. Writing ten bespoke charts would
be ten places for them to drift and ten places for one to be wrong. Instead this
classifies the columns and picks a mark:

===============================  ==========================
Shape                            Chart
===============================  ==========================
temporal + many numerics         multi-line (a pivot table read as lines)
string label + numeric           horizontal bar, ranked
temporal + string label + num    stacked area over time
temporal + numeric               line
nothing plottable                none, and it says so
===============================  ==========================

The "says so" case matters. A renderer that silently returns an empty spec for a
shape it does not recognise produces a blank rectangle, which reads as a design
choice. It returns a reason instead, and the front end shows it.

Built with the same palette, axis style and container width as the main charts
in `dwm/ui/charts.py`, so an OLAP result does not look like a different website.
"""

from __future__ import annotations

from typing import Any

import altair as alt

from dwm.ui.charts import SERIES, _axis, _config

# Columns that are labels rather than measures.
_LABEL_HINTS = {
    "topic_name", "topic_group", "sentiment_band", "month_name", "measure",
    "year_month", "year_no", "month_no", "full_date", "label",
}

# Columns that are dimensions rather than measures.
_DIMENSION_HINTS = {"topic_name", "topic_group", "sentiment_band", "g_year",
                    "g_topic", "g_band", "is_trading_day"}

# Surrogate keys, never plottable. Present on the cube because it carries the
# group ids, and they mean nothing to a reader.
_DROP = {"g_year", "g_topic", "g_band", "topic_key", "date_key"}

# When several measures cannot share an axis, this is the one to plot.
_PRIMARY_MEASURES = ["headline_count", "measure_value", "sensational_count"]


def _is_temporal(name: str) -> bool:
    return name in {"year_month", "year_no", "month_no", "full_date", "month", "date"}


def _is_measure(name: str, rows: list[dict[str, Any]]) -> bool:
    if name in _DIMENSION_HINTS or name in _DROP:
        return False
    # A year number and a month number are *part of the axis*, not things to
    # plot. Left in the measure list they push a result over the "several
    # numeric columns" threshold and get drawn as their own lines, so
    # `top_months` rendered four series — two of them the calendar.
    if _is_temporal(name):
        return False
    # `headline_count` is the measure these cross-tabulations are *about*, so it
    # is never excluded. `measure_value` is excluded only when it duplicates it,
    # because `top_months` carries the same number in both columns and plotting
    # both would draw every total twice.
    if name == "measure_value" and any(
        isinstance(r.get("headline_count"), (int, float)) for r in rows
    ):
        return False
    for row in rows[:20]:
        value = row.get(name)
        if value is not None:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _natural_order(values: list[str]) -> list[str]:
    """Sort labels by their natural order, not alphabetically.

    `2017-08` sorts after `2017-07` alphabetically and before `2017-10`
    lexically-but-not-naturally, and `10` sorts before `9`. Every time a nominal
    axis carries these labels, the obvious default order is wrong — and a chart
    with months out of order looks chronological when it is not.
    """
    def key(value: str):
        parts = [int(p) for p in str(value).replace("-", " ").split() if p.isdigit()]
        return (parts, str(value))

    try:
        return sorted(set(values), key=key)
    except (TypeError, ValueError):
        return sorted(set(values))


def _spec(chart: Any, height: int = 300) -> dict[str, Any]:
    return (
        chart.properties(width="container", height=height)
        .configure(**_config(_TOKENS))
        .to_dict()
    )


# The OLAP panel follows the page theme rather than being built per theme, so a
# single neutral token set is used here and the front end re-tints on switch by
# re-requesting. Kept explicit rather than imported from a theme so this module
# does not depend on which theme is active server-side.
_TOKENS = {
    "grid": "#E3E3E8",
    "axis": "#C7C7CC",
    "muted": "#5E5E63",
    "accent": "#0062C4",
    "positive": "#157F3C",
    "caution": "#9A6200",
    "negative": "#C8102E",
    "surface": "#FFFFFF",
}


def _maxima(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for column in columns:
        values = [
            abs(float(r[column]))
            for r in rows
            if isinstance(r.get(column), (int, float)) and not isinstance(r.get(column), bool)
        ]
        if values:
            out[column] = max(values)
    return out


def _commensurable(
    rows: list[dict[str, Any]], columns: list[str], tolerance: float = 50.0
) -> bool:
    """Whether these measures can share one y-axis without disappearing.

    Counts in the thousands and a sentiment mean around zero differ by four
    orders of magnitude. Drawn together, the small series collapses onto the
    baseline and reads as a flat line at zero — which is not what it measures,
    and looks exactly like a null result.
    """
    maxima = [v for v in _maxima(rows, columns).values() if v > 0]
    if len(maxima) < 2:
        return False
    return max(maxima) / min(maxima) <= tolerance


def olap_chart_spec(
    operation: str,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> dict[str, Any]:
    """A chart for one OLAP result, or a reason there isn't one.

    Returns `{}` when there is nothing plottable, and `{"dwm_reason": ...}` when
    there are rows but no shape it recognises, so the front end can say which
    rather than drawing nothing.
    """
    if not rows:
        return {}

    names = [c for c in (columns or list(rows[0])) if c not in _DROP]
    temporal = next((c for c in names if _is_temporal(c)), None)
    numeric = [c for c in names if _is_measure(c, rows)]
    labels = [
        c for c in names
        if c not in numeric and not _is_temporal(c)
        and isinstance(rows[0].get(c), str)
    ]
    label = labels[0] if labels else None

    # -- pivot-shaped: a temporal axis with several measure columns ---------
    # Only when the measures are *commensurable*. A count of headlines and a
    # sentiment mean cannot share an axis: the mean flattens onto the baseline
    # and contributes nothing but a straight line at zero. Three operations
    # qualified on column count alone and drew four or six series each, most of
    # them invisible.
    if temporal and len(numeric) >= 3 and label is None and _commensurable(rows, numeric):
        series = numeric[:8]
        base = alt.Chart(alt.Data(values=rows)).encode(
            x=alt.X(f"{temporal}:N",
                    sort=_natural_order([str(r.get(temporal)) for r in rows]),
                    axis=_axis(_TOKENS, None, labelAngle=-45, tickCount=12,
                               gridColor=None)),
        )
        layers = [
            base.mark_line(strokeWidth=2, color=SERIES[i % len(SERIES)])
            .encode(
                y=alt.Y(f"{s}:Q", axis=_axis(_TOKENS, s.replace("_", " "))),
                tooltip=[
                    alt.Tooltip(f"{temporal}:N"),
                    alt.Tooltip(f"{s}:Q", format=","),
                ],
            )
            for i, s in enumerate(series)
        ]
        return _spec(alt.layer(*layers), height=320)

    # -- ranked bar: one label, one measure --------------------------------
    if label and len(numeric) == 1 and not temporal:
        measure = numeric[0]
        values = sorted(
            {str(r.get(label)) for r in rows},
            key=lambda v: -sum(r.get(measure) or 0 for r in rows if str(r.get(label)) == v),
        )
        chart = (
            alt.Chart(alt.Data(values=rows))
            .mark_bar(cornerRadiusEnd=3)
            .encode(
                y=alt.Y(f"{label}:N", sort=values, axis=_axis(_TOKENS, None, gridColor=None)),
                x=alt.X(f"{measure}:Q", axis=_axis(_TOKENS, measure.replace("_", " "))),
                color=alt.value(_TOKENS["accent"]),
                tooltip=[
                    alt.Tooltip(f"{label}:N"),
                    alt.Tooltip(f"{measure}:Q", format=","),
                ],
            )
        )
        return _spec(chart, height=max(160, 26 * len(values)))

    # -- stacked area: time against a dimension ----------------------------
    if temporal and label and numeric:
        groups = _natural_order([str(r.get(label)) for r in rows])
        chart = (
            alt.Chart(alt.Data(values=rows))
            .mark_area(opacity=0.85)
            .encode(
                x=alt.X(f"{temporal}:N",
                        sort=_natural_order([str(r.get(temporal)) for r in rows]),
                        axis=_axis(_TOKENS, None, labelAngle=-45, tickCount=12,
                                   gridColor=None)),
                y=alt.Y(f"{numeric[0]}:Q", stack="zero",
                        axis=_axis(_TOKENS, numeric[0].replace("_", " "))),
                color=alt.Color(
                    f"{label}:N",
                    scale=alt.Scale(domain=groups, range=SERIES),
                    legend=alt.Legend(orient="bottom", columns=6, title=None),
                ),
                order=alt.Order(f"{label}:N"),
                tooltip=[
                    alt.Tooltip(f"{temporal}:N"),
                    alt.Tooltip(f"{label}:N"),
                    alt.Tooltip(f"{numeric[0]}:Q", format=","),
                ],
            )
        )
        return _spec(chart, height=320)

    # -- a short ranked series is a bar, not a line ------------------------
    # `top_months` returns ten periods in rank order. A line implies a
    # trajectory through ten points that were chosen for being large, which is
    # exactly the wrong reading: it invites "volume peaked in December" from a
    # list whose tenth entry differs from its first by 1.3%. Enough points and
    # the line is right again, which is why this is a threshold on length rather
    # than a rule about the operation.
    if temporal and len(numeric) >= 1 and not label and len(rows) <= 15:
        measure = numeric[0]
        ordered = sorted(rows, key=lambda r: -(r.get(measure) or 0))
        labels_ = [str(r.get(temporal)) for r in ordered]
        chart = (
            alt.Chart(alt.Data(values=ordered))
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X(f"{temporal}:N", sort=labels_,
                        axis=_axis(_TOKENS, None, labelAngle=-45, gridColor=None)),
                y=alt.Y(f"{measure}:Q",
                        axis=_axis(_TOKENS, measure.replace("_", " "))),
                color=alt.value(_TOKENS["accent"]),
                tooltip=[
                    alt.Tooltip(f"{temporal}:N"),
                    alt.Tooltip(f"{measure}:Q", format=","),
                ],
            )
        )
        return _spec(chart, height=max(220, 30 * len(ordered)))

    # -- one measure alone, when the rest cannot share an axis ---------------
    # Reached when several numeric columns exist but their scales differ by
    # orders of magnitude. Plotting them together would flatten the small ones
    # onto the baseline and read as a null result, so the headline count — the
    # measure the cross-tabulation is actually about — is drawn on its own. The
    # caption says which one was chosen, because silently dropping five of six
    # columns is the kind of quiet omission this project does not do.
    if temporal and len(numeric) >= 1 and not label:
        primary = next(
            (c for c in _PRIMARY_MEASURES if c in numeric),
            max(numeric, key=lambda c: _maxima(rows, [c]).get(c, 0), default=numeric[0]),
        )
        chart = (
            alt.Chart(alt.Data(values=rows))
            .mark_line(strokeWidth=2, color=_TOKENS["accent"])
            .encode(
                x=alt.X(f"{temporal}:N",
                        sort=_natural_order([str(r.get(temporal)) for r in rows]),
                        axis=_axis(_TOKENS, None, labelAngle=-45, tickCount=12,
                                   gridColor=None)),
                y=alt.Y(f"{primary}:Q",
                        axis=_axis(_TOKENS, primary.replace("_", " "))),
                tooltip=[
                    alt.Tooltip(f"{temporal}:N"),
                    alt.Tooltip(f"{primary}:Q", format=","),
                ],
            )
        )
        spec = _spec(chart, height=280)
        if len(numeric) > 1:
            spec["dwm_caption"] = (
                f"plotting {primary.replace('_', ' ')} only — the other "
                f"{len(numeric) - 1} measures in this result are on scales too "
                f"far apart to share an axis"
            )
        return spec

    # -- group bars: one dimension, one measure ----------------------------
    if label and numeric:
        measure = numeric[0]
        groups = _natural_order([str(r.get(label)) for r in rows])
        chart = (
            alt.Chart(alt.Data(values=rows))
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X(f"{label}:N", sort=groups,
                        axis=_axis(_TOKENS, None, gridColor=None)),
                y=alt.Y(f"{measure}:Q",
                        axis=_axis(_TOKENS, measure.replace("_", " "))),
                color=alt.value(_TOKENS["accent"]),
                tooltip=[
                    alt.Tooltip(f"{label}:N"),
                    alt.Tooltip(f"{measure}:Q", format=","),
                ],
            )
        )
        return _spec(chart, height=280)

    return {
        "dwm_reason": (
            f"This result has {len(rows)} rows and {len(names)} columns, but no "
            f"combination the chart renderer recognises as a time series or a "
            f"ranking. The table below carries the answer."
        )
    }
