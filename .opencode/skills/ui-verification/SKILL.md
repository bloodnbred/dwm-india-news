---
name: UI Verification
description: Verify a front end you cannot see. Use when building or changing dashboard UI, HTML, CSS or JavaScript in this project, or when a UI change is described as "looking wrong" and the actual defect is unknown. Covers wiring checks, data-path checks, contrast checks, and screenshot round trips.
---

# Verifying a UI you cannot see

## The problem this exists for

This project was built without a connected browser. That constraint is not a
reason to build less carefully — it is a reason to check the things a human eye
checks automatically.

Every defect in that category is **silent**: the server returns 200, the page
loads, no console error appears, and the suite stays green. The reader sees a
blank cell, an "n/a", or a chart drawn in the wrong colour, and has no way to
know whether that was intended.

Concretely, during the build that motivated this skill:

| Defect | What the eye would catch | What the suite would not |
|---|---|---|
| `taxonomy_artefacts` read as `.category`, actual key `.raw_category` | empty column | nothing |
| Lag rows read `.significant`, actual key `.significant_at_alpha` | blank badges | nothing |
| Returns r read from `.max_abs_r`, actually on the fact header | `undefined` | nothing |
| Outcomes emitted `caveat`, project spells it `caution` | **every caution missing** | nothing |
| Accent `#0071E3` on tinted background, 4.15:1 | faint text | nothing |
| Month axis sorted by z-score | 2020-05 beside 2016-12 | nothing |

The fourth is the one that mattered. It removed the caution from the single
page whose job is stating what may not be claimed, and nothing failed.

## Run the checks

```powershell
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_ui.py -q
node --check dashboard\static\\app.js
.\\.venv\\Scripts\\ruff.exe check .
```

`node --check` matters: the JavaScript is served raw with no build step, so a
syntax error is a page that silently does nothing.

## The five checks, and how to extend them

All live in `tests/test_ui.py`.

**1. Every CSS variable is defined.** `var(--x)` for an undefined `--x` is not
an error — it renders nothing. Extend the token list when adding a colour.

**2. Every id the JavaScript reaches for is declared.** `$("#foo")` returns
`null` on an undeclared id, and the failure surfaces somewhere else entirely.
Ids the JavaScript creates at render time are listed explicitly in
`runtime`; add to that list when adding one.

**3. Every chart the JavaScript names is served, and vice versa.** A missing
spec renders the error box. A served-but-unused spec is dead weight on the wire.

**4. Every dotted path the front end reads exists.** Asserted against the real
`facts.json`, not a fixture, because the bug is a mismatch with what mining
actually produces. When the mining output changes shape, this is the test that
tells you the front end broke.

**5. Contrast meets WCAG AA, in both themes.** 4.5:1 for body text, 3.0:1 for
large or non-essential text. Add a pair to `CONTRAST_PAIRS` when introducing a
new text-on-background combination. There is also a palette-drift test: the
chart specs duplicate the CSS colours because a Vega-Lite spec cannot read a
stylesheet, and duplication without a check is how a chart ends up drawn in
yesterday's blue.

## When a change looks wrong and you cannot see it

Do the cheap static checks first — a token typo, a missing id, a wrong key, a
contrast failure — because each has a real chance of being the actual cause.

Then **ask for a screenshot**, and be specific about where to put it — at the
repository root, named `_shot.png`.

Note that Win+Shift+S creates a *folder* with that name containing
`Screenshot <timestamp>.png` files. Glob for
`**/*.{png,jpg,jpeg,webp}` rather than reading the path directly, or you will
report "no file" for a screenshot that exists.

Read every image in the folder. Two screenshots of two different pages is more
useful than one, because the same defect usually appears on both.

## Rules for this front end

- **A chart that cannot load says so.** Never a blank rectangle. A blank
  rectangle in a demonstration reads as a design choice.
- **Never hardcode a colour in JavaScript.** Read the CSS custom property. The
  browse-view series chart did hardcode a palette and was the one chart that
  could drift from the other nine.
- **Do not PowerShell-round-trip a UTF-8 file.** `Get-Content` plus
  `Set-Content -Encoding UTF8` double-encodes every non-ASCII character and
  adds a BOM. It destroyed `dashboard/app.py` once. Use the `edit` tool, or
  write a Python script with `Path.write_text(..., encoding="utf-8")`. There is
  a test for the damage, and it caught the case only because it existed.