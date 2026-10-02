# Viva sheet

Every claim below is answerable with one command, and the command is given.
Written for the oral, so each answer is short enough to say out loud and the
follow-up question is already anticipated.

## The one-minute version

I built a DuckDB warehouse over 3.3 million Times of India headlines, 56,714
labelled IFND statements and five years of Nifty 50 closes, then answered seven
research questions against it. **Three of the seven produced no result, or a
result that reads better than it is** — and those are the most useful findings,
because they are the ones a less careful analysis would have dressed up.

The three: the headline volume contains no news signal; the topic structure that
exists covers 5% of the corpus; and the headlines have no relationship to daily
market returns. The positives are a 10.94% risk-signal rate on Education news
against a 3.77% baseline, 644 association rules that two independent algorithms
agree on exactly, and a classifier at 95.7% against a 65.9% majority baseline.

## Where to find the numbers

| | |
|---|---|
| Generated report | [`reports/report.md`](reports/report.md) |
| Machine-readable results | `reports/mining.json` |
| Every number with its source and caveat | `reports/facts.json` |
| Reasoning behind each stage | [`docs/`](docs/) |
| Handover and known traps | [`docs/STATUS.md`](docs/STATUS.md) |

## The seven questions

| Q | Command | Answer |
|---|---|---|
| 1 topic mix | `dwm olap --op topic_mix` | `Local` is 69.95% of the window; one 2017 filing artefact |
| 2 bursts | `dwm mine` | **zero.** Volume CV is 0.0202–0.0352 within every full year |
| 3 sensationalism | `dwm mine` | `Education` 10.94%, CI 10.06–11.89%, n=4,450, vs 3.77% corpus |
| 4 clusters | `dwm mine` | silhouette 0.2582, but 94.88% of the corpus in one cluster |
| 5 rules | `dwm mine` | 644 rules, Apriori and FP-Growth identical, FP-Growth 1.4× faster |
| 6 market | `dwm mine` | no link to returns; **r = −0.2827 to 20-day volatility** |
| 7 classifier | `dwm mine` | 95.71% vs 65.90% baseline, Fake recall 91.37% |

## Questions I expect, with the answers

### "Why DuckDB?"

Single file, no server, columnar, and it handles 3.3M rows plus 4.2M bridge
rows in memory. The whole warehouse is a 573 MB file that can be deleted and
rebuilt in six minutes. Postgres would need a server for a project that has to
be reproducible on a laptop.

### "How do you know the data is right?"

Row counts reconcile at every stage. Staging is lossless and gated:
`stg_toi` = 3,297,172 against the source file. Cleaning drops 142,256 exact
duplicates to 3,154,916. Features and facts must equal the clean counts, and
the key must be unique — that gate is a test, not a convention.

The subtlety: headline grain is **(date, text)**, not text alone and not
date+text+category. 37,629 texts recur across dates, and 111,146 pairs are
filed under more than one category, so one row per category would multi-count a
third of a million headlines in every topic analysis.

### "Why is the analysis window a flag and not a filter?"

Because filtering throws away 2 million rows that are still worth querying, and
it makes the ETL destructive. `in_window` is a boolean on the fact row. The
window is derived from `max(publish_date)` minus five years, so it is never
stale, and it came out as 2015-06-30 to 2020-06-30.

The cost is that 2015 is a **partial year**, which is why every trend statement
is a within-year share and raw counts across years are never compared.

### "Why cubes, and why only sums?"

Because the questions are about rates and cubes are stored sums. A cube column
named like a mean is rejected by a test. Every mean in the report is recomputed
as sum ÷ count at query time, so a rounded average is never averaged again.

### "Your sensationalism threshold is 0.2208. Isn't that arbitrary?"

It is a judgement, and the report says so. It is the **measured** 95th
percentile, not a round number, and the report ships a sensitivity table across
eight thresholds so a reader can see whether the ranking survives. The original
0.5 flagged 156 rows out of 3.15 million, which is not a threshold, it is a
rounding error.

The metric is a **risk-signal rate**, not a fake-news rate, because these
headlines have no labels. A test greps the whole payload to enforce that.

### "Why is `Unknown` excluded from the ranking?"

Because it tops it at 17.29% and that number means nothing. `Unknown` is a
filing gap, not a subject — the absence of a filing decision, not a style. A
reader told "Unknown is the most sensational topic" has learned nothing. It is
reported separately with that explanation, and excluded from the headline
ranking and from the stability judgement.

### "Your clustering says 0.2582 but you also said there was no structure. Which is it?"

That is the most useful correction in the project, and I would rather be asked
about it than hide it.

The first run measured 0.068 and concluded the headlines had no recoverable
topic structure. **That conclusion was wrong, and the fault was mine.** The
scikit-learn token pattern admits pure numerals, so the clusters were described
by `000`, `102` and `1000`. Then, with numbers filtered, they were described by
`for`, `with`, `from` — because the mean TF-IDF inside a cluster is highest for
function words. And the descriptions were being read off the K-Means centroid
weights, which through an LSA basis returned `aadhaar, aadmi, aap, aarti` for
*every* cluster, because SVD components carry an arbitrary sign and small
numerical asymmetries make alphabetically-early features win.

Fixing all three took it to 0.2582. The lesson I took from it is that "the data
has no structure" and "my features had no signal" are very easy to confuse, and
a silhouette computed on a different feature space will not tell you which you
have.

**And 0.2582 still does not mean the corpus is well clustered.** One cluster
holds 94.88% of it. Silhouette scores a document by its distance to its own
cluster against the nearest other, so a large blob far from three small tight
ones scores well. So the report gives the score *and* the shape, and the
conclusion is that what the clustering found is `rs crore`, `road accident` and
`year old` — **writing patterns, not desks.**

### "Why mine attributes when the blueprint mentions keywords?"

Because I measured the keywords first. The 300-term vocabulary yields **1.99
items per headline**, because its most frequent terms are `govt`, `held`, `get`,
`man`, `police`. A two-item transaction supports almost no co-occurrence, so
rules over it would be reporting sparsity as a pattern. Mining it produced
**zero rules**, which the report states as a finding about the feature.

The blueprint's own example is attribute-shaped anyway —
`topic=Business, year=2016 => sensational=high` — and attribute transactions
carry 6.00 items each. The keyword result is reported rather than dropped,
because "this feature cannot support the analysis" is worth knowing.

### "Why run both Apriori and FP-Growth if you already know the answer?"

To measure the time honestly. Both run on **identical transactions with
identical thresholds**, and `rule_sets_identical: true` is asserted. They search
the same itemsets, so a difference would mean one is broken, not interesting.
The only thing being compared is the wall clock, and FP-Growth is about 1.4×
faster here.

### "Your rules came out as `5 => 4` and every lift was 1.000. What happened?"

Two real bugs, and both looked like findings.

`use_colnames` defaults to `False` in mlxtend 0.23+, so the antecedents came
back as column **indices**. And I was reading the rule frame **by position**,
which was off by two: the columns are ordered `antecedents, consequents,
antecedent support, consequent support, support, confidence, lift`, so `r[2]` is
the consequent support, not the support. That made the *confidence* appear in
the *lift* column, and all 644 rules came out at exactly 1.000 — which reads
convincingly as "every attribute is a tautology" and was pure mislabelling.

Both are now fixed and both have tests. Columns are read by name, because
column order also varies between mlxtend versions, so positional access is wrong
by construction.

### "313 of your 644 rules are tautologies. Is that a problem?"

It is a finding about the attribute scheme, and it is why `quarter` is not in
the default item set. Year and quarter are redundant in **both** directions — a
quarter implies its year — so including both produced 1,797 rules that were
almost entirely year/quarter arithmetic, and pushed every high-lift rule toward
`2020-Q2`, which is rare only because the window ends 2020-06-30.

The remaining 313 tautologies come from the sensational flag and the sentiment
band, which derive from the same score. They are counted separately and excluded
from the headline tables, because `2016-Q1 => 2016` is arithmetic, not pattern.

### "Your headline volume is flat. Is that the data, or did you break something?"

Good question, and the honest answer is that I cannot fully distinguish those.

Within-year CV is 0.0202 to 0.0352, and March 2020 — the month India entered a
national lockdown — is 2.5% above its own year mean. That is a real property of
the series, not a bug: I checked it with direct SQL on the cube before writing
any detection code.

What I could not do is explain it. Two readings fit equally well. Either the
archive behaves like a fixed editorial capacity filling a fixed number of slots,
or it is a sampling artefact of whatever export the publisher produced. This
data cannot separate them, and the report says so rather than picking the more
interesting one.

What I could test is a prediction fixed **in the config before I looked**:
Health, Sports and Entertainment coverage should rise during the listed events.
In 5 of 10 event months all three fall instead, including all three COVID
months. A prediction made in advance that then failed is worth more than the
absence of a signal.

### "You found a significant correlation. So news does affect the market?"

No, and the report does not say that. There are two separate things here and
they need separating.

Against **daily returns**, there is nothing: the strongest coefficient is 0.0748
and only 1 of 15 lag tests is significant. At α = 0.05, fifteen tests produce
about 0.75 false positives by chance, so one p below 0.05 is the expected
outcome of running the tests. I report the count of tests next to the p-value
for exactly that reason.

Against **20-day volatility**, there is something real: log business-headline
volume correlates at **r = −0.2827**, p < 0.0001, explaining 8% of the variance.
Busier headline days go with calmer markets.

That is an association, and I do not claim a direction of effect. Headline
volume and market volatility both respond to the same underlying events. The
negative sign is the interesting part and I cannot explain it: either a
newsroom under pressure covers the crash rather than business, or volume is
capped and crisis coverage displaces routine coverage. Separating those would
need the unrounded per-day export, which this corpus does not have.

### "95.7% accuracy — isn't that suspiciously high?"

It is an **upper bound**, and the report leads with that.

Three things bound it. Part of IFND's Fake class is **LSTM-generated
augmentation** of real statements, which is far easier to distinguish than a fake
article written by a person. IFND's dates are largely unusable, so I use text
only and make no claim about time. And 95.7% is measured against a **65.9%
majority baseline**, not against 50% — always answering "real" already scores
0.659, so plain accuracy would flatter a model that learned nothing.

I also chose the model on **training** cross-validated accuracy and scored the
test split **once**. Selecting on test accuracy and then reporting that number
is the optimism this study set out to avoid, and a test asserts the choice
follows the train score. I report lift over baseline, the confusion matrix, and
the Fake class first, because Fake is the class a fake-news detector is for.

### "How do you know the report's numbers are right?"

Because the report cannot compute anything. `dwm mine` writes
`mining.json`; `dwm report` writes `facts.json` and renders `report.md` from it
by **templates**. There is no language model anywhere in the reporting path, and
that is deliberate — a language model can produce a fluent sentence containing a
number nobody computed.

Each fact carries the `source` it came from and, where it is easy to misread,
the `caution` that must travel with it. Three tests hold this: every fact has a
source, every fact with a unit has a caution, and every caution in `facts.json`
appears in `report.md`. The third is the one that matters — a caution sitting in
a JSON file and never reaching the document is a dropped caution.

The API serves `facts.json` unchanged, so the dashboard cannot become a second
source of truth, and it refuses to render a figure that has a unit and no
caution.

### "What are the guard rails for?"

For the case where the data cannot support the claim. `dwm report` runs 15
checks and **exits non-zero** if one fails, so a pipeline cannot pass silently
on a warehouse that cannot back its own numbers. It still writes the report,
because "this could not be measured, and here is why" is more useful than no
report.

Concretely: a rate is refused below 1,000 rows, a correlation below 100 paired
observations, a z-score below 3 points. Cross-validation folds are capped by the
smallest class, so a `--sample` run does not crash where a full run would not. A
section that is present but empty fails the gate — a test caught that key
presence alone was satisfied by `rq4_clusters: {}`.

### "What would you do differently?"

Three things, in order.

**Get a corpus sampled by newsworthiness.** The flat volume is plausibly an
artefact of the export. Everything downstream of RQ2 is weakened by not knowing
which it is.

**Get a headline-level ground truth.** Then the sensationalism measure could be
validated against a real label instead of standing as a style proxy on its own.

**Separate the LSTM-augmented portion of IFND's Fake class** and report the
classifier on genuine misinformation as well. That is the part of the 95.7% I
trust least.

## Commands, in the order I would run them

```powershell
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean
.\.venv\Scripts\python.exe -m dwm report
.\.venv\Scripts\python.exe -m dwm serve
.\.venv\Scripts\python.exe -m dwm serve   # one process, dashboard included
```

Then, for any number: `dwm olap --op <name>` for OLAP, `reports/report.md` for
the finding, and `reports/facts.json` for its source and its caveat.
