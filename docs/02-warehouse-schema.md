# 02 — Warehouse schema (Phase 2)

The conformed dimensions and cleaned tables built by `python -m dwm etl`, and
the decisions behind them. All numbers were measured on the real data on
2026-10-01.

## The shape

```
                  dim_date (8,059)      dim_topic (20)
                        |                    |
                        |                    |
   dim_dataset (3) -----+---- cln_headline --+   dim_label (3)
                        |     (3,154,916)         ^
                        |                          |
                        +---- cln_statement ------+
                        |       (51,110)
                        |
                        +---- cln_market_daily --- dim_instrument (1)
                                (3,718)

   map_category_topic (1,025)  raw category -> topic, keyed by dataset
```

A **fact constellation**: three fact tables at different grains sharing
conformed `date_key`, `topic_key` and `dataset_key`. That is what makes
drill-across possible in Phase 4.

## Dimensions

### `dim_date` — 8,059 rows, 2001-01-01 to 2023-01-24

One contiguous calendar day. No gaps (asserted by a test), so a drill-down to a
quiet date shows zero rather than a missing row.

`date_key` (YYYYMMDD integer), `full_date`, `year_no`, `quarter_no`,
`month_no`, `day_no`, `day_name`, `day_of_week`, `week_of_year`,
`day_of_year`, `year_month`, `year_month_key`, `is_weekend`, `is_month_end`,
`is_quarter_end`, `is_trading_day`.

The span is the union of all three sources: TOI to 2020-06-30, nifty to
2023-01-24. `is_trading_day` is derived from the presence of a market row and
matches `cln_market_daily` exactly (3,718).

Inside the analysis window, TOI published on **1,828 distinct days** while the
market traded on **1,235**. The 593-day difference is weekends and holidays:
headline volume exists on days with no price data. Any market-linked
comparison must join on trading days, not on calendar days.

### `dim_topic` — 20 rows

`topic_key`, `topic_name`, **`topic_group`**, `is_place`, `topic_sort`.

`topic_group` is `Place` / `Subject` / `Type` / `Other` / `Unknown`. It exists
because of a measured problem: over the full archive `Local` is 58% of rows,
and **inside the analysis window it is 70%**. `Local` is a *where*, not a
*what* — a city story can be about business or sport. Without the group
column, research question 1 ("how did the topic mix change") would be answered
by "Local went up or down", which is not a subject finding.

`Place` = Local, Nation, World. `Type` = Misinformation (IFND's
misinformation-type categories). `Subject` = the rest.

### `dim_dataset` — 3 rows

Carries `citation`, `license`, `provenance`, `is_labelled`,
`declared_precision`, `expected_rows` and `staged_rows` next to each other.
The provenance string is what the report's limitations section quotes, so the
unofficial status of the nifty mirror travels with the data rather than living
only in a config file.

### `dim_label` — 3 rows

| key | code | value | ground truth |
|---|---|---|---|
| 1 | REAL | 1 | yes |
| 2 | FAKE | 0 | yes |
| 3 | UNLABELLED | NULL | **no** |

`is_ground_truth` encodes the blueprint's honesty rule in the schema: only the
first two rows can support an accuracy claim. TOI headlines and market rows
join to `UNLABELLED`, and any measure over them is a risk-signal rate.

### `dim_instrument` — 1 row

`NIFTY50`, exchange NSE, currency INR, sourced from `nifty`.

## Clean tables

### `cln_headline` — 3,154,916 rows (from 3,297,172 staged)

Grain: **one headline per (publish_date, headline_text)**.

| measure | value |
|---|---:|
| staged rows | 3,297,172 |
| clean rows | 3,154,916 |
| duplicates removed | 142,256 |
| rows inside the window | 1,113,427 |
| multi-category headlines | 111,146 |

**Why (date, text) and not text alone.** Measured: 37,629 headline texts appear
on more than one date, and 111,146 (date, text) pairs were filed under more
than one category. Three candidate grains:

| grain | rows | problem |
|---|---:|---|
| text | 3,082,589 | merges genuinely separate publications 37,629 times |
| date + text | 3,154,916 | chosen |
| date + text + category | 3,275,587 | multi-counts 111,146 headlines in every topic analysis |

The middle option is the only one that neither merges distinct events nor
triple-counts one headline across desks. Because a headline can carry several
categories, the row keeps `staged_rows` (how many times it was filed),
`category_count` and `is_multi_category`, and the primary category is the one
it was filed under most often, ties broken alphabetically. Nothing is lost:
the count is recoverable from `map_category_topic` and `stg_toi`.

`word_count` uses `regexp_split_to_array(text, '\s+')`, not a plain space
split, so runs of whitespace do not inflate it.

### `cln_statement` — 51,110 rows (from 56,714 staged)

Grain: one distinct statement text. `label_code` is normalised to
REAL / FAKE / UNLABELLED.

**Date handling.** Post-dedup precision:

| precision | rows | `source_date` |
|---|---:|---|
| `month` | 33,964 | 2020-10-01 (month start) |
| `month_day` | 6,789 | **NULL** — a day with no year |
| `none` | 10,357 | **NULL** — no date in the source |

So **17,146 of 51,110 statements (33.5%) have no resolvable calendar date**,
and `date_key` is NULL for all of them. A test asserts that
`count(source_date IS NULL)` equals `count(precision IN ('none','month_day'))`,
so a month-day row can never acquire an invented date.

A bug worth recording: the first implementation picked `source_date` and
`date_precision` with two independent `any_value()` calls. Those can come from
*different* rows of the same duplicate group, producing a dated row labelled
`none` or vice versa — the two counts disagreed by 231 rows. The fix selects
one representative row with `QUALIFY row_number() = 1`, ordered so a row that
has a date beats one that does not. There is a named regression test for it.

### `cln_market_daily` — 3,718 rows

One trading day. `open`, `high`, `low`, `close`, `volume`, `turnover`.
Verified clean at ingest: no NULL prices, no rows with high < low, no close
outside [low, high], no non-positive close, all dates distinct.

## The window is a flag, not a filter

Every cleaned row is kept; `in_window` marks membership of the analysis
window. The window is derived from `max(publish_date)` in the data
(2020-06-30) minus `--years` (default 5) → **2015-06-30 to 2020-06-30**. No
year is hard-coded; change `--years` and everything downstream follows.

A hard filter would have made the funnel unable to report that 2,041,489
headlines sit outside the window. A test asserts an out-of-window row survives
with `in_window = false`.

## The Phase 2 gate

> no null date keys, every raw category maps to a topic

Measured result: **passed**.

| check | result |
|---|---:|
| `cln_headline` null `date_key` | 0 |
| `cln_market_daily` null `date_key` | 0 |
| `cln_headline` null `topic_key` | 0 |
| orphan `date_key` | 0 |
| orphan `topic_key` | 0 |
| `cln_statement` null `date_key` | 17,146 (exempt, see below) |

The statement exemption is explicit in the gate's own output, with the reason
attached, rather than being quietly dropped from the check. A third of IFND
has no usable date; the alternative would be inventing years.

Additional integrity checks run after the build and are all zero: surrogate
keys unique, `dim_date.date_key` unique, `dim_topic.topic_key` unique, no
duplicate (date, text) in `cln_headline`, no duplicate text in
`cln_statement`, no duplicate date in `cln_market_daily`.

## Where the topic mapping went

`map_category_topic` (1,025 rows) is keyed by `(dataset_code, raw_category)`
because TOI and IFND resolve the same-looking string differently. Every row
resolves to a `topic_key`; unmapped count is 0.84% of rows, all landing in
`Other` rather than being dropped, so headline counts still reconcile against
staging.

IFND's `Category` field mixes two kinds of value, which is a schema finding
worth stating: `GOVERNMENT`, `POLITICS`, `ELECTION`, `COVID-19`, `VIOLENCE`
are topics, while `TERROR`, `MISLEADING`, `MISLEADIND` (a typo in the source,
18 rows) and `TRAD` are misinformation *types*. The types say nothing about
what the news is about, so they map to the `Misinformation` topic with
`topic_group = 'Type'` rather than being forced into a subject bucket.

## Cost

On the full 227 MB TOI file: dimensions 1.2s, clean tables 11.6s, peak memory
within the 4 GB DuckDB limit. Single-threaded Python is used only for the
1,025 category lookups and the 56,714 IFND date parses; the 3.3M-row date
parsing happens in SQL.
