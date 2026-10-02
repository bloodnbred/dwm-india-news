# 04 — Mining (Phases 5-6)

The seven research questions, answered from the warehouse. Every number here
was measured on the real data on 2026-10-02 and is reproducible with
`python -m dwm mine`, which also writes `reports/mining.json` so the report can
quote a file rather than recompute.

**The two most important results are negative, and that is the finding.** RQ2
found no event-correlated signal in volume at all, and RQ4 found that these
headlines have almost no cluster structure. Both are reported with the
measurement that establishes them, rather than presented as findings of
convenience.

| Q | Module | Headline result |
|---|---|---|
| 1 topic mix | `trends` | `Local` is 70% of the window; one 2017 filing artefact |
| 2 bursts | `trends` | **no volume signal exists**; CV ≤ 0.035 |
| 3 sensationalism | `sensationalism` | Education 10.9%, CI 10.1–11.9%, n=4,450 |
| 4 clusters | `clustering` | **silhouette 0.069, no preferred k** |
| 5 rules | `rules` | 1,797 rules, both algorithms agree, FP-Growth 1.3× faster |
| 6 market | `market` | **no meaningful association**, \|r\| ≤ 0.075 |
| 7 classifier | `classifier` | 95.7% vs 65.9% baseline, fake recall 91.4% |

## RQ1: the topic mix, and a filing artefact

Shares are computed **within each year**, never as raw counts, because 2015 is a
partial year: the window starts 2015-06-30, so it holds about half a year of
headlines. A partial year is flagged `is_partial_year` and excluded from any
year-on-year comparison rather than dropped silently.

The most useful finding is a warning, not a trend.
`business.international-business` is **11.1% of all 2017 headlines (26,856
rows)** and **0.2% of 2018 (485 rows)**. A naive topic-mix analysis reports
"business coverage quintupled in 2017", which is an artefact of how the
publisher filed content, not of what India was reading. `raw_category_dominance`
flags any raw category holding 8% or more of a single year so the report has to
name the artefact.

`Local` is 70% of the window and is a *where*, not a *what*, which is why
`dim_topic.topic_group` splits `Place` from `Subject`. Every subject-mix
statement is made within one group.

## RQ2: there is no volume signal, and that is the result

**Monthly headline volume is almost perfectly flat.** Within-year coefficient
of variation is **0.02 to 0.04** for every complete year, and the busiest month
of a year runs only 1.02 to 1.05 times the monthly mean. March 2020 — the month
India entered a national lockdown — is 2.5% above its own year mean.

A z-score threshold of 2.0 therefore detects nothing, and lowering it until
something appeared would be choosing a threshold to manufacture a finding. So
the module tests four measures and reports the flatness as evidence.

What happens in the event months is the interesting part, and part of it runs
**opposite** to expectation:

| month | event | Health z | Sports z | Entertainment z | negative-sentiment z |
|---|---|---:|---:|---:|---:|
| 2016-11 | Demonetisation announced | +0.37 | +1.81 | +0.43 | −0.15 |
| 2016-12 | Demonetisation deadline | +0.60 | +1.41 | +0.86 | −0.46 |
| 2017-07 | GST launched | −0.26 | +0.01 | +0.92 | −0.41 |
| 2019-02 | Union Budget | −0.83 | −1.36 | −1.53 | +0.98 |
| 2019-05 | Election result | −0.56 | −1.08 | −0.73 | +1.28 |
| 2020-03 | COVID lockdown announced | −0.74 | −1.33 | −1.57 | +0.09 |
| 2020-04 | COVID lockdown extended | −0.92 | −1.41 | −1.80 | **−2.63** |

Health and Sports coverage **fall** during the pandemic, and April 2020 has the
*lowest* negative sentiment in the whole series. An archive that tracked news
intensity would show the opposite. This suggests the corpus behaves like a
fixed editorial capacity rather than a reactive news feed, and the report
should say so.

A partial year once contaminated this result: 2015 has seven months, and a
seven-month series has a wider spread for reasons unrelated to news. Including
it reported a CV of 0.39 for a series that is flat to within 0.035. Years below
`full_year_months` are now excluded from the flatness claim and named in
`partial_years_excluded`.

## RQ3: sensationalism by category

Corpus risk-signal rate **3.77%**. Among topics that carry an editorial
subject, the highest is:

| topic | rate | 95% CI | n |
|---|---:|---|---:|
| **Education** | **10.94%** | 10.06 – 11.90 | 4,450 |
| Business | 6.9% | | 61,619 |
| Politics | 6.6% | | 4,833 |

**`Unknown` tops the raw ranking at 17.3%, and it is excluded.** It is a filing
gap, not a subject: a reader told "Unknown is the most sensational topic" has
been told nothing. It is reported separately in `uninformative_topics`.

Every rate carries a **Wilson interval**, which is used instead of the normal
approximation because the highest-scoring topics sit near the extremes, where
the normal interval runs outside [0, 1]. A topic is called
`distinguishable_from_corpus` only when its interval excludes the corpus rate,
so the ranking is not just ordering noise.

The threshold is 0.2208, the measured 95th percentile. Because that is a
judgement, `threshold_sensitivity` re-ranks at seven thresholds and reports
whether the top topic changes, so the report can state the ranking's stability
instead of presenting one table as fact.

This is a **style** measure on unlabelled headlines. It is a risk-signal rate
and is never a fake-news rate. A test greps the payload to enforce that.

## RQ4: these headlines have almost no cluster structure

**Silhouette 0.069 at the chosen k.** The usual reading of silhouette treats
below 0.25 as weak, and below 0.1 as effectively no structure. This corpus is
in the second band.

Two measurements explain it, and both are reported:

**K-Means on raw TF-IDF does not work at all.** On the 20,000-feature matrix
the silhouette was **0.005 at every k from 4 to 12** — zero separation, because
in that many dimensions every document is nearly equidistant from every other.
Adding truncated-SVD (LSA) reduction to 100 components lifted it to 0.069, a
14× improvement, and is the standard remedy for short text. The reduction and
its 9.4% explained variance are both in the output.

**There is no preferred k.** Silhouette rises to k=12, the largest value tried,
without turning over. That indicates no natural cluster count, not that k=12 is
correct: any partition looks slightly better when cut more finely. The output
sets `no_preferred_k` and explains it, rather than reporting "the best k is 12".

A 60,000-headline sample is used with a fixed seed, and `sample_stability`
refits the **same** documents with two different K-Means seeds to separate
initialisation sensitivity from sampling noise. Low agreement would mean the
clusters are an artefact of the starting points.

## RQ5: 1,797 rules, and both algorithms agree

**The primary transactions are attributes, not keywords**, and the data forced
that choice. The 300-term keyword vocabulary yields a mean of **1.02 items per
headline**, because its highest-frequency terms are functional words: `govt`,
`held`, `get`, `man`, `police`, `case`, `two`. A transaction with one item
supports no co-occurrence, so rules over keyword transactions would be
reporting sparsity as a pattern.

The blueprint's own example is attribute-shaped —
`topic=Business, year=2016 => sensational=high` — and attribute transactions
carry **7.00 items** each across 7 attributes: topic, year, quarter, sentiment
band, sensational flag, weekend flag, multi-category flag.

| | Apriori | FP-Growth |
|---|---:|---:|
| rules found | 1,797 | 1,797 |
| time | 0.76 s | 0.58 s |
| speedup | — | **1.32×** |

**`rule_sets_identical: true`.** Both algorithms find the same itemsets, so the
rule sets must be identical; a difference would mean one is wrong, not
interesting. The comparison is run on identical input for exactly that reason,
and the timing difference is the only thing being measured.

The keyword run is still performed and reported **with its sparsity caveat**,
because a negative result about the vocabulary is itself worth knowing.

Rules are association, never causation. A test greps the output for causal
wording.

## RQ6: no meaningful association with the market

Over **1,235 paired trading days** (headlines exist on 1,828 days; the market
trades on 1,235, and a weekend has headlines but no close price):

| measure | strongest \|r\| | lag | p |
|---|---:|---:|---:|
| headline volume | 0.023 | 0 | not significant |
| mean sentiment | 0.046 | 0 | not significant |
| mean sensational score | 0.075 | 5 | not significant |

**There is no relationship to report.** These are the correlations one would
expect from noise at this sample size, and the report should say the question
was asked and answered negatively rather than quoting 0.075 as a weak effect.

Correlations are computed on trading days only, each with a p-value and a
count, and lags are reported without privileging zero. A coefficient near zero
with a p-value is the honest form of that result. Volatility is reported
separately, on fewer days because `volatility_20d` is null until its window is
full.

## RQ7: the only result permitted to state an accuracy

**IFND's majority class is 65.9%**, not 50%: 33,684 real against 17,426 fake.
A model that always answers "real" already scores 0.659, so accuracy alone
flatters a model that learned nothing.

| model | accuracy | fake recall | fake precision |
|---|---:|---:|---:|
| Multinomial Naive Bayes | 0.9540 | 0.9078 | |
| Complement NB | 0.9463 | 0.9256 | |
| **Logistic regression** | **0.9571** | 0.9137 | |

Logistic regression is chosen on **training** cross-validated accuracy
(0.9577), and the test split is scored once. Selecting on test accuracy and
then reporting that same number is the optimism the blueprint warns about, so
the two are kept apart and a test asserts the choice follows the train score.

Results are reported as `lift_over_baseline_pp` = **+29.8 points**, with the
confusion matrix and the Fake class first, because Fake is the class a
fake-news detector is for.

**This is an upper bound.** Part of IFND's Fake class is LSTM-generated
augmentation of real statements, which is easier to distinguish than a fake
article written by a person. 95.7% is not 95.7% against genuine
misinformation, and the report must say so.

The classifier does not use dates, so the unusable IFND date column does not
affect it.

## Guard rails

Every module records its checks into one `guard_summary`, and a failed guard is
not necessarily an error: clustering refusing to run on too little data is the
guard working. What matters is that a reader can see which results are
conditional.

Refusals, with the reason returned rather than a division by zero:

- fewer than 3 points for a correlation or z-score
- fewer than 100 paired trading days for RQ6
- a class with fewer than 2 members for the classifier
- cross-validation folds capped by the smallest class, so a `--sample` run does
  not crash where a full run would not
- topics below `min_topic_rows` excluded from the RQ3 ranking and listed
  separately
- a rate never reported without its denominator

## Cost

86 seconds on the full corpus, dominated by RQ4 (73 s, nine K-Means fits at
k=4..12 on 60,000 documents). Rules take 4 s, the classifier 4 s, everything
else under a second. All seeds are fixed, so a re-run reproduces every number.
