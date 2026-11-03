# The UI revamp: how each effect works

Same pages, same features, same buttons in the same places. What changed is the look, applied
evenly to every page through the shared theme and layout. Everything is HTML, CSS and plain Vue:
no new package, no animation library in the layout, and no WebGL.

| Effect                          | Where it lives                                                          |
| ------------------------------- | ----------------------------------------------------------------------- |
| Living background               | `components/layout/LivingBackground.vue`, colours in `theme.css`        |
| Panels that glow near the mouse | `composables/usePointerGlow.ts`, `lib/pointer-glow.ts`, `theme.css`     |
| Light round the main buttons    | `theme.css` (`.btn-primary`, `.sl-cta`)                                 |
| Outline buttons that fill       | `theme.css` (`.btn-outline-primary`, `.btn-outline-secondary`)          |
| Liquid glass menu bubble        | `components/ui/MainNav.vue`, `lib/nav-bubble.ts`                        |
| Care+ cursors and their switch  | `public/cursors/*.svg`, `theme.css` ("Cursors"), `useDisplay.ts`        |
| Heading font                    | `public/fonts/bricolage-grotesque-latin-wght-normal.woff2`, `theme.css` |

## Living background

One fixed layer behind every page (`position: fixed; z-index: -1`), rendered once in
`AppLayout.vue`, so all pages share it.

- **Glows**: each is a `div` with `background: radial-gradient(closest-side, colour, transparent)`.
  The gradient already fades to nothing, so no `filter: blur()` is needed (blur on large moving
  elements is slow).
- **Drift**: `@keyframes` move and scale each glow over 26 to 34 seconds, `alternate`, so they
  sway back and forth.
- **Follows the mouse**: `usePointerGlow` writes the mouse position into CSS variables (`--sl-mx`,
  `--sl-my`). The trailing glow uses them in `transform: translate(...)`, and a 1.1s `transition`
  makes it lag behind, so it feels soft.
- **Lean (parallax)**: the same composable writes `--sl-lean-x/y` (-1 to 1). Two layers move a
  few pixels by it, in opposite directions, which gives depth.
- **Vignette**: a `radial-gradient` that darkens the edges.
- **Grain**: an inline SVG `<feTurbulence>` noise filter at low opacity, `mix-blend-mode: overlay`.
- **Light and dark**: the colours are tokens (`--sl-bg-main`, `--sl-bg-bright`, ...). Dark mode
  redefines them under `:root[data-bs-theme='dark']`, so one component serves both.

## Panels that glow near the mouse

- One `pointermove` listener for the whole app (`usePointerGlow.ts`). It runs at most once per
  screen refresh (`requestAnimationFrame`), reads every panel's position first
  (`getBoundingClientRect`), then writes, so the page is laid out once per frame.
- For each panel within 160px of the mouse (`isNear` in `lib/pointer-glow.ts`), it sets `--sl-x`,
  `--sl-y` (the mouse inside that panel) and `--sl-glow-on: 1`.
- In CSS, `.sl-panel::after` is a `radial-gradient` centred on `--sl-x/--sl-y`, cut down to a thin
  ring with `mask` (the same trick as a gradient border). A faint wash of the same colour lights
  the inside. The colour follows the panel's tone (`sl-tone-coral` glows coral, for example).
- Touch is skipped (no hover on a finger). The maths is unit tested in `pointer-glow.test.ts`.

## Buttons

- **Main buttons** (`.btn-primary`): a `::before` ring with a `conic-gradient` (white, then sun),
  masked to the 2px border. `@property --sl-spin` registers the angle as an `<angle>`, so
  `@keyframes` can animate it smoothly (an ordinary custom property would jump). At rest the light
  waits in one place (`animation-play-state: paused`); hover or keyboard focus sets it running.
  The page's single main action has `sl-cta` and keeps it running.
- **Outline buttons**: a `radial-gradient` circle grows from beside the first word.
  `@property --sl-fill` animates its size from 0% to 100%. The words change colour 0.08s later,
  once the fill has reached them.

## Liquid glass menu bubble

- The bubble is the existing `.mainnav-indicator`, now glass with a rainbow rim (a
  `conic-gradient` ring masked to the edge, plus a blurred copy behind it).
- On the wide-screen pill, `@pointerenter` and `@focus` on a link call `moveTo(link, true)`. It
  reads the link's `offsetLeft` and `offsetWidth`, first stretches the bubble over both the old
  and the new link (`stretchSpan` in `lib/nav-bubble.ts`, slightly squashed), then 170ms later
  shrinks it onto the new link. The springy `cubic-bezier` overshoots a little, so it wobbles
  into place.
- Leaving the menu (mouse out, or focus moving off it) sends the bubble back to the current page.
- With reduced motion it jumps straight there, with no stretch and no transition.

## Care+ cursors

- 13 small SVG pictures in `public/cursors/`.
- `theme.css` defines one variable per kind of cursor (`--sl-cur-press`, `--sl-cur-text`,
  `--sl-cur-grab`, ...). Each is a normal keyword (`pointer`, `text`, `grab`) until
  `html.sl-cursors` is set and the device has a mouse or trackpad (`@media (pointer: fine)`). Then
  it becomes `url('/cursors/hand.svg') 13 2, pointer`: the picture, the point that clicks, and the
  keyword to fall back on.
- Elements just use `cursor: var(--sl-cur-…)`: links show the book, buttons the hand, text boxes
  the I-beam, tick boxes the tick, the "Add" buttons the plus. Dragging a calendar visit or Kaki
  shows the open hand, then the closed hand while dragging. The availability painter shows a
  green brush for Free and a grey one for Busy. A won medal shows the spin arrows, and something
  that cannot be pressed yet shows the "not yet" sign.
- The pointer button in Display settings switches them off (`careplus.cursors.v1` in this
  browser). On a phone the button is hidden, because there is no cursor.

## Accessibility kept

- Text sits on near-solid panels (84% opaque), so contrast is as before (WCAG AA).
- With reduced motion turned on, nothing drifts, leans, follows, spins or stretches.
- Keyboard focus gets the same effects as the mouse (the bubble, the button light, the fill).
- The background is `aria-hidden`, ignores clicks (`pointer-events: none`) and is not printed.
