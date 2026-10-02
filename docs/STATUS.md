# Where the project stands

Written at the end of 2026-10-02, after Phase 8. Read this first in a new
session, then `README.md` for how to run things and `docs/` for the design
reasoning behind each stage.

## Done and verified on the real data

| Phase | Gate | Result |
|---|---|---|
| 0 Scaffold | pytest runs, `--help` works | pass, 265 tests |
| 1 Ingest | staging row counts equal source | pass, zero rejects |
| 2 ETL + dims | no null date keys, every category maps | pass |
| 3 Features + facts | fact counts equal clean counts, keys unique | pass |
| 4 OLAP | roll-up totals equal raw totals, cube equals fact | verified against the warehouse |
| 5-6 Mining | metrics on test split only; seeds reproduce | pass, all 7 questions answered |
| 7 Inference | every fact has a source; every caution reaches the report | pass, 15 of 15 guards |
| 8 API + dashboard | read-only; every panel's data path exercised | pass, 13 endpoints, 9 panels |

Everything reproduces from raw CSV to `report.md` in about six minutes:

```
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean
.\.venv\Scripts\python.exe -m dwm serve
.\.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

`-skipAnalysis` rebuilds only the warehouse.

## What the study found

Three of the seven questions produced no result, or a result that reads better
than it is. Those are reported with the measurement that establishes them, which
is the point of the exercise.

**There is no news signal in the headline volume.** Within-year volume
coefficient of variation is 0.0202 to 0.0352, and the busiest month of a year
runs only 2-5% above its own mean. March 2020, the month of the national
lockdown, is 2.5% above its year mean. A prediction fixed in config before the
data was examined — that Health, Sports and Entertainment coverage would rise
during the listed events — **failed in 5 of the 10 event months**, all three
failing together. The archive behaves like a fixed editorial capacity.

**Topic structure exists but is narrow.** Silhouette is 0.2582, which clears
the threshold for strong separation — but one cluster holds 94.88% of the
corpus. What the three small clusters find is `rs crore`/`lakh` (money),
`road`/`accident`/`killed` (traffic and crime) and `old`/`year old`
(age-and-gender copy): **writing patterns, not desks**, and none of them a topic
in the publisher's own taxonomy.

**Headline volume does not relate to daily returns, but does relate to
volatility.** Against returns the strongest coefficient is 0.0748 and only 1 of
15 lag tests is significant, which is what chance produces. Against 20-day
volatility, log business-headline volume correlates at **r = −0.2827**
(p < 0.0001, 8% of variance): busier headline days go with calmer markets. The
sign is unexplained and this data cannot explain it.

The positives: `Education` carries a 10.94% risk-signal rate against a 3.77%
corpus rate; 644 association rules are found identically by Apriori and
FP-Growth; and the IFND classifier reaches 95.71% against a 65.9% majority
baseline, +29.8 points, with Fake recall 91.4%.

Full reasoning in `docs/04-mining.md`.

## Current row counts

```
stg_toi             3,297,172      cln_headline      3,154,916
stg_ifnd               56,714      cln_statement        51,110
stg_nifty               3,718      cln_market_daily      3,718
dim_date                8,059      fact_headline      3,154,916
dim_topic                  20      fact_statement        51,110
dim_dataset / dim_label     3      fact_market_daily      3,718
dim_instrument              1      dim_keyword              300
bridge_headline_keyword 4,221,537   cube_day_topic       19,481
```

Analysis window: **2015-06-30 to 2020-06-30**, derived from the data, never
hard-coded. 1,113,427 headlines fall inside it, and `Local` is 69.95% of them.

## Next: Phase 9, report and viva polish

The last phase. `reports/report.md` is generated and complete, so what remains
is presentation rather than construction:

- a viva sheet mapping each question to the command that answers it and the
  number it produces
- diagrams for the star schema and the pipeline
- tightening `README.md` as the single entry point
- checking `BLUEPRINT.md` research questions against the seven answers one more
  time, and reconciling the phase list with what was actually built

`dwm/inference/report.py` holds the prose, so wording changes are one file and
one `python -m dwm report`, not an edit to a 28 KB markdown file.

## Things a future session must not undo

**The keyword vocabulary cannot support association rules.** It yields 1.99
items per headline because its top terms are functional words, and the keyword
run produces **zero** rules. RQ5 mines attributes, which carry 6.00 items each.
The keyword result is reported as a finding about the feature, not hidden.

**`quarter` is deliberately absent from the default transaction items.** Year
and quarter are redundant in both directions. Including both produced 1,797
rules that were overwhelmingly year/quarter arithmetic, and pushed every
high-lift rule toward `2020-Q2`, rare only because the window ends mid-year.

**`Unknown` and `Other` are excluded from the RQ3 ranking.** `Unknown` tops the
raw ranking at 17.29% because it is a filing gap, not a subject. A reader told
"Unknown is the most sensational topic" has been told nothing.

**The sensationalism threshold is 0.2208**, the measured 95th percentile. It is
a chosen cut-off, so the sensitivity table must be shown with it.

**All figures on the unlabelled corpus are risk-signal rates.** Only the IFND
classifier states an accuracy, and only as an upper bound because part of the
Fake class is LSTM-augmented.

## Traps in this codebase

- **DuckDB's `SAMPLE n ROWS (bernoulli, seed)` is a parser error**, and
  `reservoir(n ROWS) REPEATABLE (seed)` **returns the wrong number of rows**
  (709 for 2000 requested). Use `dwm/mining/sampling.py`, which sorts on
  `hash(column, seed)`.
- **`silhouette_score` subsamples with no seed by default.** Pass `random_state`
  or the score moves between identical runs.
- **Read mlxtend's rule columns by name.** The frame is ordered
  `antecedents, consequents, antecedent support, consequent support, support,
  confidence, lift`; reading positionally is off by two and made every rule look
  like a tautology. Pass `use_colnames=True` to `apriori`/`fpgrowth`.
- **`unnest(?)` does not work in DuckDB 1.5.6.** A bound list cannot be cast to
  `INTEGER[]`. Do small aggregations in Python.
- **mlxtend 0.25 removed `use_ylib`.** `cross_val_score` raises when a class has
  fewer members than the fold count, so folds are capped by the smallest class.
- **A partial year poisons whole-year statistics.** 2015 has seven months; its
  wider spread made a flat series look like CV 0.39.
- **Never hard-code a dimension key.** `dim_dataset` numbers by sorted code, so
  `toi` is key 3, not 1. This was a real bug that pointed every headline at the
  wrong source.
- **`DWM_REPORTS_DIR` exists so tests cannot overwrite the real
  `reports/mining.json`.** It did, once, and the next report rendered three
  paired trading days as the finding.
- **Resolve the reports path by calling `reports_dir()`, not at import time.**
  A module-level constant froze it, and redirection then depended on import
  order.
- **DuckDB locks its file exclusively, even read-only.** The API therefore
  serves a copy at `warehouse/dwm.serve.duckdb`, so `dwm serve` and the CLI can
  run at the same time. Serving the live file made `dwm olap`, `dwm tables` and
  `dwm audit` all fail with "the process cannot access the file because it is
  being used by another process". Refresh the copy with `dwm serve
  --resnapshot` or `POST /query/reload`.

## Files worth reading in this order

| file | what it records |
|---|---|
| `docs/01-ingest-etl.md` | the four data traps, the measured data profile |
| `docs/02-warehouse-schema.md` | dimensions, clean tables, the Phase 2 gate |
| `docs/03-features-facts.md` | every measure's definition and why, the Phase 3 gate |
| `docs/04-mining.md` | the seven questions, and the three negative results |
| `docs/05-inference-api.md` | traceability, the guard rails, the API |
| `BLUEPRINT.md` | the original design, unchanged |
| `config/mining.yaml` | every mining threshold, seed and sample size |
| `reports/report.md` | the generated report |
| `reports/mining.json` | the machine-readable results it is rendered from |
