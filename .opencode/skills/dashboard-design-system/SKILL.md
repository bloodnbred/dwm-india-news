---
name: Dashboard Design System
description: The visual tokens, primitives and theme rules for the dashboard. Use when adding a component, choosing a colour, adjusting spacing or type, or deciding how something should look in light and dark mode. Tokens live in dashboard/static/app.css.
---

# Dashboard design system

## The one failure this system exists to prevent

The previous dashboard set a light page background in CSS while Streamlit
rendered its own widgets with the operating system's theme. On a machine set to
dark mode that produced **a light page with dark widgets over it** — black radio
dots, black code blocks, a black chart, on white. It read as broken, and it
could not be fixed from outside the framework, because a CSS-injection layer
cannot know what the framework will paint next.

Two rules follow, and they are not negotiable:

1. **The theme is chosen before first paint.** A small script in `<head>` reads
   `localStorage`, falls back to `prefers-color-scheme`, and writes
   `document.documentElement.dataset.theme`. Any later, and the page paints once
   in the wrong theme — which reads as a flash, and a flash reads as broken.
2. **Every colour resolves from `[data-theme]`.** There is no "it looks fine in
   light". Both palettes are designed as complete sets.

## Two palettes, not one plus overrides

A dark theme derived by inverting a light one always ends up with a contrast
failure somewhere. These were picked as sets and every text pair is asserted at
WCAG AA by `tests/test_ui.py`.

Note the text colours are **darker than the pure brand hues**. `#0071E3` is the
brand blue; `#0062C4` is what text uses, because `#0071E3` on a tinted
background measures 4.15:1 and fails. Graphics can be brighter than text; text
cannot. The same applies to green (`#157F3C`, not `#1B8E45`) and amber
(`#9A6200`, not `#FF9F0A`).

## Tokens

Everything lives in `dashboard/static/app.css`. Add tokens there, never inline.

**Surface** `--canvas` page, `--surface` card, `--surface-2` recessed, `--surface-sunk` inset.
**Text** `--ink` primary, `--muted` secondary, `--faint` labels and axis text only.
**Line** `--hairline` the default border, `--hairline-firm` the emphasised one, `--grid` chart gridlines, `--axis` axis ticks.
**Accent** `--accent` plus `--accent-soft` for its background, and the same pair for `--positive`, `--caution` and `--negative`.
**Shadow** `--shadow-sm` cards at rest, `--shadow-md` on hover, `--shadow-lg` only for the toast.

Radius: `--r-sm` 8, `--r-md` 12, `--r-lg` 18, `--r-xl` 24. Measure: `--nav-w`
250, `--measure` 1120.

## Components

Use these rather than inventing markup. They are what make six charts and
twelve tables read as one page.

| Class | For |
|---|---|
| `.card` | a bordered surface. `--pad-lg` for breathing room, `--flush` when it wraps a table |
| `.kpi` / `.kpi--accent\|positive\|caution\|muted` | one figure. Never more than four in a row |
| `.answer` | the answer to a question. See the `dashboard-pages` skill |
| `.callout--caution` | what may not be claimed. Amber, and it interrupts on purpose |
| `.callout--evidence` | how we know. Recessed, muted, left rule only |
| `.callout--note` | neutral asides |
| `.chart` | a chart frame, with `.chart__head`, `.chart__body`, `.chart__cap` |
| `.badge--guard` | live status. Green when the gate passes, red when it does not |
| `.tablewrap` + `.tablescroll` + `table.data` | every table. Sticky header, tabular numerals |
| `.tabs` / `.tab.is-active` | section tabs. Underline, not boxes |
| `.pill-yes` / `.pill-no` | yes/no cells |

## Type scale

Driven by the element, not by a class. `h1` 1.32rem in the topbar, `h2` 1.22rem
for section heads, `.hero` for a page's opening statement.

The important one is `.answer__text`:
`clamp(1.5rem, 2.9vw, 2.35rem)` at weight 660. **The answer to a question is
the largest text on the page.** If a data panel is competing with it for
attention, the hierarchy is wrong.

Small text is `.kpi__label`, `.field__label`, `.callout__label`,
`.chart__title` — all ~0.68rem, weight 650, uppercase, letterspaced. That is the
label register. Numbers never use it.

## Spacing

The rhythm is roughly 14/16/20/22/26. Inside a card: 17–22px padding. Between
sections: 40px. `mt-1` … `mt-3` and `mb-1` / `mb-2` exist for the exceptions.

Do not add pixel values inline. If a gap is missing a token, the rhythm is
wrong, not the token.

## Desktop only

A 250px sidebar and a 1120px measure have no sensible narrow-screen answer, and
a half-built one is worse than none. Do not add media queries without asking.

`prefers-reduced-motion` is honoured. Keep it that way.

## Things not to do

- **No inline colours.** `style="color:#..."` in a template is a drift waiting
  to happen. Use a token, or a `kpi--` modifier.
- **No box-shadow as structure.** Shadows separate surfaces from the canvas.
  Borders do the rest. A page where everything has a shadow reads as 1998.
- **No more than one accent.** `--accent` is the only interactive colour.
  Positive, caution and negative carry meaning and are never decorative.
- **Do not put a caution in a footnote.** It sits with the number it qualifies,
  or it does not get read.