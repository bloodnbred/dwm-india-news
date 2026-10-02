---
name: Dashboard Pages
description: The layout grammar for dashboard pages — the shell, the answer-first finding page, tables, tabs and controls. Use when adding a page, restructuring a section, or deciding what belongs above the fold. Code is in dashboard/static/app.js.
---

# Dashboard page composition

## The rule everything else serves

**The answer comes before the evidence.**

A panel that shows data and leaves the reader to infer the point has the
emphasis exactly backwards. Every finding page leads with the question, then the
answer at display size, then how we know, then what may not be claimed.

```
answer__q      RQ4 · Do the headlines cluster into topics on their own?
answer__text   Partly. Structure exists, but it covers a small minority.  [QUALIFIED]
               the supporting detail, if there is any
callout--evidence   How we know. …
callout--caution    Before you quote this. …
```

The caveat sits with the number it qualifies, never in a footnote. A caveat the
reader has to go looking for is a caveat that does not do its job.

## The shell

Fixed 250px sidebar, sticky 40px topbar, content capped at 1120px and centred.

**Sidebar**: brand, sections, then the seven research questions — visible only
while a finding page is open, so the nav reads as a numbered study rather than a
menu. Theme toggle and corpus size pinned to the bottom.

**Topbar**: page name and subtitle on the left; **live guard badge** and
provenance on the right. The badge is green when the inference gate passes and
turns red when a figure is missing its caution. That badge is the project's
differentiating feature rendered as a status light rather than a number in a
table — it should never be decorative or hidden behind a tab.

## The five sections

| Section | Job |
|---|---|
| **Overview** | the conclusions, before any chart. KPI row, then the seven outcomes as cards |
| **Findings** | one page per research question, answer-first |
| **Explore** | browse, monthly series, warehouse, OLAP, pipeline audit |
| **How it works** | guard rails, corrections, decisions, warehouse shape, rules |
| **Report** | the full `report.md` |

**How it works is where the rigour lives.** This is what separates the project
from a tutorial, and it used to be invisible. Keep it one click from anywhere,
and keep the four corrections intact — they are the strongest thing here.

## Overview

The KPI row is four cards, equal weight: headlines analysed, questions with a
result, months spiking on volume, classifier accuracy. Then the seven outcomes.

Order the outcomes by **how surprising they are**, not by RQ number. A null
result belongs near the top: "we looked and there was nothing" is an answer, and
the reader is entitled to know the question was asked.

## A finding page

1. `answerBlock(outcome)` — the whole answer structure, nothing else
2. the chart that shows the finding
3. the table underneath it, for anyone who wants the numbers
4. a `.callout--note` or `<details>` for the interesting-but-secondary material

One chart per claim. Two charts on one page means neither is the point.

The Overview is the exception: it carries the topic-mix area chart before the
outcome cards, because that shape is what makes the filing artefact visible
across the whole window at a glance.

## Tables

`table(columns, rows, opts)` in `app.js`. Always use it.

Column definitions take `key`, or `get` for a computed value, plus optional
`num` (right-aligned, tabular), `dim` (muted) and `html` (for badges or
formatted percentages). Never build table HTML by hand.

`tablewrap` and `tablescroll` give the sticky header and the height cap. Long
tables scroll inside their frame rather than pushing the page down.

`opts.caption` carries the *how many* and the *filtered how* — "82,340 in-window
headlines for `Business` · showing 50 from offset 0". A table without its
denominator is how a rate stops being a rate.

## Tabs and controls

`tabs(names, active)` and `setTimeout(..., 0)` for wiring after render. Route
tabs through the hash so a tab is linkable and survives a reload.

Controls go in `.controls` with `.field` wrappers. Always give them a run or
load button — nothing fetches on change. A select that fires a query on every
keystroke is a page that feels broken.

## Routing

Hash routing: `#/overview`, `#/findings/volume`, `#/explore/Warehouse`,
`/how/Corrections`. Read with `routeFromHash()`, write with `hashFor()`. This
makes every view shareable, which matters when someone wants to send a colleague
straight to the corrections page.

## Adding a page

1. Add it to `SECTIONS` in `app.js`
2. Add a `page*()` function returning HTML
3. Add a case to the `render()` switch
4. Add the tab list to `renderNav()` if it has sub-navigation
5. Add its charts to `dwm/ui/charts.py` and reference them by name
6. Run `tests/test_ui.py` — the chart-name and data-path checks will tell you
   what you forgot

Six steps, and steps 5 and 6 are the ones that catch mistakes. The tests exist
because building this the first time produced four silently-wrong pages.