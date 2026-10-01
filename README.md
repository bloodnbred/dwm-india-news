# dwm-india-news

Data Warehousing and Mining project: **Indian News Warehouse**.

Loads three real datasets into a DuckDB fact constellation, runs OLAP and
mining operations, and produces a traceable inference about trends in Indian
news. The design is specified in [`BLUEPRINT.md`](BLUEPRINT.md); this file
covers how to run it and what state each phase is in.

## Current state

Phases 0 and 1 (scaffold, ingest) are **built and verified**. Phases 2-9 are
registered in the CLI but raise `NotImplementedError` naming the phase, so the
command surface is stable while the rest is written.

| Phase | Output | Status |
|---|---|---|
| 0 Scaffold | repo, config, CLI | done |
| 1 Ingest | `stg_toi`, `stg_ifnd`, `stg_nifty`, `etl_audit` | done, gate passes on real data |
| 2 ETL + dims | clean tables, `dim_*` | stub |
| 3 Features + facts | `fact_*`, bridge, cubes | stub |
| 4 OLAP | `dwm/olap/`, SQL cookbook | stub |
| 5-6 Mining | trends, bursts, clusters, rules, classifier | stub |
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

# develop on a slice instead of the full file
.\.venv\Scripts\python.exe -m dwm ingest --sample 50000

# what is in the warehouse, and where the rows went
.\.venv\Scripts\python.exe -m dwm tables
.\.venv\Scripts\python.exe -m dwm audit
```

Global options accepted by the pipeline commands: `--db`, `--sample`, `--years`,
`--chunk`, `--dataset/-d`, `--force`, `--skip-fetch`, `--verbose`.

A first full run downloads about 240 MB into `data/raw/` (gitignored) and
takes roughly 40 seconds. A `.sha256` sidecar is written next to each file, so
subsequent runs skip the download.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

59 tests, no network access required. They cover config loading, date parsing
with its precision rules, staging against the row-count gate, the CSV
normalisation fallback, and the CLI contract.

## Layout

```
config/
  datasets.yaml      source URLs, column aliases, date formats, provenance
  topics.yaml        raw category -> coarse topic, with ordered regex rules
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
  etl/ features/ warehouse/ olap/ mining/ inference/ api/    (stubs)
tests/
docs/
  01-ingest-etl.md  ingest design, data traps, measured data profile
data/raw/            raw CSVs, gitignored
warehouse/           dwm.duckdb, gitignored
```

## Design notes worth knowing before Phase 2

These are measured findings, not assumptions. Full detail in
[`docs/01-ingest-etl.md`](docs/01-ingest-etl.md).

- **Never pass `ignore_errors` to `read_csv`.** On duckdb 1.5.6 it silently
  discarded 15,730 of 56,714 rows from a perfectly well-formed file, while
  `count(*)` still reported the full number. The gate reconciles the
  *materialised* count against the file.
- **IFND cannot be parsed by DuckDB as shipped.** The loader falls back to a
  strict `csv`-module re-quoting, then reloads. TOI and nifty load directly.
- **Harvard Dataverse returns 403 to a non-browser User-Agent.** `fetch.py`
  sends a browser UA; override with `DWM_USER_AGENT`.
- **IFND dates are month-precision or worse.** 67% resolve to a month,
  12.6% to a day with no year, 20.2% are empty. `fact_statement.date_key` must
  be nullable and must carry a `date_precision`.
- **IFND's majority-class baseline is 66.7%**, not 50%.
- **`Local` is 58% of TOI.** It is a location, not a subject; treat the
  topic-mix question accordingly.

## Honesty rules carried from the blueprint

- Never call an unlabelled measure a "fake news rate". On TOI it is a
  **risk-signal rate**; only the labelled IFND data supports accuracy claims.
- Cube totals are stored as **sums**, never averages. Averages are recomputed
  as sum/count at query time.
- Correlations are reported as associations, not causation.
- If a dataset cannot be fetched, the run stops and the gap is stated in the
  report. **Data is never fabricated.**
