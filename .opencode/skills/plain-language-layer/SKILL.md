---
name: Plain Language Layer
description: How to write or change the plain-language layer in facts.json — the intro, the thirty-second summary, the glossary, number scales and cluster glosses. Use when adding a finding, editing prose in dwm/inference/plain.py, or when a summary sentence needs a new figure. Tests in tests/test_plain_layer.py enforce the rules.
---

# The plain-language layer

## Why it exists

The dashboard was correct and unreadable. It said `silhouette 0.2582` and
`LSA component 1` and `313 tautological rules` and expected the reader to supply
the meaning. Somebody without a data-warehousing background could read every
number and come away with no conclusion, which makes the rest of the project
pointless.

`dwm/inference/plain.py` is the fix. It sits **beside** the technical layer, not
over it.

> **Never remove the technical layer.** This is an academic data-warehousing
> project; an examiner will ask about silhouette and lift. A project that hid
> them would look shallow, and you would get caught out in the viva. Both
> audiences, same page, plain first and technical always one click away.

## The two rules

**1. Interpolate every number. Never retype one.**

```python
f"{metrics['accuracy'] * 100:.1f}%"      # yes
"On the labelled data it scored 95.7%"   # no
```

If a measurement changes, an interpolated sentence changes with it. A retyped
one does not, and a drifted sentence is worse than no sentence — it is a
confident lie. `tests/test_plain_layer.py` asserts the quoted fragments match
`facts.json`, so this is machine-enforced rather than a convention.

**2. Plain is not vague.**

"There is some structure here" is not plain English, it is a hiding place. Each
finding states what was measured, what the number means against its possible
range, and what it does not license. Brevity comes from short sentences, not
from withholding the caveat.

Every summary item carries **three** parts, and all three are required:

| Part | Job |
|---|---|
| `claim` | the conclusion, as one plain sentence |
| `body` | what was measured, with its scale |
| `so_what` | why it matters — the sentence that turns a measurement into something a reader can act on |
| `caution` | what it does not license |

`so_what` is the part that makes the module worth writing. Do not skip it.

## The denylist

`test_no_jargon_leaks_into_the_intro_or_summary` fails the build on these in the
intro or summary: silhouette, tautological, TF-IDF, LSA, z-score, p-value,
coefficient of variation, k-means, apriori, FP-Growth, variance, confidence
interval, lift, cohort, ETL, OLAP, star schema, cube, null result, significance.

The fix is to **rephrase, not to remove the measurement**. "About 28 in every
100 busier days went with a calmer market" carries exactly as much information as
`r = -0.2827` and can be judged by a reader who has never heard of a correlation
coefficient.

Where a term genuinely must appear, it belongs in the **glossary**, and the
glossary has to cover every denylisted concept —
`test_the_glossary_explains_the_jargon` checks that.

## Numbers need scales

`scales` supplies the range or comparison for each headline figure. A score
without its range is decoration: `0.2582` could be excellent or meaningless and
the reader cannot tell.

```python
"silhouette": (
    "Out of a possible 0 to 1, where 0 is no structure at all. Short news "
    "text usually scores 0.1 to 0.3, so this sits in the normal band..."
)
```

`test_scales_never_overstate_a_measurement` checks the scales do not flatter: the
silhouette scale must not call the score high, the correlation scale must state
its range and weakness, and the rule-count scale must carry the tautology count.

## Cluster glosses are matched, never inferred

`gloss_terms` maps a cluster's top words to plain descriptions by looking for
those words in a pattern table. If nothing matches, it returns
`summary: None` and a note saying the vocabulary cannot be summarised.

**That fallback is load-bearing.** A cluster of headlines whose distinguishing
words we cannot describe is itself worth knowing. Describing it anyway would
invent a finding, in the one place a reader is most likely to take it on trust.
`test_cluster_terms_are_glossed_not_invented` checks every non-dominant
cluster's gloss is backed by at least one of its own words.

The dominant cluster (>50%) gets its own description: "General news vocabulary —
no distinguishing subject". Its top words are just the words most headlines use,
so listing "people's ages, police and crime" for 95% of the corpus would imply
the blob is a topic with several themes, which is the opposite of what it is.

## Adding a finding

1. Add the item to `build_summary` with all four parts
2. If it needs a new number, interpolate it from `facts` in that function
3. If the number needs a scale, add it to `build_scales`
4. If it introduces a term of art, add it to `build_glossary`
5. Run `pytest tests/test_plain_layer.py`

The coverage test requires every RQ to appear in the summary, including the null
and qualified ones — that test has already caught a missing RQ1.

## Where it renders

- **Intro** — top of Overview, and the first tab of How it works
- **Summary** — seven cards on Overview, plus a plain reading at the top of each
  finding page
- **Glossary and scales** — How it works → Plain guide, which is the default tab
- **Inline terms** — `.term` spans with the definition in the markup, not a
  tooltip, so it works without hovering and cannot be clipped off-screen
- **Cluster glosses** — a table on the topic-clusters page, raw words beside the
  translation so the claim can be checked rather than trusted

## Writing voice

Short sentences. Concrete nouns. No hedging adverbs. The "so what" lines are
allowed to be direct: "This data cannot tell that pattern apart from an artefact
of how the publisher exported it, and we are not going to guess" is plain
English, and it is more useful than a cautious sentence that says nothing.

Do not use `*emphasis*` in the claim lines — they render as literal asterisks in
a couple of places because the claims are set in a heading context.