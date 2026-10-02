# 05 — Inference, API and dashboard (Phases 7-8)

How `mining.json` becomes `report.md`, and how the API and dashboard reach it
without either of them becoming a second source of truth.

## The shape of the pipeline

```
dwm mine     →  reports/mining.json     the numbers, once
dwm report   →  reports/facts.json      the numbers + source + caution
             →  reports/report.md       the sentences, from templates
dwm serve    →  reads facts.json, serves it
streamlit    →  calls the API, renders it
```

Each stage reads what the previous one wrote. Nothing downstream recomputes
anything, which is what makes "every number in the report traces to a query"
checkable rather than aspirational: a reader who distrusts a number opens the
fact, reads its `source`, and runs the query.

## A fact

```json
{
  "value": 0.037718,
  "unit": "risk-signal rate, share of headlines over the sensationalism threshold",
  "source": "reports/mining.json:rq3_sensationalism.by_topic.corpus_rate",
  "caution": "A STYLE measure on unlabelled headlines. It is a risk-signal rate
              and is NOT a fake-news rate. The threshold is the measured 95th
              percentile, a chosen cut-off, so the report must show the
              sensitivity table."
}
```

`caution` is the honesty mechanism. A fact that is easy to misread carries its
caveat *with it*, so the renderer cannot drop it by accident. Three tests hold
this in place:

- every fact records a `source`
- every fact with a `unit` has a `caution`
- every caution in `facts.json` appears in `report.md`

The third is the one that matters. A caution sitting in a JSON file and never
reaching the document is a dropped caveat.

## Why there is no language model in this path

Every sentence in `report.md` is a template in `dwm/inference/report.py` and
every number is a value in `facts.json`. This is a deliberate constraint from
the blueprint, and it is what makes traceability checkable — a language model
can produce a fluent sentence containing a number nobody computed. The report
says so in its own footer, and a test asserts it.

## The gate

`check_guards` runs 15 checks. Each states what it looked at; a check that
cannot be evaluated reports that rather than passing quietly.

```
inference gate: 15 of 15 checks passed
```

A failed guard exits **non-zero**, so a pipeline cannot pass silently on a
warehouse that cannot support its claims. But the report is still written,
because "this could not be measured, and here is why" is more useful than no
report.

The checks cover:

| group | checks |
|---|---|
| corpus | in-window headlines present, and above the 1,000-row floor for a rate |
| labels | labelled statements present |
| market | trading days present, enough paired observations for a correlation |
| sections | each of the seven present **and non-empty** |
| ran | each section that reports `ran` actually ran, with its reason if not |
| integrity | every in-window headline has a topic |

The "non-empty" and "ran" checks were added after a test showed that key
presence alone was satisfied by `rq4_clusters: {}` — a section that had answered
nothing while passing the gate.

## Two path bugs worth recording

**A module-level path constant froze the reports directory at import time.**
`FACTS_JSON = reports_dir() / "facts.json"` was evaluated when the module was
first imported, so redirecting `DWM_REPORTS_DIR` afterwards had no effect on
that module. The consequence was a `503 results not found` from the API while
the file was sitting on disk, because the writer had used a different module
that had been imported later. Paths are now resolved by calling `reports_dir()`
at use time, so redirection does not depend on import order.

**The test suite silently overwrote the real `reports/mining.json`.** Because
the reports path was a constant, running pytest replaced the full-corpus
mining results with results computed from a ten-row fixture — and the next
report rendered "3 paired trading days" as though that were the finding.
`DWM_REPORTS_DIR` now exists and an autouse fixture points it at a tmp path for
every test. `reports_dir()` honours it.

## The API

FastAPI, read-only, thirteen paths. `python -m dwm serve`.

| endpoint | what it does |
|---|---|
| `GET /health` | liveness **and** whether the warehouse and results exist |
| `GET /operations` | the ten OLAP operations with default parameters |
| `GET /facts` | everything `facts.json` holds |
| `GET /facts/{section}` | one section |
| `GET /summary` | the headline figures, each with `unit` and `caution` |
| `GET /report` | `report.md` as text/markdown |
| `GET /topics` | the topic dimension |
| `GET /headlines` | a paged slice of in-window headlines |
| `GET /series/monthly` | monthly counts and rates, optionally by topic |
| `GET /tables` | every table with its row count |
| `GET /audit` | the pipeline run funnel |
| `GET /query/{operation}` | runs one of the ten OLAP operations |
| `POST /query/reload` | drops cached results so a rebuilt warehouse is picked up |

Three decisions:

**The API serves results; it does not recompute them.** Every figure under
`/facts`, `/summary` and `/report` is read from `facts.json`. The single
exception is `/query/{operation}`, which exists to answer ad-hoc slicing
questions and is whitelisted to the ten named operations.

**Read-only is a property of the file, not a promise.** The DuckDB handle is
opened `read_only=True`, so no malformed request can write to the warehouse even
if validation were bypassed.

**A missing warehouse is 503, not 500.** "You have not built it yet" is a
different situation from "the server is broken", and the message says which
command to run.

`limit` on `/headlines` is capped at 500. The corpus holds 1.1M in-window rows
and an unbounded page would exhaust memory in the client rather than being a
convenience.

## The dashboard

`streamlit run dashboard/app.py`. Five sections — Overview, Findings, Explore,
How it works, Report — with seven finding pages, one per research question.

**It computes nothing** (BLUEPRINT section 1). It calls the API and renders what
comes back. `dashboard/helpers.py` holds the design system and the formatting, so
both can be tested without a browser.

### The answer comes before the evidence

Each finding page leads with the question, then **the answer as the largest text
on the page**, then how we know, then the caveat. The previous layout showed
panels of data and left the reader to infer the point, which inverts the
emphasis for no good reason.

The conclusions live in `facts.json` under `outcomes`, **derived from the
measured values** rather than hand-written, so they cannot drift away from the
numbers the way prose does. Both `report.md` and the dashboard render the same
block. A null result is kept rather than dropped: "we looked and there was
nothing" is the answer to a question.

### Cautions

`render_metric` returns the value, unit and caution as three separate strings so
a test can assert the caution is never dropped, and `find_uncautoned` walks the
whole API payload at startup — if any figure has a unit and no caveat, the
sidebar shows a warning. `metric()` renders a warning inline in that case.

That is not decoration. A bare "10.9%" on a screen, detached from the words
"risk-signal rate on unlabelled headlines", is exactly how a risk-signal rate
stops being called one.

### Infographics

Six Altair charts, chosen because each one shows a finding rather than
displaying a table: the event-month z-scores as diverging bars, the topic mix as
a stacked area, silhouette against k with the chosen value ringed, the cluster
sizes showing the 94.88% blob, the volatility scatter with its trend, and the
confusion matrix as a heatmap. Hover tooltips throughout, and a CSV download
returns exactly the data behind each chart.

Two-colour encodings are written as a **labelled nominal field** mapped through
a scale, not as a conditional. Altair 6 changed the conditional API enough that
`alt.condition(...)` is no longer safe to title, and an untitled two-colour
legend is unreadable anyway — so the legend says `coverage fell` and
`coverage rose`.

### Testing the dashboard

**A healthy server proves nothing.** Streamlit executes a page only when a
session connects, so a dashboard whose every page raises still answers
`/_stcore/health` with "ok". That is how the Report page survived: it called
`.json()` on a markdown endpoint and had never once worked.

So the tests use Streamlit's own `AppTest` to run the real script headlessly and
visit every section, every finding page, and both tab groups — 21 tests. It
caught a `KeyError` from misreading the API's shape, three Altair 6 API breaks,
and a `str` versus `float` comparison caused by a colour label overwriting the
column being plotted.

One test recomputes the volatility correlation from the plotted points and
asserts it matches the reported r, so the scatter and the number beside it can
never describe different things.

## End-to-end

```
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean
```

runs ingest → etl → features → build → mine → report, about six minutes, and
prints the artefact sizes at the end. `-skipAnalysis` rebuilds only the
warehouse.

```
265 tests, ruff clean
```

The suite runs with no network access and never touches the real warehouse,
`data/raw` or `reports/`.
