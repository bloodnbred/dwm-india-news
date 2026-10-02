---
name: Vega Charts
description: Building Vega-Lite chart specs for this dashboard with Altair in Python. Use when adding or changing a chart, choosing a mark, sorting an axis, or debugging a spec that renders blank. Specs live in dwm/ui/charts.py.
---

# Vega-Lite charts

## Why the specs are in Python

Rendering a chart is not computing a finding, so putting the specs in
JavaScript would not break the "the dashboard computes nothing" rule. They are
in Python anyway, for two reasons that both paid for themselves:

1. **A malformed spec is a blank page with no stack trace.** Built here, it is a
   failing unit test. Built in JS, someone discovers it during a presentation.
2. **Six charts stay consistent.** One palette, one axis style, one set of rules,
   in one file. Charts built in three places drift immediately, and drift in a
   chart library looks like a subtle wrongness nobody can name.

The front end embeds a spec and nothing more. `dwm/ui/charts.py` builds,
`GET /ui/charts?theme=…` serves, `static/app.js` embeds.

## The sorting rule, which exists because of a bug

**A nominal axis in Vega-Lite is a set of unordered strings. Its default order is
whatever order the data arrives in.**

The RQ2 event-month chart used `sort="-x"` on its month axis, which ordered the
months by their *z-score*. The chart showed 2020-05 beside 2016-12 and read as a
chronological series that was not one. Nothing was technically wrong. It was
simply a lie about the data, drawn confidently.

So:

> Every nominal axis gets an explicit `sort=` list, ordered by the natural order
> of the **label**, never by a measure.

```python
months = _sorted_unique([r["month"] for r in rows])   # sorted by the label
alt.Y("month:N", sort=months, ...)
```

`_sorted_unique` exists for this and takes nothing but labels. There is
deliberately no helper that sorts by a value.

`tests/test_ui.py::test_the_event_month_chart_is_in_date_order` pins the
specific regression, and `test_nominal_axes_are_sorted_by_their_own_labels`
covers the general case.

## Shared helpers

Do not hand-roll axis config or colour scales. Use these, or a chart will not
match the other eight.

| Helper | For |
|---|---|
| `theme(name)` | the palette. Light or dark, never hardcoded |
| `_axis(t, title, **over)` | one axis style. `domain=False`, no axis line — the gridline is enough structure |
| `_config(t)` | transparent plot, quiet legend, no toolbar |
| `_named(yes, no, …)` | two-state colour as a **labelled** nominal field |
| `_label_state(rows, key, test, yes, no)` | attaches the readable state for `_named` |
| `_sorted_unique(values)` | the explicit axis order |
| `_spec(chart, t, height)` | applies config and serialises |

## Two-state colour is never a conditional

A conditional encoding with two colours and no labels produces a legend of two
unlabelled swatches, which tells the reader nothing. Naming the states turns the
same encoding into a sentence:

```python
rows = _label_state(rows, "z", lambda v: v < 0, "coverage fell", "coverage rose")
color=_named("coverage fell", "coverage rose", t["caution"], t["accent"])
```

The legend then reads `coverage fell` / `coverage rose`, which is the finding.

This is also version-stable. Vega-Lite's conditional API has changed shape
repeatedly — Altair 6 returns a plain dict from `alt.condition()`, which cannot
be titled — and a labelled nominal field works in every version.

## Altair 6 specifics that cost time

- **`mark_line(point=True, pointSize=…)` raises.** `MarkDef` has no
  `pointSize`. Layer `mark_line()` with `mark_point()` instead.
- **`mark_text(fontWeight=…)` raises.** `TextMarkDef` has no such parameter.
  Pass the CSS shorthand: `font="600 14px system-ui, sans-serif"`.
- **Do not pass an `AxisConfig` through `**`.** `alt.X("f:Q", **axis(...))`
  fails; use `axis=axis(...)`, which takes a plain dict.
- **Never `theme=None`.** In the Streamlit version that told the chart library to
  use *nothing* rather than follow the app theme, which is part of why charts
  rendered dark on a light page.

## Choosing a mark

| Claim | Mark |
|---|---|
| a rate with an interval | `mark_bar` + a `mark_rule` whisker for the CI |
| a rate against a benchmark | add a dashed `mark_rule` reference layer |
| a shape among points | `mark_circle` at low opacity, never connected |
| a proportion over time | `mark_area`, stacked `zero` |
| a ranked comparison | `mark_bar`, sorted by the label |
| a matrix of counts | `mark_rect` + a `mark_text` layer for the counts |

**Always draw the interval.** A bare percentage over tens of thousands of rows
implies a precision the measure does not have, and the whisker is the honest
part of the chart.

**A scatter is only for a claim about a cloud.** If the claim is a single
coefficient, draw the fitted line on the same points — a chart that disagreed
with the number beside it would be worse than no chart.

## Rules

- One finding per chart. If you cannot name it in a sentence, it is two charts.
- Every chart gets a `chart__sub` saying what it shows and a `chart__cap`
  saying what it does not.
- A chart with no data returns `{}`. The front end renders an explicit
  "unavailable" box, so "not measured" is never mistaken for "measured as zero".
- Colours must be theme tokens. `test_chart_palette_matches_the_css` will fail
  if the palettes drift.
- Validate before shipping: `tests/test_ui.py` builds and checks every spec in
  both themes.