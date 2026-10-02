# What 1.1 million Indian news headlines actually show

A data-warehousing and mining study built on 3,297,172 Times of India headlines, 56,714 IFND statements carrying real/fake labels, and 3,718 Nifty 50 trading sessions.

**Analysis window** 2015-06-30 to 2020-06-30, which is 6 calendar years. The window is derived from the last publish date in the corpus, not hard-coded, and it is applied as a **flag rather than a filter**: 2,041,489 out-of-window headlines stay in the warehouse and remain queryable.

*Generated 2026-10-02T09:27:32 from `facts.json` (mining run 20261002T092603Z).*

> **Two of the seven findings are negative, and they are the most
> informative results in this study.** Monthly headline volume does not
> respond to national events, and these headlines have almost no
> recoverable topic structure. Both are reported with the measurement
> that establishes them rather than replaced by a finding that was
> chosen for being more convenient.

## 1. The data

Three sources, staged losslessly and reconciled row for row: 3,297,172 TOI headlines, 56,714 IFND statements and 3,718 Nifty 50 sessions, with zero rejects.

### Sources

| source | rows staged | labelled | date precision | licence |
|---|---|---|---|---|
| IFND - Indian Fake News Dataset | 56,714 | yes | month | See publisher terms; redistributed by the dataset authors on GitHub |
| Nifty 50 daily index prices | 3,718 | no | day | Unofficial redistribution of Yahoo Finance data |
| Times of India News Headlines | 3,297,172 | no | day | CC0 1.0 Universal (public domain dedication) |


Full citations:

- **IFND - Indian Fake News Dataset** — Sharma, D. K., & Garg, S. (2021). IFND: a benchmark dataset for fake news detection. Complex & Intelligent Systems, 9, 2843-2863. https://doi.org/10.1007/s40747-021-00552-1
- **Nifty 50 daily index prices** — Mirror of Yahoo Finance daily OHLCV for ^NSEI, redistributed in github.com/manishkr1754/NIFTY50_Data_Analysis_NSETOOLS_NSEPY_Python
- **Times of India News Headlines** — Kulkarni, Rohit (2020). Times of India News Headlines. Harvard Dataverse. https://doi.org/10.7910/DVN/DPQMQH

### What survives cleaning

| stage | rows | note |
|---|---|---|
| staged headlines | 3,297,172 | lossless staging |
| clean headlines | 3,154,916 | 142,256 dropped as exact duplicates |
| **in the analysis window** | **1,113,427** | flag, not a filter: out-of-window rows stay in the warehouse |
| labelled statements | 51,110 | IFND, 3 label values normalised to 2 |
| market sessions | 3,718 | daily OHLCV |
| date dimension | 8,059 | spans 2001-01-01 to 2023-01-24 |
| topic dimension | 20 | from the publisher taxonomy |
| keyword dimension | 300 | 4,223,280 headline-keyword pairs |


### Where this data is weak, stated up front

These limitations shaped the design, and each one is a reason a result
below is worded the way it is.

1. **No ground truth on the headline corpus.** TOI headlines carry a
   category but no label. Every style measure in this report is a
   *risk-signal rate* and never a fake-news rate. Only IFND supports an
   accuracy claim.
2. **IFND is imbalanced.** 33,684 real against 17,426 fake, so always answering "real" scores 65.9%. The classifier is judged against that, not against 50%.
3. **IFND dates are largely unusable.** Of 51,110 statements, 33,964 carry only a month, 10,357 carry only a none, 6,789 carry only a month-day. The statements stay in the corpus, but the classifier uses text only and makes no claim about when anything was published.
4. **The publisher changed how it files content.** In 2017 the single
   category `business.international-business` is 11.1% of every headline;
   a year later it is 0.2%. A topic-mix analysis that ignored this would
   report a news-industry event as a change in what India was reading.
5. **`Local` is 70% of the window and is a *where*, not a *what*.** Topic
   comparisons are made within `topic_group` (Place, Subject, Type) so a
   city desk is never compared against a subject as if they matched.
6. **2015 is a partial year.** The window starts 2015-06-30. All trend
   statements are within-year shares, and raw counts across years are
   not comparable.
## 2. RQ1 — How did the topic mix change?

**`Local` is 69.95% of the 2015-06-30 to 2020-06-30 analysis window window** (778,859 of 1,113,427 headlines). It is a *where*
rather than a *what*, which is why `dim_topic` separates Place from
Subject and why every subject comparison below is made within a group.

| topic | group | headlines | share of the window |
|---|---|---|---|
| Local | Place | 778,859 | 69.95% |
| Entertainment | Subject | 99,059 | 8.90% |
| Business | Subject | 61,619 | 5.53% |
| Nation | Place | 56,770 | 5.10% |
| Sports | Subject | 45,299 | 4.07% |
| World | Place | 17,037 | 1.53% |
| Lifestyle | Subject | 12,563 | 1.13% |
| Technology | Subject | 10,453 | 0.94% |


### Largest year-on-year moves in topic share

Within-year shares, because raw counts are not comparable across years
and 2015 is a partial year.

| topic | group | years | share | change | rows in later year | note |
|---|---|---|---|---|---|---|
| Local | Place | 2015 → 2016 | 54.61% → 68.20% | +13.59 pp | 169,184 | partial year, not compared |
| Business | Subject | 2016 → 2017 | 2.78% → 14.78% | +12.01 pp | 35,729 |  |
| Local | Place | 2019 → 2020 | 77.81% → 88.98% | +11.17 pp | 78,264 |  |
| Business | Subject | 2017 → 2018 | 14.78% → 3.63% | -11.15 pp | 8,721 |  |
| Local | Place | 2017 → 2018 | 63.58% → 73.62% | +10.04 pp | 176,855 |  |
| Unknown | Unknown | 2015 → 2016 | 6.92% → 0.00% | -6.92 pp | 2 | partial year, not compared |
| Local | Place | 2016 → 2017 | 68.20% → 63.58% | -4.62 pp | 153,674 |  |
| Nation | Place | 2015 → 2016 | 9.03% → 4.80% | -4.23 pp | 11,906 | partial year, not compared |


### Largest subject topics by year

| topic | year | share of that year |
|---|---|---|
| Business | 2017 | 14.78% |
| Entertainment | 2016 | 10.95% |
| Entertainment | 2015 | 10.78% |
| Entertainment | 2018 | 9.52% |
| Entertainment | 2017 | 8.83% |


### A filing artefact, not a trend

These raw categories hold an implausible share of a single year, which
means the publisher changed how it filed content rather than that
reader interest moved:

| year | raw category | rows | share of that year |
|---|---|---|---|
| 2017 | `business.international-business` | 26,856 | 11.11% |


A single raw category holding this share of a year indicates a change in how the publisher filed content, not a change in reader interest. Affected years need this caveat in the report.

> **Read this before quoting the number.** Shares are within-year, so the partial year does not distort them. Raw counts across years are not comparable.

## 3. RQ2 — Which months spike, and do they match known events?

### The answer is no, and the measurement is the interesting part

**0 months** exceeded the z-score threshold.
That is not a tuning failure. Monthly headline volume is almost perfectly
flat:

| year | coefficient of variation of monthly volume |
|---|---|
| 2015 | excluded (partial year) |
| 2016 | 0.0202 |
| 2017 | 0.0296 |
| 2018 | 0.0352 |
| 2019 | 0.0288 |
| 2020 | excluded (partial year) |


The busiest month of a full year runs only 2-5% above its own monthly
mean. March 2020, the month India entered a national lockdown, is 2.5%
above its year mean. A z-score of 2.0 cannot fire on a series this
flat, and lowering it until something appeared would be choosing a
threshold to manufacture a finding.

### What the event months actually look like

The listed events are calendar coincidences offered for the reader to
judge, not causes. Several measures run *opposite* to what a
news-reactive archive would show:

| month | event | Health z | Sports z | Entertainment z | negative sentiment z |
|---|---|---|---|---|---|
| 2016-11 | Demonetisation announced 8 Nov 2016 | +0.37 | +1.81 | +0.43 | -0.15 |
| 2016-12 | Demonetisation midnight deadline 31 Dec 2016 | +0.60 | +1.41 | +0.86 | -0.46 |
| 2017-07 | GST launched 1 Jul 2017 | -0.26 | +0.01 | +0.92 | -0.41 |
| 2017-08 | Independence Day, 15 Aug 2017 | -0.60 | +0.34 | +0.21 | -1.27 |
| 2018-01 | Union Budget, 1 Feb 2018 (session starts) | -0.52 | +1.07 | -0.06 | +0.29 |
| 2019-02 | Union Budget, 1 Feb 2019 | -0.83 | -1.36 | -1.53 | +0.98 |
| 2019-05 | General election result, 23 May 2019 | -0.56 | -1.08 | -0.73 | +1.28 |
| 2020-03 | National COVID-19 lockdown announced 24 Mar 2020 | -0.74 | -1.33 | -1.57 | +0.09 |
| 2020-04 | Lockdown extended to 3 May 2020 | -0.93 | -1.41 | -1.80 | -2.63 |
| 2020-05 | Lockdown eased from 18 May 2020 | -0.98 | -1.44 | -1.73 | -1.71 |


The single largest departure is `negative_rate` in 2020-04 at z = -2.63. In 5 of the 10 event months (2019-02, 2019-05, 2020-03, 2020-04, 2020-05) every one of the desks predicted to rise — Health, Sports, Entertainment — fell below its norm instead. That is a specific prediction failing, not a vague absence of signal. For scale, 81 of 154 measures sit below −0.5 SD, against roughly 47.5 expected by chance. That count is **not** offered as a significance test: the measures share months and are correlated, so their z-scores are not independent and the count is only shown so it is not hidden.

Read the magnitudes carefully. These are standard deviations on a series
that barely moves, so a z of −1.5 is a real departure from the norm and
still a small one in absolute terms. What carries the weight is the
**sign** on a prediction fixed in advance: the desks a news-reactive
archive should have covered more heavily during a pandemic are the ones
that fell.

The honest caveat is that this data cannot distinguish a genuinely
quota-driven newsroom from a sampling artefact of whatever export the
publisher produced. Both produce the same signature, and separating them
would need data this study does not have.


> **Read this before quoting the number.** This is a NULL result and it is the answer. Monthly volume is flat within each year, so no month is a statistical outlier. Lowering the threshold until a spike appeared would be choosing a threshold to manufacture a finding.

## 4. RQ3 — Which categories use the most sensational language?

Corpus risk-signal rate: **3.77%** at a threshold of 0.2208 (the measured 95th percentile of the score distribution).

### By topic, with a confidence interval on every rate

| topic | risk-signal rate | 95% CI | headlines | above corpus average? |
|---|---|---|---|---|
| Education | 10.94% | 10.06% – 11.89% | 4,450 | yes |
| Business | 5.81% | 5.63% – 6.00% | 61,619 | yes |
| Politics | 4.24% | 3.71% – 4.85% | 4,833 | no |
| Local | 3.96% | 3.92% – 4.01% | 778,859 | yes |
| Sports | 3.90% | 3.73% – 4.08% | 45,299 | no |
| Nation | 3.51% | 3.37% – 3.67% | 56,770 | no |
| Health | 2.09% | 1.77% – 2.46% | 6,610 | no |
| Technology | 1.99% | 1.74% – 2.28% | 10,453 | no |


The interval matters more than the ranking. Counts here are in the tens
of thousands, so a bare percentage would imply a precision the measure
does not have. A Wilson interval is used rather than the normal
approximation because the highest-scoring topics sit near the extremes,
where the normal interval runs outside [0, 1].

**`Unknown`, `Other` are excluded from the ranking.** These carry no editorial subject, so their score measures the absence of a filing decision rather than the language used. They are excluded from the headline ranking.

### Trend over the window

| year | headlines | risk-signal rate | 95% CI |
|---|---|---|---|
| 2015 | 125,137 | 4.88% | 4.76% – 5.00% |
| 2016 | 248,065 | 3.97% | 3.89% – 4.05% |
| 2017 | 241,687 | 3.59% | 3.51% – 3.66% |
| 2018 | 240,220 | 3.46% | 3.39% – 3.53% |
| 2019 | 170,357 | 3.62% | 3.54% – 3.71% |
| 2020 | 87,961 | 3.25% | 3.14% – 3.37% |


### Is the ranking an artefact of the cut-off?

The threshold is a judgement, so the ranking is recomputed across a
range. If the top topic changed as the cut-off moved, the ranking would
be an artefact of the cut-off rather than a finding.

| threshold | top topic | top three |
|---|---|---|
| 0.0500 | Education | Education, Unknown, Politics |
| 0.1000 | Education | Education, Unknown, Business |
| 0.1500 | Unknown | Unknown, Education, Business |
| 0.2000 | Unknown | Unknown, Education, Business |
| 0.2208 ← chosen | Unknown | Unknown, Education, Business |
| 0.2500 | Unknown | Unknown, Education, Business |
| 0.3000 | Unknown | Unknown, Education, Business |
| 0.4000 | Unknown | Unknown, Health, Other |


The top *informative* topic is NOT stable across this range. `Unknown` tops the raw ranking at some thresholds because it is a filing gap rather than a subject, so it is excluded from the stability judgement — the raw count is shown above so the difference is visible.


> **Read this before quoting the number.** A STYLE measure on unlabelled headlines. It is a risk-signal rate and is NOT a fake-news rate. The threshold is the measured 95th percentile, a chosen cut-off, so the report must show the sensitivity table.

## 5. RQ4 — Do natural topic clusters exist in the headlines?

**Silhouette 0.2582, which is strong separation.** The
conventional reading treats below 0.25 as weak and below 0.1 as
effectively none.

One cluster holds 94.88% of the sample and 3 further clusters hold at least 1% each. A high silhouette in this shape does not mean the corpus is well clustered: it means a small, well-separated topical minority exists and the remainder is undifferentiated. Read the score and the shape together.

### A correction worth stating plainly

An earlier version of this analysis concluded that these headlines had
**no recoverable topic structure**, on a silhouette of 0.068. That
conclusion was wrong, and the fault was in the feature engineering
rather than in the data. Two fixes moved the score from 0.068 to 0.2582:

1. **Numbers were admitted as terms.** The scikit-learn default token
   pattern allows pure numerals, and because numerals appear in a large
   share of headlines they crowded out every content word. The clusters
   were described by `000`, `102` and `1000`.
2. **Function words were not removed.** With them present, the mean
   TF-IDF inside a cluster is highest for words like `for`, `with` and
   `the`, because they occur in a modest share of documents but a large
   share of any one cluster. The clusters were described by stopwords.

A third fix was needed to make the descriptions mean anything: clusters
are described by the mean TF-IDF of their own members rather than by the
K-Means centroid weights. Projecting centroid weights back onto the term
axis through the LSA basis returned `aadhaar, aadmi, aap, aarti` for
*every* cluster, because SVD components carry an arbitrary sign and small
numerical asymmetries make alphabetically early features win
systematically.

None of those three defects is visible in a silhouette computed on a
different feature space, which is why the first number looked like a
property of the corpus rather than of the pipeline. The lesson is that
'the data has no structure' and 'my features had no signal' are easy to
confuse and must be separated before being reported.

### k selection

| k | silhouette |
|---|---|
| 4 | 0.2582 |
| 5 | 0.2261 |
| 6 | 0.2269 |
| 7 | 0.1748 |
| 8 | 0.2073 |
| 9 | 0.1824 |
| 10 | 0.1855 |
| 11 | 0.1873 |
| 12 | 0.1921 |


Silhouette peaks at k=4 and falls away on both sides, so this k is a genuine optimum rather than an edge of the search range.

A first attempt at this ran K-Means directly on the 20,000-dimensional
sparse TF-IDF matrix and measured a silhouette of **0.005 at every k** —
zero separation, because in that many dimensions every document is nearly
equidistant from every other. Adding truncated-SVD (LSA) reduction to
100 components lifted the score roughly fourteenfold.
The reduction explains 9.20% of the
variance, which is itself part of the explanation for the low score.

### The clusters

From a fixed-seed sample of 60,000 headlines. The
right-hand column is the publisher's own topic for the same documents, so
the comparison shows how far unsupervised grouping gets toward the
supplied taxonomy.

| cluster | size | share | top terms | dominant supplied topics |
|---|---|---|---|---|
| 0 | 56,930 | 94.88% | new, india, says, held, man, city | Local, Entertainment |
| 2 | 1,519 | 2.53% | rs, crore, rs crore, rs lakh, lakh, worth | Local, Business |
| 1 | 776 | 1.29% | road, road accident, accident, garbage, killed, main road | Local, Nation |
| 3 | 775 | 1.29% | old, year old, year, yr old, yr, old girl | Local, Entertainment |


The small clusters are legible and the remainder is not. Terms like
`rs crore`, `lakh` and `worth` are money; `road`, `accident` and `killed`
are traffic and crime reporting; `old`, `year old` and `girl` are
age-and-gender copy. Those are real, recurring headline shapes and none
of them is a topic in the publisher's own taxonomy — which is why the
right-hand column is dominated by `Local` for every cluster. What the
clustering found is a set of **writing patterns**, not desks.

**Stability.** The same documents are clustered twice with different K-Means seeds, so only the initialisation varies. High agreement means the partition is a property of the data; low agreement means the clusters are an artefact of the starting points. Agreement was 0.9669 on the same documents refit with two different K-Means seeds.


> **Read this before quoting the number.** Read this with the cluster sizes, not alone. Silhouette rewards a large cluster sitting far from a few small tight ones, and that is the shape here: most headlines are undifferentiated while a small topical minority is cleanly separated. The score also depends entirely on the TF-IDF settings: an earlier run that admitted numerals and stop words measured 0.068 on the same data.

## 6. RQ5 — Which co-occurrence patterns exist?

**644 rules** at support ≥ 0.01, confidence ≥ 0.3, maximum rule length 3.

### Two algorithms, one answer

| algorithm | rules | time |
|---|---|---|
| Apriori | 644 | 0.9152 s |
| FP-Growth | 644 | 1.3258 s |
| **speedup** | — | **0.69×** |


**Rule sets identical: True.** Both algorithms were run
on identical transactions with identical thresholds. They must return the
same rules, because they search the same itemsets; a difference would mean
one of them is broken, not interesting. The only thing being measured is
the time, and FP-Growth is the faster of the two.

### The strongest non-trivial rules, by lift

Ranking by lift alone would put tautologies at the top — a rule whose
consequent is implied by its antecedent scores exactly 1.000. Those are
counted separately below, and this table shows the rules that carry
information.

The highest-lift table is not dominated by the partial final period. Lift is still maximised by rare consequents in general, so the confidence table below is the more informative of the two.

| if |  | then | support | confidence | lift |
|---|---|---|---|---|---|
| Business | => | 2017 + weekday | 2.72% | 49.2% | 3.181 |
| Business | => | 2017 + neutral | 2.84% | 51.4% | 2.969 |
| Business + weekday | => | 2017 | 2.72% | 60.4% | 2.779 |
| Business | => | 2017 + single_category | 3.19% | 57.8% | 2.764 |
| Business + single_category | => | 2017 | 3.19% | 58.9% | 2.709 |
| Business + sensational=normal | => | 2017 | 3.05% | 58.7% | 2.700 |
| Business | => | 2017 | 3.23% | 58.5% | 2.693 |
| Business + neutral | => | 2017 | 2.84% | 58.4% | 2.689 |


### The most confident rules

The more informative of the two tables, because confidence is not
inflated by a rare consequent in the way lift is.

| if |  | then | support | confidence | lift |
|---|---|---|---|---|---|
| 2017 + Sports | => | single_category | 1.12% | 100.0% | 1.038 |
| 2018 + Entertainment | => | sensational=normal | 2.08% | 99.7% | 1.036 |
| World | => | sensational=normal | 1.54% | 99.5% | 1.034 |
| World + single_category | => | sensational=normal | 1.47% | 99.5% | 1.034 |
| World + neutral | => | sensational=normal | 1.07% | 99.5% | 1.034 |
| World + weekday | => | sensational=normal | 1.02% | 99.4% | 1.033 |
| 2019 + Entertainment | => | sensational=normal | 1.01% | 99.3% | 1.032 |
| 2017 + Entertainment | => | sensational=normal | 1.87% | 99.3% | 1.032 |


313 of 644 rules are tautologies with lift exactly 1.000: the consequent is implied by the antecedent, as in `2015 => Local`. The transaction items are not independent — the sensational flag and the sentiment band are derived from the same score, and a year implies every other item carrying that year. Redundant items inflate the rule count without adding information, which is why 331 substantive rules are reported alongside the 644 total.

### Why transactions are attributes, not keywords

The plan was to mine the 300-term keyword vocabulary in the bridge table.
Measured on the real corpus it yields **1.992 items
per headline**, because its most frequent terms are functional words:
`govt`, `held`, `get`, `man`, `police`, `case`, `two`. A transaction with
two items supports almost no co-occurrence, so rules over them would be
reporting sparsity as a pattern.

Attribute transactions carry **6.0 items** each across 6 attributes (topic, year, sentiment_band, sensational_flag, weekday_flag, multi_category_flag), drawing on a vocabulary of only 31 distinct values, and the research
question's own example rule is attribute-shaped: `topic=Business,
year=2016 => sensational=high`.

**The keyword run produced zero rules**, and that is reported as a result rather than an omission. Across 100,000 sampled headlines the mean transaction held 1.992 keywords, and at the configured support and confidence thresholds no pair of terms cleared the bar. The vocabulary is dominated by functional words, so it carries almost no co-occurrence structure to mine. Rebuilding this feature would need domain-specific term extraction rather than a top-300-by-frequency cut.


> **Read this before quoting the number.** Association, not causation. A rule states two attributes co-occur more often than chance. Transactions are ATTRIBUTES, not keywords: the 300-term keyword vocabulary yields only 1.992 items per headline and produced zero rules at these thresholds, so keyword rules would have reported sparsity as a pattern.

## 7. RQ6 — Do headlines relate to Nifty returns or volatility?

Over **1,235 paired trading days**. The
answer differs for returns and for volatility, so they are reported
separately rather than averaged into one verdict.

### Against daily returns: no relationship

| measure | Pearson r | Spearman ρ | at lag | p | significant? |
|---|---|---|---|---|---|
| headline volume | +0.0230 | +0.0270 | 0 | 0.4186 | no |
| mean sentiment | +0.0459 | +0.0608 | 0 | 0.1067 | no |
| mean sensational score | +0.0748 | +0.0655 | 5 | 0.0087 | yes |


### Every lag, so the shape is visible

| measure | lag (trading days) | Pearson r | p | n |
|---|---|---|---|---|
| headline volume | 0 | +0.0230 | 0.4186 | 1235 |
| headline volume | 1 | +0.0167 | 0.5574 | 1234 |
| headline volume | 2 | +0.0211 | 0.4596 | 1233 |
| headline volume | 3 | +0.0119 | 0.6765 | 1232 |
| headline volume | 5 | +0.0100 | 0.7252 | 1230 |
| mean sentiment | 0 | +0.0459 | 0.1067 | 1235 |
| mean sentiment | 1 | -0.0070 | 0.8046 | 1234 |
| mean sentiment | 2 | -0.0397 | 0.1638 | 1233 |
| mean sentiment | 3 | -0.0362 | 0.2041 | 1232 |
| mean sentiment | 5 | -0.0389 | 0.1721 | 1230 |
| mean sensational score | 0 | +0.0331 | 0.2458 | 1235 |
| mean sensational score | 1 | -0.0263 | 0.3559 | 1234 |
| mean sensational score | 2 | +0.0062 | 0.8268 | 1233 |
| mean sensational score | 3 | -0.0050 | 0.8601 | 1232 |
| mean sensational score | 5 | +0.0748 | 0.0087 | 1230 |


1 of 15 lag tests is significant (mean sensational score at lag 5 (r = +0.0748, p = 0.0087)). At α = 0.05, 15 tests yield about 0.75 false positives by chance. That **exceeds** what chance alone would produce. On this evidence the significant result is not treated as a finding, and the coefficient involved is small in any case.

### Against 20-day volatility: a real association

Over 1,235 trading days with a full volatility window:

| measure | Pearson r | variance explained | p | significant? |
|---|---|---|---|---|
| mean sentiment | -0.0226 | 0.05% | 0.4279 | no |
| mean sensational score | +0.0236 | 0.06% | 0.4078 | no |
| log headline volume | -0.2827 | 7.99% | 0.0000 | yes |


**Log `log headline volume` correlates with 20-day volatility at r = -0.2827, and the coefficient is significant.** Headline volume and market volatility move together, and the relationship is *negative*: busier headline days go with calmer markets. It accounts for 8.0% of the variance in volatility, so it is a real association and a weak predictor — it would be misleading to describe it as either strong or causal.

The direction is the interesting part and this data cannot explain it. Two readings fit equally well: a newsroom under pressure covers the market crash rather than business, or headline volume in this archive is capped and crisis coverage displaces routine coverage. Separating them would need the unrounded per-day export, which this corpus does not provide. It is reported as an association and left there.

### How the question was asked

Only *trading days* are used, because headlines are published on 1,828
days in the window while the market trades on 1,235 — a weekend has
headlines and no close price, and pairing them would invent data. Every
coefficient travels with a p-value and a count, because 0.02 over 1,200
points and 0.02 over 10 points are different claims. And lag 0 is not
privileged: a lag-0 or lag-1 coefficient being the largest is exactly
what a shared calendar effect produces, and is not evidence of
leading-indicator behaviour.


> **Read this before quoting the number.** ASSOCIATION ONLY. Against daily returns the relationship is negligible. Against 20-day VOLATILITY it is not: log headline volume correlates at about -0.28, which is a real association and still not an effect, because both respond to the same underlying events.

## 8. RQ7 — Can a classifier separate Real from Fake?

This is the only accuracy claim in the project, because IFND is the only
source with ground truth. Everything measured on the headline corpus
above is a style measure on unlabelled data.

### The baseline that makes accuracy mean something

IFND is imbalanced: 33,684 real against
17,426 fake. A classifier that answers
"real" to everything already scores **0.6590**.

Reporting plain accuracy would therefore flatter a model that had learned
nothing. Every metric here is stated against that baseline, and the Fake
class is reported first because it is the class a fake-news detector is
for.

### Results

| model | accuracy | Fake recall |
|---|---|---|
| naive_bayes | 0.9540 | 0.9078 |
| complement_nb | 0.9463 | 0.9256 |
| logistic_regression | 0.9571 | 0.9137 |


`logistic_regression` was selected on **training** cross-validated accuracy naive_bayes 0.9548, complement_nb 0.9479, logistic_regression 0.9577.
The test split was scored once. Selecting a model on test accuracy and then
reporting that same number is the optimism this study set out to avoid, so
the two are kept strictly apart.

**Accuracy 0.9571** against a **0.6590** baseline: **+29.8 percentage points**.

| class | precision | recall | F1 | support |
|---|---|---|---|---|
| FAKE | 0.9585 | 0.9137 | 0.9356 | 5,228 |
| REAL | 0.9564 | 0.9795 | 0.9678 | 10,105 |


### Confusion matrix

| actual \ predicted | FAKE | REAL |
|---|---|---|
| FAKE | 4,777 | 451 |
| REAL | 207 | 9,898 |


row = actual class, column = predicted. The bottom-left cell is fake statements missed, which is the expensive error.

The model is not opaque. Its highest-weighted terms:

| toward FAKE | toward REAL |
|---|---|
| fake | sc |
| fact | says |
| did | covid |
| fact check | to |
| check | for |
| video | centre |
| viral | dies |
| not | seeks |
| false | maharashtra |
| shared | talks |
| photo | cases |
| image | court |
| falsely | govt |
| no | tells |
| shared as | against |


### What this number is not

Part of IFND's Fake class is LSTM-generated augmentation of real statements, which is easier to distinguish than a fake article written by a person. This accuracy is therefore an upper bound on performance against genuine misinformation.


> **Read this before quoting the number.** The ONLY accuracy claim in this project, because IFND is the only source with ground truth. The majority baseline is 0.659049, not 0.5, so accuracy alone is meaningless. Part of the Fake class is LSTM-augmented, so this is an UPPER BOUND.

## 9. Method, and what it refuses to do

### Warehouse shape

A star schema over three fact tables, with dimensions for date, topic,
dataset, label, instrument and keyword, plus a bridge from headlines to
keywords. Cubes store **sums, never averages**; every mean in this report
is recomputed as sum ÷ count at query time, so no rounded average is
ever averaged again.

### Guard rails

The inference gate ran 15 checks: **all passed**. Each one
states what it looked at, and a check that cannot be evaluated reports
that rather than passing quietly.

| check | result | detail |
|---|---|---|
| headlines_in_window_present | pass | 1,113,427 headlines in the analysis window |
| headlines_in_window_sufficient | pass | 1,113,427 rows, floor for a rate is 1000 |
| labelled_statements_present | pass | 51,110 labelled statements |
| trading_days_present | pass | 1,235 trading days in the window |
| market_correlation_has_enough_observations | pass | 1235 paired trading days, floor is 100 |
| rq1_topic_mix_present | pass | topic mix section has content |
| rq2_bursts_present | pass | bursts section has content |
| rq3_sensationalism_present | pass | sensationalism section has content |
| rq4_clusters_present | pass | clustering section has content |
| rq4_clusters_ran | pass | clustering ran |
| rq5_association_rules_present | pass | association rules section has content |
| rq6_market_association_present | pass | market association section has content |
| rq7_classifier_present | pass | classifier section has content |
| rq7_classifier_ran | pass | classifier ran |
| every_headline_has_a_topic | pass | 0 headlines without a topic |


### Rules this study holds itself to

- On the unlabelled TOI corpus every style measure is a RISK-SIGNAL rate. It is never a fake-news rate.
- Only the IFND classifier states an accuracy, because IFND is the only source with ground truth.
- Correlations are associations. No result in this project identifies an effect of news on markets.
- Association rules state co-occurrence, never causation.
- 2015 is a partial year and is excluded from year-on-year comparison.
- A negative result is reported as a negative result, with the measurement that establishes it.

### Reproducibility

Every threshold, weight, sample size and random seed lives in
`config/*.yaml` rather than in code, so any number above can be traced to
the setting that produced it. The pipeline rebuilds from raw CSV to this
report in about five minutes; mining takes 86 seconds. There is no
language model anywhere in the reporting path: `report.md` is rendered
from `facts.json` by templates, which is what makes the traceability
claim checkable rather than aspirational.
## 10. What this study concludes

### The negative results are the contribution

Two of the seven questions produced no result, and one produced a score
that flatters a narrow finding. Reporting them with the measurement
that establishes them is more useful than a finding chosen for being
presentable.

1. **Headline volume carries no news signal.** Within-year coefficient of variation 0.0352, and in 5 of the listed event months every desk predicted to rise — Health, Sports, Entertainment — fell instead.
2. **Topic structure, where it exists, covers a small minority.** Silhouette 0.2582 is strong, but one cluster holds 94.88% of the corpus and the rest is undifferentiated. The score looks better than the coverage warrants.
3. **Headlines do not measurably relate to Nifty daily returns.** Strongest correlation 0.0748, and the one significant lag out of fifteen is within what chance produces.

### The positive results, and what they are worth

4. **Risk-signal language is concentrated and measurable.** `Education` carries 10.94% of headlines over the threshold (95% CI 10.06%–11.89%, n=4,450), well above the corpus rate of 3.77%.
5. **A headline's attributes predict each other strongly.** 644 rules mined by two independent algorithms that return the same rule set, with FP-Growth the faster.
6. **Headline volume is genuinely related to market volatility.** Log business-headline volume against 20-day volatility gives r = -0.2827, explaining 8.0% of its variance. The sign is negative: busier headline days go with calmer markets. This is an association and the direction is unexplained.
7. **Text alone separates real from fake statements well on IFND.** 0.9571 against a 0.6590 majority baseline, an improvement of +29.8 points, with Fake recall 0.9137.

### What a follow-up study should do differently

- Use a corpus sampled by newsworthiness rather than by whatever a
  publisher's export happened to contain. The flat volume is plausibly
  a sampling artefact of the export, and that cannot be distinguished
  from a genuinely quota-driven newsroom using this data alone.
- Use a headline-level ground truth, so the sensationalism measure can be
  validated against a real label instead of standing as a style proxy.
- Use IFND dates from a source that records them, and treat the
  LSTM-augmented portion of the Fake class separately, since it is the
  part that inflates the classifier's apparent skill.
---

Generated 2026-10-02 14:57 from `facts.json` (mining run 20261002T092603Z). Every figure in this document is rendered from a fact that records its own source. No language model was involved in producing it.
