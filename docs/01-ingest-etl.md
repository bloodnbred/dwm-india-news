# 01 — Ingest and ETL design

This note records what the ingest stage actually does to the source files, the
data-quality decisions it makes, and the traps found in the real data. It is
the reference for the "ETL steps and data-quality funnel" section of the
project report.

## Principle: ingest is lossless

`dwm/ingest/staging.py` deliberately does **no** cleaning. It loads each CSV
as-is into a `stg_*` table with every column typed `VARCHAR`, adds a surrogate
`_stg_row_id` and an ingest timestamp, and records what it did in
`etl_audit`.

| Table | Grain | Source |
|---|---|---|
| `stg_toi` | one TOI headline | `publish_date, headline_category, headline_text` |
| `stg_ifnd` | one labelled statement | `id, Statement, Image, Web, Category, Date, Label` |
| `stg_nifty` | one trading day | `Date, Open, High, Low, Close, Volume, Turnover` |

All three tables share the same shape: `stg_row_id`, `stg_dataset_code`,
`stg_filename`, `stg_ingested_at`, `stg_row_num`, `raw_text`, `raw_category`,
`raw_date`, `raw_label`, plus `raw_<numeric>` columns where the dataset has
them. A field a dataset does not provide is `NULL`, never absent, so a fact
table can join to any staging table without column-existence checks.

Keeping ingest dumb means the ETL stage can present an honest
rows-in / rows-out funnel. If ingest deduplicated, the loss would be invisible.

## The Phase 1 gate

The gate is *"row counts in staging equal rows in source file"*. It is checked
in `stage_dataset` and written to `etl_audit`:

```
rows_read     = data rows in the file, counted from the raw bytes
rows_loaded   = rows that landed in the stg_ table
rows_rejected = rows_read - rows_loaded
csv_rejects   = rows DuckDB itself refused, from its rejects side table
```

A shortfall is logged as a warning, **not** raised. The reason is that a
partial load must still leave a funnel for the report to show, rather than
vanish behind an exception.

## Traps found in the real data

These were found by running the stage, not by reading the papers. Each one is
handled in code and covered by a test.

### 1. Harvard Dataverse rejects a project User-Agent

`https://dataverse.harvard.edu/api/access/datafile/:persistentId?...` answers
**403 Forbidden** to `User-Agent: dwm-india-news/0.1 (course project)` and
**206 Partial Content** to a browser-style UA. Verified 2026-10-01.

`dwm/ingest/fetch.py` therefore sends a browser UA by default. Override with
the `DWM_USER_AGENT` environment variable. The same variable is the escape
hatch for any other host that plays games.

### 2. `ignore_errors = true` silently destroys data

This was the most damaging finding. On the **perfectly well-formed** IFND file
(56,714 rows, every row exactly 7 fields, verified with Python's `csv`
module), DuckDB 1.5.6 behaves like this:

| `read_csv` options | rows materialised |
|---|---|
| `ignore_errors = true` | **40,984** (15,730 silently dropped) |
| `store_rejects = true` | **40,984** |
| default, `SELECT count(*)` | 56,714 |
| after strict re-quoting | 56,714 |

`SELECT count(*)` uses an optimised metadata path and reports the full count,
so the loss only shows up once the rows are actually written. A pipeline that
validated with `count(*)` would have shipped a warehouse missing 28% of the
labelled data.

Consequences, both applied:

- **Never pass `ignore_errors`.** Use `store_rejects = true` with a
  `rejects_table`, which records genuinely malformed rows instead of dropping
  them quietly.
- **Always reconcile the materialised count against the file**, never trust
  `count(*)`.

### 3. IFND cannot be parsed by DuckDB as shipped

DuckDB rejects the IFND file outright:

```
Invalid Input Error: CSV Error on Line: 47
Original Line:
46,'Police must adhere to norms': Centre issues fresh advisory to States on women safety...
```

The file has no odd-quote lines and no embedded newlines; the row is valid
RFC 4180 and Python's `csv` module reads all 56,714 rows. This is a DuckDB
CSV-sniffer limitation, not a data defect.

`dwm/ingest/normalise.py` is the fallback. When the direct load raises, **or
when the materialised count is short of the file**, the loader:

1. re-reads the file with Python's `csv` module,
2. rewrites it with a strict `QUOTE_MINIMAL` writer to
   `<name>.normalised.csv`,
3. reloads from there,
4. sets `normalised: true` in `etl_audit`.

The rewrite is a mechanical re-quoting of the same bytes. Row counts are
verified on both sides, and the normalised file is reused on later runs.

This is deliberately a *fallback*, not a mandatory step: TOI and nifty parse
correctly and are loaded straight from the original bytes.

### 4. IFND dates are month-precision

The `Date` column mixes `Oct-20`, `Nov 2020` and bare years. There is no day
component anywhere in it. Consequences:

- `dwm/parse.py` returns a `ParsedDate` carrying `precision` of `day`, `month`
  or `none`, rather than a bare `date`.
- A month-only value resolves to the **first of the month**, tagged `month`.
  The day is never invented silently — the tag travels with the value.
- Unparseable values resolve to `precision = "none"`, are counted into
  `etl_audit`, and never raise.
- `fact_statement.date_key` will therefore be a month-start key, and
  `date_precision` is carried alongside it. Drill-across against daily market
  data must respect that: comparing a month-start statement date to a daily
  close is a category error, and the report says so.

`--years 5` windows are day-granular for TOI and nifty and month-granular for
IFND. That asymmetry is inherent to the sources.

### 5. IFND is class-imbalanced and partly synthetic

37,809 real against 7,271 fake before augmentation; the Fake class is enlarged
with an LSTM augmentation algorithm. Two consequences for Phase 6:

- The majority baseline is not 50%. A classifier that predicts "all real"
  already scores ~87%, so any accuracy figure must be shown against that
  baseline, and precision/recall on the Fake class matters more than accuracy.
- Augmented fakes are easier to spot than scraped ones, so measured accuracy
  is an upper bound. This belongs in the report's limitations.

### 6. Nifty has no text column

`nifty50.csv` is a price series: `Date, Open, High, Low, Close, Volume,
Turnover`. `config/datasets.yaml` declares `text_column: null` for it, and the
loader emits `raw_text` as `NULL` rather than insisting on a headline.

Source is a GitHub mirror of Yahoo Finance `^NSEI` daily OHLCV, covering
2008-01-21 to 2023-01-24. The `abulbasar/data` copy that circulates for this
dataset stops at **2019-12-31** and so misses January–June 2020, the COVID
window that research question 6 cares about most. Authoritative fallback is
the NSE daily archive, which only reaches back to about 2018-09.

### 7. TOI categories are hierarchical, and sparse early

`headline_category` is dot-separated: `sports.wwe`, `business.gadgets`. The
top-level prefix is mapped to a coarse topic by `config/topics.yaml`. Early
years (2001 onward) are dominated by `unknown`, which maps to the `Unknown`
topic rather than being dropped, so headline counts still reconcile against
staging.

Unmapped categories fall through to the `Other` topic and are counted, so the
Phase 2 gate *"every raw category maps to a topic"* holds by construction.
The count of fallbacks is reported in `etl_audit` so the map can be extended.

The five-year window is computed from `max(publish_date)` and is never
hard-coded. Since TOI ends mid-2020, the window is approximately
2015-06-30 to 2020-06-30, in a period where TOI categories are rich.

## Measured data profile

Everything below was measured on the real files on 2026-10-01, not taken from
the papers. It is the baseline the ETL stage should reproduce.

### Staging reconciliation (the Phase 1 gate)

| Dataset | rows in file | staged | rejected |
|---|---:|---:|---:|
| `toi` | 3,297,172 | 3,297,172 | 0 |
| `ifnd` | 56,714 | 56,714 | 0 |
| `nifty` | 3,718 | 3,718 | 0 |

`ifnd` only reaches 56,714 because the normalisation fallback ran. Direct
DuckDB load gave 40,984.

### TOI

- 3,297,172 rows, 7,080 distinct dates, **0 unparseable dates**, all
  day-precision.
- Range 2001-01-01 to 2020-06-30.
- The `--years 5` window is therefore **2015-06-30 to 2020-06-30** and holds
  **1,167,299 headlines**. It is computed from the data, never hard-coded.
- 6.3% of rows carry the raw category `unknown`, concentrated in the early
  years. They map to the `Unknown` topic rather than being dropped.

### IFND

- 56,714 rows. Labels: **37,800 real / 18,914 fake**.
- **Majority-class baseline is 66.7%**, not 50%. A classifier that always
  answers "real" scores 0.667, so accuracy alone is meaningless in Phase 6.
- Date completeness, after adding the yearless format:

  | precision | rows | share | usable for |
  |---|---:|---:|---|
  | `month` (e.g. `Oct-20`, `Nov 2020`) | 38,081 | 67.1% | month-level joins |
  | `month_day` (e.g. `20-Sep`, no year) | 7,172 | 12.6% | seasonality only |
  | `none` (empty) | 11,461 | 20.2% | nothing time-based |

  So only **67% of IFND rows have a resolvable calendar date**. This confirms
  the blueprint's fallback row *"IFND has no dates → allow nullable
  `date_key`; skip time-based IFND analysis"*. The classifier work is
  unaffected: it does not use dates.

### Nifty

- 3,718 rows, 0 unparseable dates, 2008-01-21 to 2023-01-24.

### Topic mapping coverage

`config/topics.yaml` maps the hierarchical raw category to a coarse topic.
Initial coverage was 91.9%; after adding the `life-style`, `home` and
`*-times` families plus ordered regex rules, **unmapped ("Other") is 0.84%**
(27,570 rows).

| topic | share | topic | share |
|---|---:|---|---:|
| Local | 58.2% | Lifestyle | 0.9% |
| Nation | 11.5% | Other (unmapped) | 0.8% |
| Entertainment | 8.0% | Education | 0.6% |
| Unknown | 6.3% | Politics | 0.5% |
| Business | 4.7% | Health | 0.5% |
| Sports | 4.1% | Environment | 0.2% |
| World | 1.9% | Automobile | 0.2% |
| Technology | 1.7% | Religion / Travel | ~0.0% |

Two things to be aware of before the topic-mix analysis (RQ1):

- **`Local` is 58% of the corpus.** TOI's `city.*` categories and the Times
  city editions together dominate. It is a real part of the archive, not a
  mapping artefact, but it means "topic mix" is mostly a Local/non-Local
  split unless local coverage is deliberately excluded or analysed separately.
- **`Local` is a "where", not a "what".** A city story can be about business or
  sport. The coarse topic is therefore location-flavoured for over half the
  rows. If RQ1 needs subject topics rather than desk types, the fix is a
  keyword-based subject classifier over the headline text (Phase 5 material),
  not more entries in this file.

## Downloads

`dwm/ingest/fetch.py` supports resume via HTTP `Range` (both hosts answer
`206`), retries up to four times, and writes a `.sha256` sidecar so a second
run skips the download entirely. `--force` re-downloads.

If a dataset cannot be fetched, the stage raises `FetchError` naming the URL
and the target directory. **Data is never fabricated.** Per the blueprint's
fallback table, the run stops and the gap is stated in the report.

## Sampling

`--sample N` takes the first N rows of the file, not a random sample, so the
sample is reproducible across runs and lands on a contiguous date range. The
audit still records the true `rows_read`, so the funnel shows the sample in
context rather than pretending the file was small.

Note that a TOI sample is drawn from the start of the file, i.e. 2001, which
is mostly `unknown` categories and outside the analysis window. **A sample
validates the pipeline, not the analysis.** Full runs are required before any
mining phase.
