---
name: Dashboard Honesty
description: The invariants the dashboard must never break — no figure without a caution, nothing recomputed in the browser, nulls shown not hidden, associations never called causation. Use when adding a figure, editing facts.json keys, or reviewing anything that renders a number.
---

# Honesty invariants

These are what make this project defensible rather than merely working. Each has
a test that fails if it is broken, which is the only reason they are worth
stating.

## 1. No figure renders without its caution

A bare "10.9%" on a screen, detached from "risk-signal rate on unlabelled
headlines", is exactly how a risk-signal rate stops being called one. The
dashboard is the last place that wording survives contact with a reader.

Enforced at three levels:

- **`find_uncautoned`** in `dashboard/helpers.py` walks a payload for any figure
  with a `unit` and no `caution`, returning the dotted paths so a failure names
  the section.
- **`auditPayload`** in `static/app.js` runs the same walk at start-up over the
  whole `/summary` response and puts the count in the top bar.
- **`figure()`** in `app.js` renders a visible warning if a specific figure
  arrives without one, rather than showing the bare number.

The fact structure is `{value, unit, source, caution}`. **Spell it `caution`,
everywhere.**

> This exact thing broke once. `build_outcomes` emitted its per-outcome caveat
> under the key `caveat` while the rest of the project spelled it `caution`, so
> **every caution on the conclusions page silently rendered as absent** — on the
> one page whose entire job is stating what may not be claimed. Nothing raised.
> `test_every_outcome_carries_a_caution` and
> `test_outcomes_use_the_project_wide_caveat_spelling` now pin it.

## 2. The dashboard computes nothing

Every figure was measured once by the mining stage, written to `facts.json` by
the inference stage, and served unchanged.

Drawing a chart is not computing. But if the browser derived a rate, computed a
total, or sorted by a measure, it would be a second source of truth and the two
would drift — and the drift would be invisible.

**Building chart specs in Python is not a violation.** It is presentation, and it
happens where a test can reach it.

Two exceptions, both browse-only and both deliberately marked:

- The monthly-series chart in `renderSeries` is assembled in the browser. It is a
  browse view with no published figure behind it.
- Page text sorts nothing. It reads arrays in the order the warehouse stored.

## 3. Null results are shown, never dropped

"Zero months spiking on volume" is a finding, and it needs the measurement that
establishes it. `outcomes` keeps it with `kind: "null"`, and
`test_every_outcome_carries_a_caution` asserts `counts.null >= 1`.

Dropping a null makes "we looked and found nothing" indistinguishable from "we
did not look". Same for a stage that declined to run: `ran: false` counts as a
gate failure, because a section that did not run has not answered its question.

## 4. Associations are never causation

Every correlation on this dashboard says "association", and says what it cannot
distinguish. The volatility finding states that both series respond to the same
underlying events and that nothing here identifies a direction of effect. The
lift figures say a rule states two attributes co-occur more often than chance.

A coefficient with no count of tests beside it invites over-reading. RQ6 shows
all fifteen lag tests, names the one that came out significant, and states that
fifteen tests at α = 0.05 produce about 0.75 false positives by chance.

## 5. Style measures are never fake-news rates

On the unlabelled TOI corpus, every style measure is a **risk-signal rate**.
Nothing in that corpus is labelled. Only the IFND classifier makes an accuracy
claim, and only as an upper bound, because part of IFND's Fake class is
LSTM-generated augmentation — far easier to distinguish than a fake written by a
person.

The `is_risk_signal` flag in Explore carries its caution inline, every time.

## 6. A threshold is a judgement, so show the sensitivity

The cut-off is the measured 95th percentile, 0.2208. Because any cut-off is a
choice, RQ3 ships a table across eight of them and states that the ranking is
**not** stable across that range. A threshold chosen until something appeared
would be choosing a threshold to manufacture a result.

## 7. Numbers state their denominator

Every rate carries the count behind it. Confidence intervals are drawn, not
hidden in a tooltip. Tables caption the total and the filter. `Unknown` and
`Other` are excluded from rankings and the exclusion is named.

## Adding a figure

Before it renders, it needs:

1. A `caution`, or an explicit statement that none applies and why
2. Its denominator or n
3. A source in the payload
4. If it is a rate on unlabelled data: the word "risk-signal", not "fake"
5. If it is a correlation: the number of tests, and what else could explain it
6. If it is null: still shown

Then run `pytest tests/test_ui.py`. Steps 1 and 3 are machine-checked.