# Demonstration runbook

Ordered so the strongest thing is first and the build is last. Every command
here has been run and every row count verified.

**Before you start** — one terminal, one command. `dwm serve` starts the API
*and* serves the dashboard from the same process on the same origin, so there is
no second server to start and nothing to get wrong.

```powershell
.\.venv\Scripts\python.exe -m dwm serve
```

Open **http://localhost:8000**. Leave it running for the whole demo.

The CLI stays usable at the same time, so you can keep this terminal and a second
one open and switch freely.

Total: about 25 minutes. Timings in brackets.

---

## 1. The claim, before any tooling (30s)

Open `reports/report.md` in VS Code and leave it visible.

> "I built a warehouse over 3.3 million Times of India headlines, 56,714
> labelled IFND statements and five years of Nifty 50 closes, and answered
> seven research questions against it.
>
> **Three of the seven produced no result, or a result that reads better than
> it is.** Those are the most useful findings, because they're the ones a less
> careful analysis would have dressed up."

Point at the section list. Ten sections, 34 KB, generated.

---

## 2. The data (2 min)

**In the dashboard:** Overview. Show the four KPI cards.

Say the number out loud: **1,113,427 headlines in the analysis window**,
2015-06-30 to 2020-06-30.

Then the three limitation cards, because a limitation stated before a finding
is worth three stated after it:
- no ground truth on the headline corpus
- IFND is imbalanced, so 65.9% is the baseline
- IFND dates are largely unusable

**In the CLI:**

```powershell
.\.venv\Scripts\python.exe -m dwm tables          # 27 tables, 17.2M rows
```

> "Staging is lossless and gated: `stg_toi` is 3,297,172 against the source
> file. Cleaning drops 142,256 exact duplicates. Facts must equal the clean
> counts, and that's a test, not a convention."

---

## 3. Data quality — the part examiners probe (3 min)

**In the CLI:**

```powershell
.\.venv\Scripts\python.exe -m dwm audit           # the run funnel
.\.venv\Scripts\python.exe -m dwm config --verbose # URLs, aliases, provenance
```

Have these ready, because they will be asked:

| If they ask | Answer |
|---|---|
| Why is IFND's baseline 65.9%? | 33,684 real vs 17,426 fake. Always answering "real" scores 0.659. |
| Why is the window a flag not a filter? | Filtering throws away 2M still-queryable rows. `in_window` is a boolean on the fact row. |
| How do you know the grain is right? | (date, text). 37,629 texts recur across dates; 111,146 pairs are multi-category, so one row per category would multi-count ⅓ million headlines. |
| How do you know the keys are right? | `dim_dataset` numbers by sorted code, so `toi` is key 3. A hard-coded 1 pointed every headline at the wrong source while all counts stayed correct. DDL looks keys up now. |
| Why sums and not averages in cubes? | A rounded average can't be averaged again. Every mean is recomputed as sum ÷ count. A test rejects any column named like a mean. |

---

## 4. OLAP — all ten operations (4 min)

All ten work **with the dashboard running**. Verified row counts:

```powershell
.\.venv\Scripts\python.exe -m dwm olap --op slice -p topic=Business    # 50
.\.venv\Scripts\python.exe -m dwm olap --op slice_year -p year=2018    # 16
.\.venv\Scripts\python.exe -m dwm olap --op dice                       # 108
.\.venv\Scripts\python.exe -m dwm olap --op roll_up                    # 92
.\.venv\Scripts\python.exe -m dwm olap --op drill_down                 # 12
.\.venv\Scripts\python.exe -m dwm olap --op top_months -p n=10         # 10
.\.venv\Scripts\python.exe -m dwm olap --op pivot                      # 61
.\.venv\Scripts\python.exe -m dwm olap --op cube -p topic_group=Subject # 200
.\.venv\Scripts\python.exe -m dwm olap --op drill_across -p topic=Business # 200
.\.venv\Scripts\python.exe -m dwm olap --op topic_mix                  # 63
```

Don't read them all. Pick three and say what each *demonstrrates*:

- **`slice`** — one dimension. "Business by month, 50 rows."
- **`roll_up`** — "month rolled up to year, 92 rows. The sums are exact and the
  mean is sum ÷ count, not an average of monthly means."
- **`drill_across`** — the one that shows the star schema.
  > "This joins two facts — daily Business headline counts beside Nifty close,
  > return and volatility — on the only days where both exist. Headlines
  > appear on 1,828 days in the window; the market trades on 1,235. A weekend
  > has headlines and no close price, so joining on the calendar would invent
  > data."

Add `-p topic=Sports` or `--limit 20` to any of them to show parameters work.

---

## 5. The seven questions (8 min)

**In the dashboard,** one finding page each. Language, Co-occurrence rules,
`Classifier` are the four worth pausing on.

### RQ2 — the flatness (2 min) — *your strongest moment*

Trends panel, or Warehouse panel → "Monthly series" chart. That chart is
**visibly flat** and examiners will notice it before you say anything.

> "Monthly headline volume is almost perfectly flat. Within-year variation is
> 2 to 4%, and March 2020 — the month India entered a national lockdown — is
> 2.5% above its own year mean.
>
> A z-score of 2.0 detects nothing, and lowering it until something appeared
> would be choosing a threshold to manufacture a result. So I fixed a
> prediction in the config *before* looking: Health, Sports and Entertainment
> coverage should rise during these events. **In 5 of the 10 event months all
> three fell instead**, including all three COVID months.
>
> I can't tell you whether that's a genuinely quota-driven newsroom or a
> sampling artefact of the publisher's export. This data can't separate them,
> and I'd rather say that than pick the more interesting one."

### RQ3 — the threshold judgement (1.5 min)

Language panel → scroll to the sensitivity table.

> "The threshold is 0.2208, the measured 95th percentile, not a round number —
> 0.5 flagged 156 rows out of 3.15 million, which isn't a threshold.
>
> And `Unknown` tops the raw ranking at 17.29%. I excluded it. It's a filing
> gap, not a subject — a reader told 'Unknown is the most sensational topic'
> has learned nothing. The top real topic is Education at 10.94%."

**This is the decision most likely to be challenged. Have it ready.**

### RQ5 — the rules (1.5 min)

Rules panel.

> "1,804 rules, then 644. I want to be clear about why the number changed,
> because both are true at different times.
>
> Year and quarter are redundant in both directions — a quarter implies its
> year. Including both gave me 1,797 rules that were almost entirely
> `2020-Q1 => 2016` arithmetic, and pushed every high-lift rule toward
> 2020-Q2, which is rare only because the window ends mid-year. I removed
> quarter, which is what the blueprint's own example rule uses anyway.
>
> Apriori and FP-Growth return the **identical** rule set, which is asserted —
> they search the same itemsets, so a difference would mean one is broken. The
> only thing I'm measuring is time, and FP-Growth is about 1.4× faster.
>
> The keyword run you might expect is **zero rules**, and that's reported as a
> finding: the 300-term vocabulary yields 1.99 items per headline because its
> top terms are `govt`, `held`, `get`, `man`."

### RQ7 — the baseline (1.5 min)

Classifier panel.

> "95.71% — but that number means nothing on its own. The majority class is
> 65.9%, so always answering 'real' scores 0.659. Against the baseline it's
> **+29.8 points**, and the Fake class is reported first because it's the class
> a detector is for: 91.4% recall.
>
> I chose the model on *training* cross-validated accuracy and scored the test
> split **once**. Picking on test accuracy and then reporting that number is
> the optimism this study set out to avoid.
>
> And it's an **upper bound**: part of IFND's Fake class is LSTM-generated
> augmentation, which is far easier to distinguish than a fake written by a
> person."

### RQ4 and RQ6 — if time allows

RQ4 is the *correction*, and it's the most interesting thing you can say about
your own work. See `docs/VIVA.md` for the full version.

RQ6: no link to returns (max |r| 0.0748), but **r = −0.2827 to volatility** —
busier headline days go with calmer markets, and the sign is unexplained.

---

## 6. Traceability — the mechanism (2 min)

This is what separates the project from a script that prints numbers.

**In the CLI:**

```powershell
.\.venv\Scripts\python.exe -m dwm report
```

> "That just re-rendered `facts.json` and `report.md`. The report **cannot
> compute anything** — there is no language model anywhere in the reporting
> path, deliberately, because a language model can produce a fluent sentence
> containing a number nobody computed."

Then open `reports/facts.json` side by side with `report.md`:

> "Every fact records the source it came from and, where it's easy to misread,
> the caution that must travel with it. Three tests hold this: every fact has a
> source, every fact with a unit has a caution, and every caution in the JSON
> appears in the report. The third one matters — a caution sitting in a file
> and never reaching the document is a dropped caution."

**In the CLI** — the gate, which is the bit examiners like:

```
inference gate: 15 of 15 checks passed
```

> "The gate exits non-zero on failure, so a pipeline can't pass silently on a
> warehouse that can't back its own numbers. It still writes the report, because
> 'this couldn't be measured, and here's why' is more useful than no report."

---

## 7. The API (1.5 min)

**http://127.0.0.1:8000/docs** — interactive Swagger UI.

| Click | Show |
|---|---|
| `GET /health` | status, plus the snapshot path |
| `GET /summary` | 77 KB of facts, each with `unit` and `caution` |
| `GET /query/topic_mix` | an OLAP operation over HTTP |
| `GET /query/drop_table` | **404** — "unknown operation". Point out the operation is looked up in a whitelist, never interpolated into SQL. |
| `GET /headlines?limit=9999` | **422** — the cap at 500, not silently clamped |

> "The API serves results, it doesn't recompute them. The one exception is
> `/query/{operation}`, which exists for ad-hoc slicing and is whitelisted to
> the ten named operations.
>
> Read-only is a property of the file, not a promise: the handle is opened
> read-only, so no malformed request can write to the warehouse even if
> validation were bypassed.
>
> And it serves a **snapshot** copy, because DuckDB locks its file exclusively
> even read-only. That's why I can leave this running and still run CLI
> commands."

---

## 8. The dashboard: answer first, and the honesty mechanism (2 min)

Back to **:8000**. Start on **Overview** and scroll.

> "Every page leads with its answer, not its data. Each outcome carries the
> question, the answer as the largest text on the page, how we know, and the
> caveat — the caveat sits with the number rather than in a footnote."

Show the metric tiles, then the outcomes in order. Point out that the null
result is **present** rather than dropped: "we looked and there was nothing" is
the answer to a question, and the reader is entitled to know it was asked.

Now **Findings**, and click through two or three. The **Volume and events** page
is the strongest: the diverging bars show Health, Sports and Entertainment all
falling during the pandemic months, and the legend says so in words rather than
leaving two unexplained colours.

Then **How it works** -> **Corrections**:

> "This is the part I'm most pleased with. Four things this study got wrong,
> each of which had looked convincingly like a finding. The clustering one
> especially: I reported 0.068 as 'these headlines have no topic structure', and
> the fault was my feature engineering admitting numerals and stop words, not
> the data. Fixing it gave 0.2582 — and the report states the correction rather
> than quietly replacing the number."

Open the sidebar's **honesty rules** expander:

> "Those cautions travel with the API response and the dashboard renders them
> under every figure. It also refuses to render a figure that has a unit and no
> caution, and at startup it walks the whole payload looking for one — if it
> found any, the warning would appear in the sidebar. A bare '10.9%' detached
> from 'risk-signal rate on unlabelled headlines' is exactly how a risk-signal
> rate stops being called one."

If asked how the interactivity works, note that the charts are Altair with hover
tooltips, the topic charts are click-to-filter, and the CSV download under
**Explore** returns exactly the data behind each chart. Also worth saying: the
dashboard computes nothing, so it cannot disagree with the report.

## 9. Reproducibility (2 min)

```powershell
.\.venv\Scripts\python.exe -m pytest -q      # 369 tests
.\.venv\Scripts\ruff.exe check .             # clean
```

> "369 tests, no network, and they never touch the real warehouse or the
> reports directory. They check the promises rather than the numbers: that a
> rate is never reported without its denominator, that a statistic from too
> few observations is refused with a stated reason, that the payload carries
> no causal wording and no 'fake news rate', and that two mining runs agree on
> every number."

Then the full rebuild — **5m36s**:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean
```

> "Raw CSV to report.md, from nothing, in under six minutes. Everything about
> this project regenerates from three downloaded files."

*(Only run this if you have the time. It's the riskiest item in the runbook —
if it fails on the demo machine, you're stuck explaining a rebuild instead of
your findings. Have `reports/report.md` already open as your fallback.)*

---

## 10. Close (30s)

> "To summarise: three of the seven questions produced no result, and reporting
> them with the measurement that establishes them was more useful than finding
> something presentable. The positive results are a 10.94% risk-signal rate on
> Education against a 3.77% baseline, 644 association rules two independent
> algorithms agree on exactly, and a classifier at 95.7% against a 65.9%
> baseline.
>
> The thing I'd do differently: get a corpus sampled by newsworthiness. The
> flat volume is plausibly an artefact of the export, and everything downstream
> of that question is weakened by not knowing which it is."

---

## Fallbacks

If something breaks mid-demo:

| Problem | Do this |
|---|---|
| Port 8000 busy | `dwm serve --port 9000`, then browse to `http://localhost:9000/` |
| A chart shows an error box | The chart library did not load — it comes from a CDN, so this needs internet. Every number is on the page as text. |
| Dashboard won't load | `reports/report.md` covers every finding, and `Get-Content reports\facts.json` has every number with its source. |
| `dwm olap` says file in use | Something is holding the warehouse. `Get-Process python \| Stop-Process -Force`, then `dwm serve` again. |
| Warehouse gone | `powershell -ExecutionPolicy Bypass -File .\run_all.ps1 -clean` then `dwm mine` then `dwm report` — 6 minutes. |
| You need a number | `Select-String` it in `reports/facts.json`. Every figure is there with its source. |

## Do not do these

- **Don't demo a rebuild unless you have 10 spare minutes.** It's the only item
  that can fail on someone else's machine.
- **Don't lead with the pipeline.** Lead with the finding, then prove it.
- **Don't read the dashboard panels aloud.** Point at one number and talk about
  what it means.
- **Don't defend the 0.2208 threshold.** Show the sensitivity table and let it
  speak. It already demonstrates you know it's a judgement.
- **Don't hide the RQ4 correction.** It's the strongest thing you can say about
  your own work, and `docs/VIVA.md` has the full version.
