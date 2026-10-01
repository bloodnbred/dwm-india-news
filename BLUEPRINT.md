# DWM Project Blueprint: Indian News Warehouse (`dwm-india-news`)

A backend-heavy Data Warehousing and Mining project. It loads several real datasets into a DuckDB warehouse (fact constellation), runs OLAP and mining operations in SQL and Python, and generates a final inference about trends in Indian news from the data.

---

## 1. Final decisions

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best mining libraries, easy to explain in a viva |
| Warehouse | **DuckDB** (single file `warehouse/dwm.duckdb`) | No server to install on Windows, fast on millions of rows, full SQL including `ROLLUP`, `CUBE`, `GROUPING SETS`, `PIVOT`, window functions. The professor can open the file and run SQL |
| Schema | **Fact constellation** (galaxy): several fact tables sharing conformed dimensions | Real multi-dataset warehouse design; enables drill-across |
| Mining | scikit-learn (TF-IDF, K-Means, Naive Bayes, Logistic Regression), mlxtend (Apriori, FP-Growth), scipy | Standard, reproducible |
| Sentiment | VADER lexicon | Fast, no training, works offline |
| Backend | CLI (Typer) plus FastAPI | Backend is the product |
| Frontend | Streamlit, thin (reads from the API/modules, no logic) | Python only, no JS build |
| Tests | pytest | Phase gates |
| Inference | Deterministic templates filled by SQL results. No LLM | Numbers are traceable, no hallucination risk |
| Task runner | `python -m dwm <command>` | Makefile is awkward on Windows |

### Datasets (final set)

| Code | Dataset | Role | Fact table |
|---|---|---|---|
| `toi` | Times of India news headlines (about 3.3M rows, 2001 to mid-2020) | Primary, unlabelled, large | `fact_headline` |
| `ifnd` | Indian Fake News Dataset (Sharma and Garg, 2021), labelled Real/Fake | Validation of the classifier | `fact_statement` |
| `nifty` | Nifty 50 daily index prices covering the same window | Numeric dataset for cross-dataset inference (drill-across) | `fact_market_daily` |

Optional 4th: India COVID-19 daily case counts, to test whether COVID headline volume follows case counts. Only add it after the first three work.

**Important:** I have not verified current download links or exact column names. Download each file yourself, open it, and adjust `config/datasets.yaml` if headers differ. Never invent or "recreate" missing data.

Where to look:
- `toi`: Hugging Face `times_of_india_news_headlines`, or Kaggle / Harvard Dataverse "India News Headlines Dataset". Expected columns: `publish_date` (YYYYMMDD), `headline_category`, `headline_text`.
- `ifnd`: the IFND paper's dataset (Complex & Intelligent Systems, 2021). Part of the Fake class was produced by augmentation. State this limitation in the report.
- `nifty`: any daily Nifty 50 CSV (Kaggle, NSE or Yahoo Finance export) with Date, Open, High, Low, Close and optionally Volume, covering at least mid-2015 to mid-2020.

### The window
"Last five years" = `[max(toi.date) - 5 years, max(toi.date)]`, computed from the data. Never hard-code years. Configurable via `--years`.

### Metric wording (honesty rule)
On unlabelled headlines never say "fake news rate". Use **risk-signal rate**: share of headlines flagged by the sensationalism and classifier signals. It is a trend indicator, not a fact-check. Only the labelled IFND data can support accuracy claims.

---

## 2. Architecture

```
data/raw/{toi,ifnd,nifty}/  (gitignored)
        |
   [1] INGEST  -> stg_* tables (as-is, plus audit)
        |
   [2] ETL     -> clean, dedupe, parse dates, map topics, apply window
        |
   [3] FEATURES-> word counts, sentiment, sensationalism, keywords
        |
   [4] WAREHOUSE (DuckDB): dims + fact_headline + fact_statement + fact_market_daily + bridge + cubes
        |
   [5] OLAP    -> slice, dice, roll-up, drill-down, pivot, cube, drill-across
        |
   [6] MINING  -> trends, bursts, clustering, Apriori, classifier, cross-dataset
        |
   [7] INFERENCE -> facts.json -> report.md
        |
   [8] FastAPI  -> Streamlit dashboard (thin)
```

---

## 3. Research questions (what the final inference answers)

1. How did the topic mix of Indian headlines change over the five-year window?
2. Which months spike in volume or sensationalism, and which known events does each spike coincide with?
3. Which categories use the most sensational or negative language, and how did that trend?
4. What natural topic clusters exist in the headlines (TF-IDF plus K-Means)?
5. Which co-occurrence patterns exist (Apriori rules such as `topic=Business, year=2016 => sensational=high`)?
6. Does business headline sentiment or volume relate to Nifty returns or volatility (lagged correlation, event windows)? Association, not causation.
7. How well does a classifier separate Real from Fake on the labelled data, compared with the majority baseline?

---

## 4. Phases and gates

| Phase | Output | Gate (must pass before next) |
|---|---|---|
| 0 Scaffold | repo, config, CLI skeleton | `pytest` runs, `python -m dwm --help` works |
| 1 Ingest | `stg_toi`, `stg_ifnd`, `stg_nifty`, `etl_audit` | row counts in staging equal rows in source file |
| 2 ETL + dims | clean tables, `dim_date`, `dim_topic`, `dim_dataset`, `dim_label`, `dim_instrument` | no null date keys, every raw category maps to a topic |
| 3 Features + facts | `fact_headline`, `fact_statement`, `fact_market_daily`, keyword bridge, cube tables | fact row counts equal clean row counts; keys unique |
| 4 OLAP | `dwm/olap/` module, SQL cookbook | roll-up totals equal raw totals; cube equals fact |
| 5 Mining A | trends, bursts, cross-dataset | slope matches a manual check on a tiny fixture |
| 6 Mining B | clustering, Apriori, classifier | classifier metrics on test split only; fixed seeds reproduce |
| 7 Inference | `facts.json`, `report.md` | every number in report traces to a query; guard rails fire on small data |
| 8 API + dashboard | FastAPI, Streamlit | all endpoints return 200 on the dev sample |
| 9 Polish | docs, final report, viva sheet | full run on real data end to end |

Development rule: build and test every phase with `--sample 50000` rows. Run the full dataset only at the end of a phase.

---

## 5. Final deliverables

1. The code repo (`dwm-india-news`).
2. `warehouse/dwm.duckdb` (do not commit if large).
3. `reports/final_report.md` generated by the inference engine.
4. Project report (Word/PDF) with: problem, datasets and limitations, ETL steps and data-quality funnel, schema diagram, OLAP examples with SQL, mining results, final inference, conclusions, limitations.
5. Short demo: dashboard walkthrough.

---

## 6. Viva cheat sheet

- **Why a fact constellation?** Multiple fact tables (headlines, labelled statements, market prices) have different grains but share date, topic and dataset dimensions. That allows drill-across.
- **Star vs snowflake vs constellation?** Star: one fact, denormalised dims. Snowflake: normalised dims. Constellation: several facts sharing dims.
- **Why store sums in cubes, not averages?** Sums roll up exactly; averages do not. Averages are computed as sum / count at query time.
- **Why DuckDB?** Columnar analytical engine, zero setup, full SQL OLAP features.
- **Apriori vs FP-Growth?** Same rules, FP-Growth avoids candidate generation and is faster. We run both and compare runtime.
- **Why not call it "fake news rate"?** The headlines are unlabelled. We measure style signals only.
- **Why validate on 30% test only?** Choosing thresholds on training data and reporting on unseen data avoids optimistic metrics.
- **Limitations:** headlines only, English only, TOI only (one outlet), IFND partly augmented, lexicon sentiment, correlation is not causation.

---

## 7. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Dataset download blocked or missing | Do not fabricate. Use the other datasets and state the gap in the report |
| Column names differ | Edit `config/datasets.yaml` aliases |
| Memory pressure on 1M+ rows | Chunked processing (`--chunk 100000`), DuckDB does aggregation, `--sample N` |
| Sentiment too slow | Multiprocessing with Windows-safe `if __name__ == "__main__":` guard, or sample for clustering |
| Apriori too slow | Limit vocabulary to top 300 keywords, sample 100k transactions, `max_len=3`, use FP-Growth |
| Dates in mixed formats | Auto-detect, count failures into `etl_audit`, continue |
| TOI has no category column in your copy | Assign topic `Unknown` and run the topic-by-keyword fallback in `docs/01-ingest-etl.md` |
| IFND has no dates | Allow nullable `date_key` in `fact_statement`; skip time-based IFND analysis |
