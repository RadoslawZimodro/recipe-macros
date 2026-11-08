# Fiutatu design system

Decisions from the Phase 0 survey (author's answers). Source of truth for all UI work.

## Direction
- **Warmth**: a warm, calm kitchen notebook. Quiet, airy, minimal, elegant.
- **Dark only** (no light theme, no theme toggle). Set `color-scheme: dark`.
- **Depth: borders only.** 1px hairlines, no shadows, no gradients, no decoration.
- **Density: loose.** Card padding 24px, section gaps 32-48px.
- **Signature**: macro figures (kcal, P/F/C) as large tabular numerals in Fraunces on
  quiet surfaces, always marked as an estimate (see AGENTS.md section 6).

## Domain / color world
Domain: recipe, pantry, staple, portion, macro, estimate, daily log, shelf.
Color world: parchment ink on charred wood, olive oil, sage leaf, clay, flour, cast iron.

## Tokens (CSS variables in `frontend/src/index.css`, exposed via Tailwind `@theme`)
All hue ~60-80 (warm), only lightness shifts between surfaces.

| Token | Value | Use |
|---|---|---|
| `--color-canvas` | `#14130f` | page background (cast iron) |
| `--color-surface` | `#1a1914` | cards, panels (+1 step) |
| `--color-raised` | `#211f19` | popovers, modals, hover rows (+2 steps) |
| `--color-inset` | `#100f0c` | inputs (darker than surroundings) |
| `--color-line` | `rgb(236 228 210 / 0.10)` | standard 1px border |
| `--color-line-soft` | `rgb(236 228 210 / 0.06)` | dividers |
| `--color-line-strong` | `rgb(236 228 210 / 0.20)` | emphasis, hovered cards/rows |
| `--color-control-border` | `rgb(236 228 210 / 0.38)` | borders of inputs, selects, secondary buttons only (WCAG 1.4.11, ~3:1) |
| `--color-ink` | `#ece4d2` | primary text (flour) |
| `--color-ink-2` | `#bdb5a3` | secondary text |
| `--color-ink-3` | `#948c7b` | tertiary / metadata (AA on canvas, verify) |
| `--color-ink-4` | `#6f6859` | disabled only (not for readable text) |
| `--color-accent` | `#9fb58a` | the single accent (sage); links, primary action, focus |
| `--color-accent-strong` | `#b4c9a0` | accent hover |
| `--color-on-accent` | `#14130f` | text on accent fill |
| `--color-danger` | `#d98a7a` | errors (desaturated clay) |
| `--color-warning` | `#d6b46a` | estimates / caution (olive oil) |

Rules: no hex/rgb/px-color literals and no Tailwind palette colors (`gray-*`, `green-*`...) in
components; only the tokens above. Every text/background pair must meet WCAG AA (4.5:1,
3:1 for large text and UI borders that carry meaning). Verify with a contrast script.

## Typography
- Headings and macro numerals: **Fraunces** (variable, self-hosted via `@fontsource-variable/fraunces`).
- UI and body: **Inter** (variable, `@fontsource-variable/inter`). `tabular-nums` on all numbers.
- Fonts are self-hosted (no Google Fonts requests; privacy + offline in Docker).
- Scale (ratio 1.25, base 15/16): caption 12 · small 13 · body 15 · h4 17 · h3 20 · h2 25 · h1 31 · display 39.
- Hierarchy through weight + color first: 600 ink / 500 ink-2 / 400 ink-3. Line-height 1.5 body, 1.2 headings.
  Headings letter-spacing -0.01em; `text-wrap: balance` on headings, `pretty` on body.

## Spacing, radius, motion
- Base unit **4px**; use the multiples 4 8 12 16 24 32 48 64 96 only.
- Radius: `--radius-sm` 6px (inputs, buttons, chips) · `--radius-md` 10px (cards) · `--radius-lg` 16px (modals). Nested: outer = inner + padding.
- Motion: 150ms (hover/press) and 200ms (overlays, entrances), `cubic-bezier(0.23, 1, 0.32, 1)`;
  only `opacity`, `transform`, `color`, `background-color`, `border-color`; never `transition: all`.
  `@media (prefers-reduced-motion: reduce)` removes transforms and keeps color/opacity only.
- Press: `scale(0.98)` on `:active`. Focus: 2px accent ring with 2px offset on every interactive element, `:focus-visible` only.
- Hit area at least 40px.

## Banned
Gradients, box-shadows, glow, colored borders for decoration, more than one accent hue,
emoji as icons, raw palette colors, hard-coded px/hex in components, `transition: all`,
borders stronger than `--color-line-strong` outside form controls, nested cards, centered-everything layouts.

## Base components (one file each in `frontend/src/components/ui/`)
Button (primary / secondary / ghost / danger; 40px h, 0 16px pad, radius-sm, 15/500),
Input + Select + Field, Card, Table, Chip, Modal (native `<dialog>`), Nav, EmptyState, Spinner/Skeleton, ErrorMessage.
Patterns get recorded here with measurements once they exist.

## Assumed (conventional, not asked)
Icons: simple inline SVG line icons, 1.5px stroke, no icon library. Max content width 1120px (reading width 680px).
Mobile-first, breakpoints Tailwind defaults. Chart (Recharts) uses accent + ink-3 only, no legend colors beyond those.
Untouched: logic, API calls, routes, texts of messages (Polish copy stays), tests (only selectors that break from markup changes).

## Decisions after audit (author-approved)
- Control borders use `--color-control-border`; structural hairlines stay at `--color-line`.
- Home page gets link shortcuts to the main views (navigation only, no new logic or data).
- Recipe deletion confirmation moves from inline "Na pewno?" to a native `<dialog>` Modal (tests updated deliberately).
- Fonts `@fontsource-variable/fraunces` and `@fontsource-variable/inter` approved as dependencies.
