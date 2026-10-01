# 03 — Features, facts and cubes (Phase 3)

What `python -m dwm features` and `python -m dwm build` compute, and why each
measure is defined the way it is. All numbers measured on the real data.

## Pipeline position

```
cln_headline / cln_statement / cln_market_daily
        |
        |  features: one pass, sentiment + sensationalism + counts + keywords
        v
feat_headline, feat_statement, feat_market_daily
dim_keyword, bridge_headline_keyword
        |
        |  build: conformed keys + measures
        v
fact_headline, fact_statement, fact_market_daily
cube_month_topic, cube_year_topic, cube_topic_sentiment, cube_day_topic
```

**Why features and facts are separate tables.** The feature stage is the
expensive, restartable one: 3.15M rows through VADER. Keeping its output means
a failed `build` can be re-run in seconds, and a reader can inspect a
sentiment score without re-deriving it. The cost is that the measures exist
twice, once keyed by clean-table id and once inside the fact. That is a
deliberate trade, and the fact is the copy queries should use.

**One pass, not three.** Sentiment, the five sensationalism sub-signals, the
word counts and the keyword extraction all come out of a single pass over each
headline. Three separate passes would triple the I/O over 227 MB of text for
no benefit.

## Sentiment

VADER (`vaderSentiment`), chosen in the blueprint because it needs no training
and works offline. Four scores per row: `sentiment_compound`, and the
`sentiment_positive` / `sentiment_negative` / `sentiment_neutral` proportions.

`sentiment_band` buckets compound at VADER's own guidance points, ±0.05 scaled
to the config thresholds of ±0.5:

| band | rows share (window) |
|---|---:|
| negative | see Phase 4 |
| positive | see Phase 4 |
| neutral | remainder |

Lexicon sentiment has a known weakness: it reads wording, not truth. A
headline can be angrily worded and entirely accurate. This is a style band and
is named as one.

## Sensationalism

A weighted composite of five bounded sub-signals. Each is squashed into [0,1]
by dividing by a saturation point, weighted, then clipped to [0,1]. The
weights sum to 1.0, so the score reads as a rough fraction of maximum
possible sensationalism.

| sub-signal | weight | saturates at | why |
|---|---:|---:|---|
| `caps_token_ratio` | 0.35 | 0.30 | shouting is the loudest style cue |
| `exclamation_count` | 0.20 | 2 | punctuation emphasis |
| `question_count` | 0.10 | 2 | weaker, and often genuine |
| `superlative_count` | 0.20 | 2 | extreme-claim vocabulary |
| `urgency_count` | 0.15 | 2 | manufactured urgency |

Two details that matter:

- **CAPS tokens need 3+ characters** (`min_caps_length`). Otherwise "A", "I"
  and "PM" register as shouting, which would fire on a large share of ordinary
  headlines. The ratio's denominator is *alphabetic* tokens, so a numeric
  headline is not counted as shouting for having no lowercase.
- **`superlative` and `urgency` lexicons are disjoint**, and a test asserts it.
  The word `exclusive` originally appeared in both, which inflated two
  sub-signals from one token and quietly broke the independence the composite
  assumes. `exclusive` is an attention signal, so it now lives only in
  `URGENCY`.

**`is_sensational` uses a chosen threshold of 0.5, not a fitted one.** It is a
judgement, so the report must show the rate across a range of thresholds
rather than presenting 0.5 as if it were discovered.

**The honesty rule is enforced in the names.** `is_risk_signal` mirrors
`is_sensational` exactly for TOI, because TOI has no classifier signal
available — only style can be measured on unlabelled headlines. Neither
column may be described as a fake-news rate. Only IFND carries ground truth,
and only the Phase 6 classifier may make an accuracy claim.

## Keywords

For the Phase 6 Apriori transactions. The vocabulary is capped at **300
terms**, which is the blueprint's limit and the reason the itemset search
stays tractable.

Built by document frequency over a **200,000-row sample** of `cln_headline`,
not the full corpus. The vocabulary is capped at 300 anyway, and the ordering
within the top 300 is not sensitive to small frequency differences, so an
exact count over 3.15M headlines would buy nothing. Measured: 81,647 candidate
terms narrowed to 300. Terms are sorted by frequency descending then term
ascending, so the vocabulary is deterministic rather than dict-order
dependent, and a test asserts two builds agree.

Filters applied: length ≥ 3, not a stopword, not in a blocklist (`news`,
`india`, `said`, `day`, `update`, `video`, ...), and must contain a letter.
Term frequency is counted on a *set* per document, so document frequency is
what is being ranked.

`max_per_headline: 8` keeps each transaction small. `bridge_headline_keyword`
is therefore at most 8 rows per headline; duplicates are impossible because
extraction intersects a set.

On the real corpus: **300 vocabulary terms** and the bridge is built for all
3,154,916 headlines. `dim_keyword` carries `doc_frequency` measured over the
whole corpus, not the sample, because that number is reported.

**The stopword list lives in code, not NLTK.** A list that silently changed
between runs would move every keyword-based number in the report. The list is
deliberately short: the corpus is headlines of ~45 characters where most
function words are already rare, and an aggressive list would strip meaning.

## Market features

Computed in SQL, not Python, because they are window functions:

| column | meaning |
|---|---|
| `return_pct` | day-over-day percent change; NULL on the first row |
| `abs_change` | close minus previous close |
| `day_range` | high minus low |
| `range_pct` | day range over previous close |
| `intraday_change` | close minus open |
| `volatility_20d` | 20-session rolling standard deviation of `return_pct` |
| `return_sign` | +1 / 0 / −1 |

**`volatility_20d` is NULL until the window is full.** A "20-day volatility"
computed from three observations is not a 20-day volatility, and publishing it
as one would make the Phase 6 correlation meaningless. The first 19 sessions
of the series are therefore NULL, not a smaller-window estimate.

These give Phase 6 both halves of research question 6: business headline
sentiment and volume against Nifty *returns* and *volatility*.

## Fact tables

`fact_headline` (3,154,916), `fact_statement` (51,110) and
`fact_market_daily` (3,718) each carry their conformed dimension keys plus the
measures. Nothing is pre-averaged.

**Keys are looked up, never hard-coded.** This was a real bug. `dim_dataset`
assigns keys by sorting the configured codes, so `toi` is key **3**, but the
fact DDL originally wrote a literal `1` — every headline would have pointed at
the wrong source and nothing in the row counts would have revealed it. The DDL
now resolves `dataset_key`, `label_key` and `instrument_key` from the
dimension tables at build time. Two regression tests cover it.

**`label_key` was worse.** The statement DDL interpolated
`LABEL_KEY = "1, 2, 3"` into the select list, which parsed as three constant
expressions, so *every* statement got `label_key = 3` (`UNLABELLED`)
regardless of its real label. It is now a join to `dim_label` on `label_code`,
and a test asserts the two distinct labels produce two distinct keys.

## Cubes

Four cubes, all derived and rebuildable:

| cube | grain | purpose |
|---|---|---|
| `cube_month_topic` | year-month × topic | monthly roll-ups, seasonality |
| `cube_year_topic` | year × topic | the RQ1 trend |
| `cube_topic_sentiment` | topic | the denominator for every rate |
| `cube_day_topic` | day × topic | drill-across onto market days |

**Sums, never averages.** This is the rule the viva sheet states, and it is
enforced by a test that rejects any column named like a mean (`*_avg`,
`avg_*`, anything containing "mean"). Every cube stores a `headline_count`
plus `sum_<measure>` columns, so a mean is always recoverable as
`sum / count`. Flags are stored as 0/1 counts (`sensational_count`,
`risk_signal_count`, `negative_count`), so a *rate* is `count / headline_count`
rather than a stored percentage.

`cube_day_topic` is not in the blueprint's original list. It is here because
research question 6 needs daily headline counts and sentiment sums lined up
against daily Nifty returns, and without a daily cube that join would rescan
3.15M fact rows.

Cube totals are reconciled against the fact table in the Phase 3 gate. All
three headline cubes must equal `count(*) FROM fact_headline WHERE in_window`.

## The Phase 3 gate

> fact row counts equal clean row counts; keys unique

Measured result: **passed**.

The count check is the one that carries weight. Every fact is built with an
inner join to its feature table, so any clean row the feature stage failed to
score would vanish — and a `count(*)` on the fact table alone would look
perfectly healthy. Comparing against the clean table is the only way to see it.

Also enforced: surrogate keys unique, no duplicate bridge pairs, no orphans
into `fact_headline` / `dim_keyword` / `dim_date` / `dim_topic` /
`dim_label`, and all four cubes reconciling with the fact.

## Two more bugs found while building

**A mis-cased label silently deleted fakes.** `cln_statement` normalised the
label with a SQL `CASE` over the literals `'TRUE'` and `'FALSE'`. The IFND
source also writes `Fake`, which matches neither, so every such row fell
through to `UNLABELLED`. Every one of those rows would have been dropped from
the Phase 6 classifier's training data without any error. The mapping now
comes from `config/datasets.yaml` and is applied by the tested
`normalise_label`, via a `map_label_value` table. The regression test asserts
no `UNLABELLED` row survives when the source labels are recognised.

**The gate's own pass condition was wrong.** It read `not key_checks`, which is
`False` for any non-empty dict — and the dict always has entries. The gate
could never pass. It now reads `not any(key_checks.values())`.

## Cost

Full corpus, 8 logical cores: vocabulary 2.0s, headline scoring with the
process pool, statement scoring, market features in SQL. VADER alone measures
~41,000 rows/s single-threaded, so the serial path is about 80s for 3.15M
headlines; the pool exists because it is free, not because it is required.
`runtime.use_multiprocessing: false` forces the serial path, which is what the
tests use for determinism.
