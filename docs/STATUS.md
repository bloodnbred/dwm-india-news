# Where the project stands

Written at the end of 2026-10-02, after Phase 4. Read this first in a new
session, then `README.md` for how to run things and `docs/` for the design
reasoning behind each stage.

## Done and verified on the real data

| Phase | Gate | Result |
|---|---|---|
| 0 Scaffold | pytest runs, `--help` works | pass, 157 tests |
| 1 Ingest | staging row counts equal source | pass, zero rejects |
| 2 ETL + dims | no null date keys, every category maps | pass |
| 3 Features + facts | fact counts equal clean counts, keys unique | pass |
| 4 OLAP | roll-up totals equal raw totals, cube equals fact | verified against the warehouse |

The warehouse is at `warehouse/dwm.duckdb` and is fully built. `run_all.ps1`
reproduces it from scratch in about 3.3 minutes.

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
hard-coded. 1,113,427 headlines fall inside it.

## Next: Phase 5-6, mining

The three modules in `dwm/mining/` are still stubs that raise
`NotImplementedError`. Everything they need already exists:

- `fact_headline` carries `date_key`, `topic_key`, `sentiment_*`,
  `sensational_score`, `is_risk_signal`, `in_window`
- `bridge_headline_keyword` plus `dim_keyword` give the 300-term vocabulary
  and the transactions for Apriori
- `fact_statement` carries `label_key` and the IFND text, for the classifier
- `fact_market_daily` carries `return_pct`, `volatility_20d`, `date_key`
- `cube_day_topic` gives daily headline counts and sentiment sums, already
  joined to trading days by the Phase 4 `drill_across`

The seven research questions map onto the work as follows, and the Phase 4
operations that feed each one are already working:

| Q | Question | Already available |
|---|---|---|
| 1 | topic mix over the window | `dwm olap --op topic_mix` |
| 2 | which months spike | `dwm olap --op top_months` |
| 3 | which categories are sensational | `dwm olap --op roll_up` |
| 4 | natural topic clusters | needs TF-IDF + K-Means on `fact_headline` |
| 5 | co-occurrence rules | needs Apriori and FP-Growth on the bridge |
| 6 | headlines vs Nifty | `dwm olap --op drill_across` |
| 7 | classifier vs majority baseline | needs the IFND text and `label_key` |

## Decisions already made that mining must respect

- **The sensationalism threshold is 0.2208**, the measured 95th percentile,
  flagging 5.01% of headlines. The first guess of 0.5 flagged 156 of 3.15M
  rows, which would have made Q3 unanswerable. Because it is a chosen cut-off,
  the report must present the rate across a range of thresholds, not this one
  number. The distribution is recorded in `config/features.yaml`.
- **`Local` is 70% of the window** and is a *where*, not a *what*. Use
  `dim_topic.topic_group` to separate `Place` from `Subject` when answering
  anything about subject mix.
- **The IFND majority-class baseline is 66.7%**, not 50%. A classifier that
  always answers "real" already scores 0.667, so accuracy alone is meaningless
  for Q7. Report precision and recall on the Fake class against that baseline.
- **IFND dates are unusable for time analysis.** 33% of statements have a
  month at best, 13% have a day with no year, 20% have nothing. The classifier
  does not use dates, but nothing time-based may be attempted on IFND.
- **Never call an unlabelled measure a fake-news rate.** On TOI it is a
  risk-signal rate. Only IFND supports accuracy claims, and only from the
  classifier.
- **Correlations are associations.** Q6 must be reported as a correlation over
  trading days, never as an effect of news on markets.
- **Use `sampling` seeds fixed** so results reproduce. Clustering and
  classifier results must be identical across runs; there is a test pattern
  for this in the other stages.

## Things that will bite you

- **Scoring 3.15M headlines takes about 165 seconds** and holds the database
  exclusively. Do not run any other stage against `warehouse/dwm.duckdb` at
  the same time; DuckDB allows one writer and the second process fails with
  "file is being used by another process". This cost me several wasted runs.
- **Do not pass `ignore_errors` to `read_csv`.** On duckdb 1.5.6 it silently
  discarded 15,730 of 56,714 IFND rows while `count(*)` still reported the
  full number. Always reconcile the materialised count.
- **`executemany` is a trap.** It is one statement per row and was 98% of the
  feature stage's runtime. Use the Arrow bulk insert helper.
- **The process pool is a trap on Windows.** It measured 39 rows/s against
  25,900 serial, because pickling headline text to workers costs more than
  the work. Serial wins; the pool is off by default.
- **Never hard-code a dimension key in SQL.** `dim_dataset` numbers rows by
  sorted code, so `toi` is key 3, not 1. Look it up. This was a real bug.
- **Guard rails for small data.** The blueprint requires the Phase 7 gate to
  fire on small data. Mining needs the same care: with a `--sample` run there
  may be no trading days, no labelled rows, or too few headlines for K-Means.
  Guard every statistic and return a stated reason rather than dividing by
  zero.

## Where the interesting reasoning lives

| file | what it records |
|---|---|
| `docs/01-ingest-etl.md` | the four data traps, the measured data profile |
| `docs/02-warehouse-schema.md` | dimensions, clean tables, the Phase 2 gate |
| `docs/03-features-facts.md` | every measure's definition and why, the Phase 3 gate |
| `BLUEPRINT.md` | the original design, unchanged |
| `config/features.yaml` | weights, thresholds, and the threshold calibration data |

The viva sheet in `BLUEPRINT.md` section 6 is the thing to be able to talk
through without notes. Every answer in it is backed by something in `docs/`.
