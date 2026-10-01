# dwm-india-news

Data Warehousing and Mining project: **Indian News Warehouse**.

Loads three real datasets into a DuckDB fact constellation, runs OLAP and
mining operations, and produces a traceable inference about trends in Indian
news. The design is specified in [`BLUEPRINT.md`](BLUEPRINT.md); this file
covers how to run it and what state each phase is in.

## Current state

Phases 0-4 (scaffold, ingest, ETL + dimensions, features + facts, OLAP) are
**built and verified**. Phases 5-9 are registered in the CLI but raise
`NotImplementedError` naming the phase, so the command surface is stable while
the rest is written.

| Phase | Output | Status |
|---|---|---|
| 0 Scaffold | repo, config, CLI | done |
| 1 Ingest | `stg_toi`, `stg_ifnd`, `stg_nifty`, `etl_audit` | done, gate passes on real data |
| 2 ETL + dims | `cln_*`, `dim_*`, `map_category_topic` | done, gate passes on real data |
| 3 Features + facts | `fact_*`, `dim_keyword`, bridge, cubes | done, gate passes on real data |
| 4 OLAP | `dwm/olap/`, SQL cookbook | done, verified against the warehouse |
| 5-6 Mining | trends, bursts, clusters, rules, classifier | **next** |
| 7 Inference | `facts.json`, `report.md` | stub |
| 8 API + dashboard | FastAPI, Streamlit | stub |
| 9 Polish | docs, report, viva sheet | partial |

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

# OLAP: list the operations, or run one
.\.venv\Scripts\python.exe -m dwm olap
.\.venv\Scripts\python.exe -m dwm olap --op topic_mix
.\.venv\Scripts\python.exe -m dwm olap --op slice -p topic=Business
.\.venv\Scripts\python.exe -m dwm olap --op drill_across -p topic=Business --limit 20

# the whole pipeline from scratch, with timings
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean

# develop on a slice instead of the full file
.\.venv\Scripts\python.exe -m dwm ingest --sample 50000

# what is in the warehouse, and where the rows went
.\.venv\Scripts\python.exe -m dwm tables
.\.venv\Scripts\python.exe -m dwm audit
```

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

157 tests, no network access required. They cover config loading, date parsing
with its precision rules, staging against the row-count gate, the CSV
normalisation fallback, the CLI contract, the ETL stage's dedupe grain and
window derivation, the feature stage's measure definitions, the Phase 3
fact/cube gate, and every OLAP operation.

## Timings, measured on the full corpus

| stage | time |
|---|---|
| `ingest` (files already downloaded) | 10s |
| `etl` | 9s |
| `features` (3.15M headlines through VADER) | 165s cold, ~2s if already scored |
| `build` (facts + cubes) | 5s |
| **full clean run** | **about 3.3 minutes** |

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
    operations.py  slice, dice, roll_up, drill_down, pivot, cube, drill_across
  mining/ inference/ api/    (stubs)
tests/
docs/
  01-ingest-etl.md         ingest design, data traps, measured data profile
  02-warehouse-schema.md   dimensions, clean tables, gate results
  03-features-facts.md     measure definitions, cubes, Phase 3 gate
data/raw/            raw CSVs, gitignored
warehouse/           dwm.duckdb, gitignored
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
  separating `Place` from `Subject`. Research question 1 needs that split.
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

## Honesty rules carried from the blueprint

- Never call an unlabelled measure a "fake news rate". On TOI it is a
  **risk-signal rate**; only the labelled IFND data supports accuracy claims.
- Cube totals are stored as **sums**, never averages. Averages are recomputed
  as sum/count at query time.
- Correlations are reported as associations, not causation.
- If a dataset cannot be fetched, the run stops and the gap is stated in the
  report. **Data is never fabricated.**
