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

`streamlit run dashboard/app.py`. Nine panels: Overview, Trends, Language,
Rules, Market, Classifier, Browse headlines, Warehouse, Report.

**It computes nothing** (BLUEPRINT section 1). It calls the API and renders what
comes back. `dashboard/helpers.py` holds the formatting so that can be tested
without a browser, and `render_metric` returns the value, unit and caution as
three separate strings so a test can assert the caution is never dropped.

That is not decoration. A bare "10.9%" on a screen, detached from the words
"risk-signal rate on unlabelled headlines", is exactly how a risk-signal rate
stops being called one. `metric()` shows a warning when a figure has a unit and
no caution, and `has_all_cautions` is checked at startup.

Because the panels read `/summary`, which nests the body under `data`, the
dashboard uses a `section()` helper that joins the header and the body once.
Reading the body from the top level is a mistake that surfaces at runtime as a
`KeyError`, and it did, twice, during the build.

## Testing the dashboard

A browser was not available in the build environment, so the dashboard was
verified by exercising its exact data path against a live server: 60 assertions
mirroring each panel's calls, run against `python -m dwm serve` with the real
warehouse. All passed, including that the report served over HTTP contains all
seven RQ sections and never calls the style measure a fake-news rate.

The long-term tests use `TestClient` against the fixture warehouse, which is
faster and runs in CI.

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
