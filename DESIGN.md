# StudBud Design System

Recorded from the implemented Next.js interface. Source of truth: `frontend/web/src/app/globals.css`.

## World

Blueprint: a technical drawing for study material. Pale grid ground, navy ink, cobalt action, monospace metadata. Operate surface: the diagram vocabulary supports scanning, provenance, and verification; it never turns a working screen into a drafting artifact.

## Color

| Role | Light | Dark |
|---|---|---|
| Background | `#eef2f7` | `#07111f` |
| Surface | `#ffffff` | `#0c1929` |
| Surface 2 | `#e6ecf4` | `#122235` |
| Ink | `#0a1a2b` | `#eaf1fa` |
| Soft | `#2d4258` | `#c3d0e0` |
| Muted | `#52657a` | `#93a5ba` |
| Line | `#c9d4e1` | `#22344b` |
| Accent | `#2456e6` | `#6f9bff` |
| Accent soft | `#e3eaff` | `#14294a` |
| Danger | `#b3261e` | `#ff8a80` |
| Warning | `#8a5a12` | `#e2b86a` |

The page ground carries a 32px construction grid at 5.5% ink, 4.5% white in dark. Surfaces are opaque cards for form panels, states, sources, and figure cards; the page itself stays gridded and open. Selection is solid cobalt with contrasting text. Browser scrollbars, caret, focus rings, and underline offsets are themed.

## Typography

- Display and body: Manrope, loaded through `next/font`. Headings 700–800, tracking `-0.03em` to `-0.05em`, balanced wrapping. Page h1 clamps 32–48px; sign-in h1 clamps 45–80px.
- Metadata, labels, buttons, status, page references: JetBrains Mono, 9–12px, uppercase, letter-spacing `0.04em`–`0.08em`.
- Body prose 17px / 1.72; measure 65–75ch.
- Tabular numerals for pages, counts, dates, and sizes.

## Layout

- Content max 1160px; 32–40px desktop gutters; 16px phone gutters.
- Top bar 72px, sticky, opaque surface, single hairline bottom border. Mobile moves search to a second row.
- Explanation: `1fr` prose + 280–340px source rail; stacked below 960px.
- Library and result rows are ruled lists with numbered coordinates, not cards. Cards are reserved for form panels, states, sources, and figures.
- Phone verified at 390px; no horizontal scroll.

## Components

- Buttons: 42px height, 4px radius, mono uppercase labels, cobalt primary, bordered ghost, quiet text action. Disabled at 45% opacity.
- Inputs: 44px, 1px strong border, 3px accent-soft focus ring; search input uses mono type.
- Status: squared mono pill with a state dot. Ready is solid cobalt; indexing is outlined cobalt with a pulse; failed red; needs OCR amber.
- Document rows: numbered `01`, file chip, name, mono meta, status, actions. Rows hover on surface tone.
- Result rows: index, document name left, section heading and snippet right, page coordinate in cobalt, chevron.
- Sources: 2px accent top rule, page-preview card, citation list, model note.
- Figures: extracted images in bordered cards with a cobalt `FIG. NN · PAGE NN` label and optional caption.
- Loading uses skeletons. Empty states teach the next action.
- Icons are authored inline SVG, 1.75 stroke, 20px grid.

## Theme

Light is the default on first visit. A moon/sun button in every header toggles light/dark and stores the choice in `localStorage` under `studbud-theme`. An inline script applies the stored theme before paint. Both themes use the same component tokens; no component is styled inside a media query.

## Motion

- 160ms ease-out for hover, border, color, and background changes; 120–250ms for state feedback.
- Two ambient moments only: indexing pulse and skeleton shimmer. Reduced-motion disables all of it.
- No page-load choreography; the app loads into the task.

## Accessibility

- WCAG AA contrast in both themes.
- Visible 2px focus ring with 2px offset.
- Keyboard operation for search, upload, result rows, citations, figure links, PDF navigation, and theme toggle.
- Every icon-only button has an accessible name.
- Semantic landmarks, one h1 per page, labels on all controls.
