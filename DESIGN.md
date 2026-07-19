# Visual Design

**Scope: looks, not structure.** Where `UI_STRUCTURE.md` fixes *what regions
exist and what drives what*, this fixes *how they look* — palette, semantic
roles, light/dark, and the rules that keep it consistent. Read it alongside
`UI_STRUCTURE.md`; nothing here changes the structure or the state machine.

The **anchor is set** (it was the blocker for everything below): a neutral base
with a single amber accent. Two prior attempts failed because they were invented
without one — this one is chosen, so build against it rather than reopening it.

---

## The palette

Five colours. The whole scheme is **mostly neutral, one accent** — the accent
is what the eye is drawn to, so it is spent only on the primary action and the
active row, never sprayed around.

| Hex | Name | Role |
|---|---|---|
| `#000000` | black | strongest text / emphasis; deepest dark chrome |
| `#14213d` | oxford navy | primary text on light; base surface on dark |
| `#fca311` | amber | **the accent** — primary action, selection, focus |
| `#e5e5e5` | platinum | dividers/borders on light; muted surfaces |
| `#ffffff` | white | base surface on light; primary text on dark |

**Why neutral + accent, not the blue ramp:** this app's ethos is *never confuse
the safe action with the irreversible one*, and its diff leans on four
distinguishable badges. A monochrome ramp has no contrasting hue for caution and
collapses the badges into one colour. A neutral base keeps the diff content
calm and readable; the one accent gives an unambiguous "do this" signal.

**Derived values are allowed, within the family.** A palette gives anchors, not
every pixel value — hover/pressed states, muted text, and one level of dark
elevation are derived as tints/shades or alpha of the five, and are named below
so they stay consistent rather than ad-hoc.

---

## Tokens

Both themes ship; the viewer's OS setting picks one. `#14213d`/`#000` and
`#fff`/`#e5e5e5` are literally the two ends of the palette, so neither theme is
an afterthought.

### Light (default)

| Token | Value |
|---|---|
| `bg` (content) | `#ffffff` |
| `bg-chrome` (top/bottom bar, sidebar) | `#e5e5e5` |
| `surface-alt` (rows, cards) | `#ffffff` / `#f4f4f4` (derived) |
| `text` | `#14213d` |
| `text-strong` | `#000000` |
| `text-muted` | `rgba(20,33,61,0.55)` (derived) |
| `border` | `#e5e5e5` |
| `accent` | `#fca311` |
| `accent-hover` | `#e8940c` (derived) |
| `accent-pressed` | `#cc7f08` (derived) |
| `on-accent` | `#14213d` |

### Dark

| Token | Value |
|---|---|
| `bg` (content) | `#14213d` |
| `bg-chrome` | `#0d1526` (derived) / `#000000` |
| `surface-alt` (elevation) | `#1c2b4a` (derived) |
| `text` | `#e5e5e5` |
| `text-strong` | `#ffffff` |
| `text-muted` | `rgba(229,229,229,0.60)` (derived) |
| `border` | `rgba(229,229,229,0.14)` (derived) |
| `accent` | `#fca311` |
| `accent-hover` | `#ffb733` (derived) |
| `accent-pressed` | `#e8940c` (derived) |
| `on-accent` | `#14213d` |

---

## Button roles

The bottom-bar decision from `UI_STRUCTURE.md`, expressed in colour. Organize
and Keep are the two affirmative actions and are never enabled at once (Preview
vs Review), so amber consistently means *the primary action right now*; the safe
alternative is a neutral ghost; the irreversible one is gated by its confirm
dialog, not by a second hue.

| Button | Fill | Text | Signal |
|---|---|---|---|
| **Organize** (primary) | `accent` amber | `on-accent` | the one thing to do in Preview |
| **Keep Organized** (irreversible) | `accent` amber | `on-accent` | primary in Review — **+ confirm dialog** names what's deleted |
| **Restore Original** (safe) | transparent, `border` outline | `text` | recedes; the safe way out |
| **disabled** (any) | `border`/muted | `text-muted` | inert, legality-visible |

This maps directly onto the `role` property already wired in `main_window.py`
(`affirmative` / `caution` / `quiet`) — the placeholder greybox colours get
replaced by these; the hooks stay.

---

## Rule-layer badges

Four categories, made distinguishable by **hue + fill vs outline**, with a
hierarchy that reads at a glance — a pane full of grey `E` badges instantly says
"no rules are firing", which is the diagnostic they exist for.

| Badge | Layer | Style |
|---|---|---|
| `C` | custom (your rules) | amber fill, `on-accent` text — *your* rule, the eye-draw |
| `P` | pattern (built-in) | navy fill, light text — a built-in structural rule |
| `M` | metadata (built-in) | navy **outline**, navy text — built-in, distinct by outline |
| `E` | extension fallback | `text-muted` on `border` — deliberately quiet |

---

## Diff, selection, focus

- **Panes stay neutral.** Surfaces are `bg`/`surface-alt`; the accent never fills
  a pane, only marks what's active. Two peers, equal width (`UI_STRUCTURE.md`).
- **Linked selection is amber.** The selected row *and its twin* take a 3px amber
  left-border plus a faint amber tint (`rgba(252,163,17,0.12)`) — this is what
  makes the twin relationship visible.
- **Keyboard focus is a 2px amber outline** on every interactive control — on
  brand and a first-class accessibility requirement, not an afterthought.
- **Collision/conflict rows** (a 2D task): there is no red in the palette, so
  emphasis is a stronger amber outline/tint, not a new hue.

---

## Contrast & hard rules

Checked against WCAG AA; the palette makes most pairings easy, with one trap.

- ✅ `#14213d` on `#ffffff` (~14:1), `#e5e5e5` on `#14213d` (~11:1) — body text.
- ✅ `#fca311` on `#14213d` (~6.9:1), `#14213d` on `#fca311` (~6.3:1) — accent UI.
- ⛔ **Never white text on amber** (`#fff` on `#fca311` ≈ 1.9:1). Text on amber is
  always `on-accent` navy (or `#000` where extra weight is wanted).
- Amber is a **fill/border/large-element** colour; it is not used for small body
  text on a light surface.

---

## Technical constraints (unchanged)

- **PySide6 on Windows, styled with QSS** — a limited CSS subset: no flexbox/grid,
  no transitions. Layout is Qt layouts; motion is code-driven
  (`QPropertyAnimation` / `QGraphicsOpacityEffect`), and must respect OS
  **reduced-motion**.
- Tokens should live in **one place** (a QSS template with the values above,
  swapped by theme) rather than scattered literals, so the accent is changed once.
- The `gui/` modules are a working **greybox** (unstyled but structurally
  complete) — styling layers onto them; it does not rebuild them.
