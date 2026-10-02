# 04 — Mining (Phases 5-6)

The seven research questions, answered from the warehouse. Every number here
was measured on the real corpus on 2026-10-02 and is reproducible with
`python -m dwm mine`, which writes `reports/mining.json` for the report to
quote rather than recompute.

| Q | Module | Headline result |
|---|---|---|
| 1 topic mix | `trends` | `Local` 70% of the window; one 2017 filing artefact |
| 2 bursts | `trends` | **no volume signal**; CV ≤ 0.035 |
| 3 sensationalism | `sensationalism` | Education 10.94%, CI 10.06–11.89%, n=4,450 |
| 4 clusters | `clustering` | silhouette **0.2582**, but 95% in one cluster |
| 5 rules | `rules` | 644 rules, both algorithms agree, FP-Growth 1.4× faster |
| 6 market | `market` | no link to returns; **r = −0.28 to volatility** |
| 7 classifier | `classifier` | 95.7% vs 65.9% baseline, fake recall 91.4% |

Three of the seven produced no result, or a result that reads better than it
is. Those are reported with the measurement that establishes them, which is the
main reason to read this document rather than skim the summary table.

## RQ1: the topic mix, and a filing artefact

`Local` is **69.95%** of the 1,113,427 in-window headlines. That figure and the
largest within-year share are both reported, because they are different numbers
answering different questions: `Local` peaks at **88.98% of 2020**, which is
true and would badly misrepresent the corpus if quoted as "of the window". An
earlier draft of the report did exactly that, so `window_shares` and the
within-year `rows` are now stored as separate blocks and cannot be confused.

`Local` is a *where*, not a *what*, which is why `dim_topic.topic_group` splits
Place from Subject and every subject comparison is made within a group.

### The artefact

`business.international-business` is **11.1% of all 2017 headlines (26,856
rows)** and **0.2% of 2018 (485 rows)**. A naive topic-mix analysis reports
"business coverage quintupled in 2017", which is how the publisher filed
content, not what India was reading. `raw_category_dominance` flags any raw
category holding 8% or more of a single year so the report has to name it.

2015 is a **partial year** (the window starts 2015-06-30), so all trend
statements are within-year shares and raw counts across years are never
compared.

## RQ2: no volume signal, and that is the result

**Monthly headline volume is almost perfectly flat.** Within-year coefficient of
variation is 0.0202 (2016) to 0.0352 (2018), and the busiest month of a year
runs only 2–5% above its own monthly mean. March 2020 — the month India entered
a national lockdown — is 2.5% above its year mean.

A z-score threshold of 2.0 therefore detects nothing, and lowering it until
something appeared would be choosing a threshold to manufacture a result. So
four measures are tested instead and the flatness is reported as the evidence.

### The counter-signal, stated as a falsifiable prediction

`config/mining.yaml` fixes three desks — **Health, Sports, Entertainment** — that
a news-reactive archive would be expected to increase coverage of during the
listed events. In **5 of the 10 event months, all three fall below their norms
instead**, including all three COVID months:

| month | event | Health z | Sports z | Entertainment z | negative-sentiment z |
|---|---|---:|---:|---:|---:|
| 2016-11 | Demonetisation announced | +0.37 | +1.81 | +0.43 | −0.15 |
| 2016-12 | Demonetisation deadline | +0.60 | +1.41 | +0.86 | −0.46 |
| 2017-07 | GST launched | −0.26 | +0.01 | +0.92 | −0.41 |
| 2017-08 | Independence Day | −0.60 | +0.34 | +0.21 | −1.27 |
| 2018-01 | Union Budget session | −0.52 | +1.07 | −0.06 | +0.29 |
| 2019-02 | Union Budget | −0.83 | −1.36 | −1.53 | +0.98 |
| 2019-05 | Election result | −0.56 | −1.08 | −0.73 | +1.28 |
| 2020-03 | Lockdown announced | −0.74 | −1.33 | −1.57 | +0.09 |
| 2020-04 | Lockdown extended | −0.93 | −1.41 | −1.80 | **−2.63** |
| 2020-05 | Lockdown eased | −0.98 | −1.44 | −1.73 | −1.71 |

A prediction fixed in advance and then failed is worth more than the absence of
a signal, which is why the desk list lives in config rather than being chosen
after looking.

The count of measures below −0.5 SD is reported but explicitly **not** offered
as a significance test: the measures share months and are correlated, so their
z-scores are not independent.

## RQ3: risk-signal rate by topic

Corpus rate **3.77%** at threshold 0.2208 (the measured 95th percentile).

| topic | rate | 95% CI | n | above corpus? |
|---|---:|---|---:|---|
| **Education** | **10.94%** | 10.06 – 11.89 | 4,450 | yes |
| Business | 5.81% | 5.63 – 6.00 | 61,619 | yes |
| Politics | 4.24% | 3.71 – 4.85 | 4,833 | no |
| Local | 3.96% | 3.92 – 4.01 | 778,859 | yes |
| Sports | 3.90% | 3.73 – 4.08 | 45,299 | no |
| Nation | 3.51% | 3.37 – 3.67 | 56,770 | no |

**`Unknown` (17.29%) and `Other` (2.66%) are excluded from the ranking.** They
carry no editorial subject, so their score measures the absence of a filing
decision rather than the language used. A reader told "Unknown is the most
sensational topic" has been told nothing.

Every rate carries a **Wilson interval**, used instead of the normal
approximation because the highest-scoring topics sit near the extremes, where
the normal interval runs outside [0, 1]. A topic is `above_corpus_average` only
when its interval excludes the corpus rate, so the ranking is not just ordering
noise.

The threshold is a judgement, so `threshold_sensitivity` re-ranks at eight
thresholds. `Education` is the top informative topic at 0.05 and 0.10 and
second at 0.15–0.30; `Health` only becomes top at 0.40. Stability is judged
**excluding** the uninformative topics, because counting `Unknown` as an
unstable "top topic" would report a non-finding as a caveat about the ranking.

This is a **style** measure on unlabelled headlines: a risk-signal rate, never a
fake-news rate. A test greps the payload to enforce that.

## RQ4: strong silhouette, narrow coverage

**Silhouette 0.2582 at k=4**, which clears the conventional 0.25 threshold for
strong separation. This corrects an earlier finding, and the correction matters
more than the number.

### The earlier finding was wrong

A previous run measured **0.068** and concluded the headlines had no recoverable
topic structure. The fault was in the feature engineering, not the data. Three
defects, each visible in the output:

1. **Numerals were admitted as terms.** scikit-learn's default token pattern
   allows pure numbers, and because numerals appear in a large share of
   headlines they crowded out every content word. The clusters were described
   by `000`, `102` and `1000`.
2. **Function words were not removed.** With them present the mean TF-IDF inside
   a cluster is highest for `for`, `with`, `from`, because they occur in a
   modest share of documents but a large share of any one cluster. The clusters
   were described by stopwords.
3. **Clusters were described by centroid weights.** Projecting K-Means
   centroid weights back onto the term axis through the LSA basis returned
   `aadhaar, aadmi, aap, aarti` for *every* cluster, because SVD components
   carry an arbitrary sign and small numerical asymmetries make
   alphabetically-early features win systematically. Clusters are now described
   by the mean TF-IDF of their own members.

None of these is visible in a silhouette computed on a different feature space,
which is why the first number looked like a property of the corpus. "The data
has no structure" and "my features had no signal" are easy to confuse.

K-Means on the raw 20,000-feature matrix measured **0.005 at every k**; LSA
reduction to 100 components (9.2% of variance) is what makes the score
informative at all.

### What the score does not say

| cluster | size | share | top terms |
|---|---:|---:|---|
| 0 | 56,930 | 94.88% | new, india, says, held, man, city |
| 2 | 1,519 | 2.53% | rs, crore, rs crore, rs lakh, lakh, worth |
| 1 | 776 | 1.29% | road, road accident, accident, garbage, killed, main road |
| 3 | 775 | 1.29% | old, year old, year, yr old, yr, old girl |

**One cluster holds 94.88% of the corpus.** Silhouette scores a document by its
distance to its own cluster against the nearest other, so a large blob sitting
far from a few small tight ones scores very well. `structure_is_concentrated`
is reported for exactly this reason.

What the three small clusters find is legible — money (`rs crore`, `lakh`),
traffic and crime (`road`, `accident`, `killed`), age-and-gender copy (`old`,
`year old`) — and none of it is a topic in the publisher's own taxonomy, which
is why the dominant supplied topic is `Local` for every cluster. The clustering
found **writing patterns, not desks**. Seed stability is 0.9669, refitting the
same documents with two K-Means seeds.

## RQ5: 644 rules, and 313 of them are arithmetic

**Transactions are attributes, not keywords.** The 300-term keyword vocabulary
yields **1.99 items per headline**, because its most frequent terms are
functional words (`govt`, `held`, `get`, `man`, `police`, `case`, `two`). The
keyword run was still performed and **produced zero rules** at the configured
thresholds — reported as a result, since it is a finding about the feature.

Attribute transactions carry **6.00 items** each over a vocabulary of 52
distinct values.

| | Apriori | FP-Growth |
|---|---:|---:|
| rules | 644 | 644 |
| time | 0.85 s | 1.37 s |

`rule_sets_identical: true` — both algorithms run on identical transactions with
identical thresholds, so a difference would mean one is broken, not
interesting.

### Three corrections that changed the answer

**mlxtend's rule columns were read by position and were off by two.** The frame
is ordered `antecedents, consequents, antecedent support, consequent support,
support, confidence, lift`, so `r[2]..r[6]` labelled the *consequent support* as
"confidence" and the *confidence* as "lift". Every one of 1,797 rules appeared
to have lift exactly 1.000, which reads as "the attributes are all tautologies"
and is pure mislabelling. Columns are now read by name.

**`use_colnames` defaults to False** in mlxtend 0.23+, so rules came back as
`5 => 4` instead of named attributes. The report was unreadable and the rules
could not be checked against the data.

**`quarter` was removed from the default item set.** Year and quarter are
redundant in both directions — a quarter implies its year, and everything
carrying a year implies the year — so including both produced 1,797 rules that
were overwhelmingly `2020-Q1 => 2016` permutations, and pushed every high-lift
rule toward `2020-Q2`, which is rare only because the window ends 2020-06-30.
The blueprint's own example rule uses year, not quarter. Removing quarter gives
644 rules whose top entries are real patterns, including `Business => 2017` —
which is the RQ1 filing artefact showing up again.

**313 of the 644 rules are tautologies** with lift exactly 1.000, because the
sensational flag and the sentiment band derive from the same score. Tautologies
are counted separately and excluded from the headline tables. The best
information is in the confidence table, since lift is maximised by rare
consequents.

Rules are association, never causation. A test greps the output for causal
wording.

## RQ6: no link to returns, a real link to volatility

Over **1,235 paired trading days** — headlines exist on 1,828 days and the
market trades on 1,235, so only trading days are used, because a weekend has
headlines and no close price.

### Against daily returns: nothing

| measure | strongest \|r\| | lag | p |
|---|---:|---:|---:|
| headline volume | 0.0230 | 0 | 0.419 |
| mean sentiment | 0.0459 | 0 | 0.107 |
| mean sensational score | 0.0748 | 5 | 0.0087 |

**15 lag tests were run. One is significant, and about 0.75 are expected by
chance at α = 0.05.** The significant result is therefore within what the number
of tests produces, and the report says so instead of quoting p = 0.0087 as a
discovery. The coefficient is small in any case.

### Against 20-day volatility: a real association

| measure | Pearson r | variance explained | p |
|---|---:|---:|---:|
| **log headline volume** | **−0.2827** | **8.00%** | < 0.0001 |
| mean sentiment | −0.0226 | 0.05% | 0.428 |
| mean sensational score | +0.0236 | 0.06% | 0.408 |

**Log business-headline volume correlates with 20-day volatility at
r = −0.2827.** This is a real association, and the sign is the interesting part:
*busier headline days go with calmer markets*. It explains 8% of the variance, so
it is neither noise nor a strong predictor.

The direction is not explained, and this data cannot explain it. Two readings
fit equally well: a newsroom under pressure covers the crash rather than
business, or headline volume in this archive is capped and crisis coverage
displaces routine coverage. Separating them would need the unrounded per-day
export. It is reported as an association and left there.

## RQ7: the only result permitted to state an accuracy

IFND's majority class is **65.9%**: 33,684 real against 17,426 fake. A model
answering "real" to everything already scores 0.659, so accuracy alone flatters
a model that learned nothing.

| model | accuracy | fake recall | fake precision |
|---|---:|---:|---:|
| Multinomial Naive Bayes | 0.9540 | 0.9078 | |
| Complement NB | 0.9463 | 0.9256 | |
| **Logistic regression** | **0.9571** | 0.9137 | 0.9585 |

Logistic regression is chosen on **training** cross-validated accuracy (0.9577)
and the test split is scored once. Selecting on test accuracy and then reporting
that number is the optimism the blueprint warns against, so the two are kept
apart and a test asserts the choice follows the train score.

Reported as `lift_over_baseline_pp` = **+29.8 points**, with the confusion matrix
and the Fake class first.

**This is an upper bound.** Part of IFND's Fake class is LSTM-generated
augmentation of real statements, which is easier to distinguish than a fake
article written by a person. 95.7% is not 95.7% against genuine misinformation.

The classifier uses no dates, so IFND's largely unusable date column does not
affect it.

## Guard rails

Every module records its checks into one `guard_summary`, and a failed guard is
not necessarily an error: refusing to report a statistic on too little data is
the guard working.

Refusals, with the reason returned rather than a division by zero:

- fewer than 3 points for a correlation or z-score
- fewer than 100 paired trading days for RQ6
- a class with fewer than 2 members for the classifier
- cross-validation folds capped by the smallest class, so a `--sample` run does
  not crash where a full run would not
- topics below `min_topic_rows` excluded from the RQ3 ranking and listed
  separately
- a rate never reported without its denominator

## Reproducibility, and two bugs that broke the claim

`reports/mining.json` is byte-comparable between runs apart from the run id and
the timings, and a test asserts it. Getting there found two real defects.

**DuckDB's sampler returns the wrong number of rows.** `USING SAMPLE
reservoir(2000 ROWS) REPEATABLE (seed)` returned **709 rows when 2000 were
requested**, and the count moved with the table's physical layout. The sampling
code compensated by topping the draw up from the first headlines by id, which
converts a random sample into a chronological one — the oldest slice of the
corpus. That biased every clustering and rule result. `dwm/mining/sampling.py`
now sorts on `hash(column, seed)` and takes the first n, which is exact and
identical across processes. A test asserts the sample is not a first-n sample.

**`silhouette_score` subsamples with no seed by default.** Without an explicit
`random_state` the score moved between runs of an otherwise identical pipeline
(0.0652 then 0.0681 for the same k and the same sample), which made the claim
that fixed seeds reproduce every number false.

A third defect was caught the same way: the first attempt at a hand-rolled
sampler hashed `(id * 2654435761 + seed) % 4294967291`. Adding the salt after
the multiply leaves the relative order of two ids unchanged, so different seeds
returned identical samples. A seed that does not change the draw is not a seed.

## Cost

91 seconds on the full corpus, dominated by RQ4 (77 s: nine K-Means fits at
k = 4..12 over 60,000 documents, plus the stability refit). Rules take 3 s, the
classifier 4 s, everything else under a second. All seeds are fixed, so a re-run
reproduces every number.
