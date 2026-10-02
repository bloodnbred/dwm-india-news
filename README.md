# dwm-india-news

Data Warehousing and Mining project: **Indian News Warehouse**.

Loads three real datasets into a DuckDB fact constellation, runs OLAP and
mining operations, and produces a traceable report on trends in Indian news.
The design is specified in [`BLUEPRINT.md`](BLUEPRINT.md); this file covers how
to run it and what state each phase is in.

## What it found

Three of the seven research questions produced **no result, or a result that
reads better than it is**. Those are reported with the measurement that
establishes them, which is the most useful thing here.

- **The headline volume carries no news signal.** Within-year variation is
  2–4%, and a prediction fixed before the data was examined — that Health,
  Sports and Entertainment coverage would rise during the listed events —
  **failed in 5 of 10 event months**, all three desks falling together.
- **Topic structure exists but covers a sliver.** Silhouette 0.2582, with one
  cluster holding 94.88% of the corpus. What the small clusters find is
  `rs crore`, `road accident`, `year old`: writing patterns, not desks.
- **Headline volume does not relate to daily returns** (strongest 0.0748, and
  the one significant lag out of 15 is what chance produces) **but does relate
  to 20-day volatility**, at r = −0.2827.
- `Education` carries a 10.94% risk-signal rate against a 3.77% corpus rate;
  644 association rules are found identically by Apriori and FP-Growth; and the
  IFND classifier reaches 95.71% against a 65.9% majority baseline.

Full detail in [`docs/04-mining.md`](docs/04-mining.md) and the generated
[`reports/report.md`](reports/report.md).

## Current state

Phases 0-8 are **built and verified on the real data**. Phase 9 is presentation
work: the report is already generated, so what remains is a viva sheet,
diagrams and a final reconciliation against the blueprint.

| Phase | Output | Status |
|---|---|---|
| 0 Scaffold | repo, config, CLI | done |
| 1 Ingest | `stg_toi`, `stg_ifnd`, `stg_nifty`, `etl_audit` | done, gate passes on real data |
| 2 ETL + dims | `cln_*`, `dim_*`, `map_category_topic` | done, gate passes on real data |
| 3 Features + facts | `fact_*`, `dim_keyword`, bridge, cubes | done, gate passes on real data |
| 4 OLAP | `dwm/olap/`, SQL cookbook | done, verified against the warehouse |
| 5-6 Mining | trends, bursts, clusters, rules, classifier | done, all 7 questions answered |
| 7 Inference | `facts.json`, `report.md` | done, 15 of 15 guards pass |
| 8 API + dashboard | FastAPI, Streamlit | done, 13 endpoints, 9 panels |
| 9 Polish | viva sheet, diagrams | **next** |

## Setup

Python 3.11+ (developed on 3.12.10).

```powershell
winget install --id Python.Python.3.12 --scope user
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The venv is at `.venv\`. On this machine `python` on `PATH` is only the
Microsoft Store alias, so invoke the interpreter by full path.

## Running

```powershell
# what is configured: URLs, column aliases, provenance
.\.venv\Scripts\python.exe -m dwm config --verbose

# download the raw CSVs and load the staging tables
.\.venv\Scripts\python.exe -m dwm ingest

# build the conformed dimensions and the clean tables
.\.venv\Scripts\python.exe -m dwm etl

# score sentiment, sensationalism, counts and keywords
.\.venv\Scripts\python.exe -m dwm features

# build the fact tables and the cubes
.\.venv\Scripts\python.exe -m dwm build

# answer the seven research questions, writing reports/mining.json
.\.venv\Scripts\python.exe -m dwm mine

# render reports/facts.json and reports/report.md, and run the guard rails
.\.venv\Scripts\python.exe -m dwm report

# OLAP: list the operations, or run one
.\.venv\Scripts\python.exe -m dwm olap
.\.venv\Scripts\python.exe -m dwm olap --op topic_mix
.\.venv\Scripts\python.exe -m dwm olap --op slice -p topic=Business
.\.venv\Scripts\python.exe -m dwm olap --op drill_across -p topic=Business --limit 20

# everything from raw CSV to report.md, with timings (about six minutes)
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean

# just the warehouse, skipping mining and the report (about four minutes)
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean -skipAnalysis

# develop on a slice instead of the full file
.\.venv\Scripts\python.exe -m dwm ingest --sample 50000

# what is in the warehouse, and where the rows went
.\.venv\Scripts\python.exe -m dwm tables
.\.venv\Scripts\python.exe -m dwm audit
```

### Serving it

Two terminals:

```powershell
# the API: http://127.0.0.1:8000/docs
.\.venv\Scripts\python.exe -m dwm serve

# the dashboard: http://localhost:8501
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

The dashboard needs the API running. Point it elsewhere with
`$env:DWM_API = "http://127.0.0.1:9000"`.

Global options accepted by the pipeline commands: `--db`, `--sample`, `--years`,
`--chunk`, `--dataset/-d`, `--force`, `--skip-fetch`, `--verbose`.

A first full run downloads about 240 MB into `data/raw/` (gitignored) and
takes roughly a minute. A `.sha256` sidecar is written next to each file, so
subsequent runs skip the download.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

265 tests, no network access required. They cover config loading, date parsing
with its precision rules, staging against the row-count gate, the CSV
normalisation fallback, the CLI contract, the ETL stage's dedupe grain and
window derivation, the feature stage's measure definitions, the Phase 3
fact/cube gate, every OLAP operation, the mining stage's guard rails, the
inference stage's traceability, and every API endpoint.

The later tests check the **promises** rather than the numbers, because the
numbers are already recorded in `reports/mining.json`. Specifically:

- a rate is never reported without its denominator
- a statistic from too few observations is refused with a stated reason
- the payload carries no causal wording and no "fake news rate"
- the classifier is judged against the real majority baseline, not 50%
- two mining runs agree on every number
- the sampler returns exactly the rows asked for and is not a first-n sample
- mlxtend's rule columns are read by name, not position
- every fact has a source, and every caution reaches `report.md`
- the guard rails fire on an empty warehouse
- the API is read-only and refuses unknown operations

Tests never touch the real warehouse, `data/raw` or `reports/`. An autouse
fixture redirects `DWM_REPORTS_DIR`, because the suite once silently replaced
the real `mining.json` with results from a ten-row fixture.

## Timings, measured on the full corpus

| stage | time |
|---|---|
| `ingest` (files already downloaded) | 13s |
| `etl` | 13s |
| `features` (3.15M headlines through VADER) | 203s cold, ~2s if already scored |
| `build` (facts + cubes) | 6s |
| `mine` (all seven research questions) | 91s, of which clustering is 77s |
| `report` (facts.json + report.md, 15 guards) | 1s |
| **full clean run to report.md** | **about 5.5 minutes** |

`features` is resumable and fingerprinted. An interrupted run continues from
the last scored row instead of restarting, and a change to any measure
definition discards the cache automatically rather than leaving stale numbers
in the warehouse.

## Layout

```
config/
  datasets.yaml      source URLs, column aliases, date formats, provenance
  topics.yaml        raw category -> coarse topic, with ordered regex rules
  features.yaml      sensationalism weights, thresholds, vocabulary size
  mining.yaml        every mining threshold, seed and sample size
dwm/
  cli.py             Typer app, one command per pipeline stage
  config.py          paths, run options, dataset specs, topic map
  db.py              DuckDB connection, table helpers
  parse.py           date/label/category parsing with explicit precision
  logging_utils.py   console logging, timed steps
  ingest/
    fetch.py         download with resume, retry and checksum sidecars
    normalise.py     strict RFC 4180 re-quoting fallback
    staging.py       stg_* loaders and the row-count gate
    audit.py         etl_audit funnel
    runner.py        per-dataset orchestration
  etl/
    dates.py         SQL date expressions + the IFND Python UDF
    clean.py         cln_* builders: dedupe, window, topic attachment
    dims.py          the five conformed dimensions
    __init__.py      orchestration and the Phase 2 gate
  features/
    lexicons.py      stopword, superlative and urgency lists (offline, pinned)
    scoring.py       one pass: sentiment, sensationalism, counts, keywords
    runner.py        chunked runner, optional process pool, SQL market features
  warehouse/
    facts.py         the three fact tables
    cubes.py         pre-aggregated cubes, sums only
  olap/
    operations.py    slice, dice, roll_up, drill_down, pivot, cube, drill_across
  mining/
    sampling.py          one deterministic sampler, seeded and exact
    trends.py            RQ1 topic mix, RQ2 bursts, partial-year guard
    sensationalism.py    RQ3 risk-signal rate by topic, Wilson intervals
    clustering.py        RQ4 TF-IDF + LSA + K-Means, k by silhouette
    rules.py             RQ5 Apriori and FP-Growth, timing compared
    market.py            RQ6 lagged correlation and volatility, trading days only
    classifier.py        RQ7 Real vs Fake against the majority baseline
  inference/
    facts.py         mining.json + warehouse -> facts.json, with cautions
    report.py        facts.json -> report.md, templates only, no LLM
    __init__.py      orchestration and the 15-check gate
  api/
    store.py         read-only warehouse handle, cached results
    app.py           13 FastAPI endpoints
dashboard/
  app.py             Streamlit, 9 panels, calls the API and computes nothing
  helpers.py         formatting, so the "no figure without a caution" rule is testable
tests/
docs/
  01-ingest-etl.md         ingest design, data traps, measured data profile
  02-warehouse-schema.md   dimensions, clean tables, gate results
  03-features-facts.md     measure definitions, cubes, Phase 3 gate
  04-mining.md             the seven questions and the three negative results
  05-inference-api.md      traceability, guard rails, API and dashboard
  VIVA.md                  every claim, its command, and the follow-up question
  STATUS.md                handover notes and current state
reports/              mining.json, facts.json, report.md
data/raw/             raw CSVs, gitignored
warehouse/            dwm.duckdb, gitignored
```

## Design notes worth knowing before Phase 4

These are measured findings, not assumptions. Full detail in
[`docs/01-ingest-etl.md`](docs/01-ingest-etl.md),
[`docs/02-warehouse-schema.md`](docs/02-warehouse-schema.md) and
[`docs/03-features-facts.md`](docs/03-features-facts.md).

- **Never pass `ignore_errors` to `read_csv`.** On duckdb 1.5.6 it silently
  discarded 15,730 of 56,714 rows from a perfectly well-formed file, while
  `count(*)` still reported the full number. The gate reconciles the
  *materialised* count against the file. `store_rejects` is also unusable: it
  drops the same rows and creates a fixed-name `reject_scans` table, so
  staging a second dataset in the same connection fails outright.
- **IFND cannot be parsed by DuckDB as shipped.** The loader falls back to a
  strict `csv`-module re-quoting, then reloads. TOI and nifty load directly.
- **Harvard Dataverse returns 403 to a non-browser User-Agent.** `fetch.py`
  sends a browser UA; override with `DWM_USER_AGENT`.
- **IFND dates are month-precision or worse.** After dedup 33,964 resolve to a
  month, 6,789 to a day with no year, 10,357 have no date at all.
  `fact_statement.date_key` must be nullable with a `date_precision`, and a
  yearless day must never be given one.
- **IFND's majority-class baseline is 66.7%**, not 50%.
- **111,146 (date, text) headline pairs are filed under more than one
  category.** `fact_headline` is therefore one row per (date, text) with a
  most-frequent primary topic. One row per category would multi-count a third
  of a million headlines in every topic analysis.
- **`Local` is 58% of TOI overall and 70% inside the window.** It is a
  location, not a subject, which is why `dim_topic` carries a `topic_group`
  separating `Place` from `Subject`. Research question 1 needs that split. Its
  share of a single year reaches 89% in 2020, so "share of the window" and
  "share of a year" are stored as separate facts and must not be interchanged.
- **Headlines exist on 1,828 days in the window; the market trades on 1,235.**
  The 593-day gap is weekends and holidays, so any market-linked join must go
  through `is_trading_day`, not the calendar. `cube_day_topic` exists for this.
- **Never hard-code a dimension key in fact DDL.** `dim_dataset` numbers its
  rows by sorted code, so `toi` is key 3, not 1. A literal silently pointed
  every headline at the wrong source while all row counts stayed correct. The
  DDL now looks keys up, and tests cover it.
- **Cubes store sums, never averages.** A test rejects any column named like a
  mean. Rates are always `count / headline_count` computed at query time.
- **`volatility_20d` is NULL until 20 sessions exist.** A 20-day volatility
  from three observations would poison the Phase 6 correlation.
- **`is_risk_signal` equals `is_sensational` for TOI** because unlabelled
  headlines support style signals only. Report it as a risk-signal *rate*.
- **TOI changed how it files content.** `business.international-business` is
  11.1% of all 2017 headlines and 0.2% of 2018. Any topic-mix analysis that
  ignores this reports a filing artefact as a change in reader interest.
- **Monthly headline volume is nearly flat** (within-year CV 0.02–0.04), so
  volume cannot answer RQ2 and no threshold will make it. See
  [`docs/04-mining.md`](docs/04-mining.md).
- **The 300-term keyword vocabulary cannot support association rules.** It
  yields 1.99 items per headline because its top terms are functional words,
  and mining it produces zero rules. RQ5 mines attributes instead.
- **DuckDB's seeded sampler returns the wrong row count.** `USING SAMPLE
  reservoir(2000 ROWS) REPEATABLE (seed)` returned 709. `dwm/mining/sampling.py`
  sorts on `hash(column, seed)` instead, and a test asserts the sample is not a
  first-n draw.
- **Read mlxtend's rule columns by name.** They are ordered
  `antecedents, consequents, antecedent support, consequent support, support,
  confidence, lift`; reading positionally is off by two and made all 1,797
  rules look like lift-1.000 tautologies.
- **`silhouette_score` subsamples with no seed by default**, so the score moved
  between identical runs. Pass `random_state`.
- **A cluster description is a feature-engineering artefact, not a property of
  the data.** Admitting numerals and stop words moved the silhouette from 0.258
  to 0.068 and made "these headlines have no structure" look like a finding.
  See the correction in [`docs/04-mining.md`](docs/04-mining.md).

## Honesty rules carried from the blueprint

These are enforced in code, not just written down. Each has at least one test
that fails if it is broken.

- **Never call an unlabelled measure a "fake news rate".** On TOI it is a
  **risk-signal rate**; only the labelled IFND data supports accuracy claims.
  The API carries each fact's `caution` next to its value, and the dashboard
  refuses to render a figure that has a unit and no caution.
- **Cube totals are stored as sums, never averages.** Averages are recomputed
  as sum/count at query time. A test rejects any column named like a mean.
- **Correlations are associations, not causation.** Every coefficient travels
  with a p-value, a count, and the number of tests run — 15 lag tests produce
  about 0.75 false positives, so one p below 0.05 is not a discovery.
- **A rate is never reported without its denominator**, and topics below a row
  floor are excluded from rankings and listed separately.
- **A statistic from too few observations is refused with a reason**, never
  divided through to a plausible-looking number.
- **A partial year never contaminates a whole-year statistic.** 2015 has seven
  months; its wider spread once made a flat series look like CV 0.39.
- **Every fact records its source, and every caution reaches the report.** This
  is what makes "each number traces to a query" checkable rather than
  aspirational.
- **There is no language model in the reporting path.** `report.md` is rendered
  from `facts.json` by templates.
- **If a dataset cannot be fetched, the run stops and the gap is stated.**
  **Data is never fabricated.**
