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
| Scrolling landing page          | `components/landing/LandingStory.vue`, `lib/landing-scroll.ts`          |
| Morning summary                 | `components/home/MorningSummary.vue`, `lib/morning-summary.ts`          |
| Home on a phone                 | `views/HomeView.vue`, `components/home/ActivityFeed.vue`                |

## Living background

One fixed layer behind every page (`position: fixed; z-index: -1`), rendered once in
`AppLayout.vue`, so all pages share it.

- **Glows**: each is a `div` with `background: radial-gradient(closest-side, colour, transparent)`.
  The gradient already fades to nothing, so no `filter: blur()` is needed (blur on large moving
  elements is slow).
- **Drift**: `@keyframes` move and scale each glow over 26 to 34 seconds, `alternate`, so they
  sway back and forth four times (about two minutes) and then rest, rather than moving forever.
- **Follows the mouse**: `usePointerGlow` writes the mouse position into CSS variables (`--sl-mx`,
  `--sl-my`). The trailing glow uses them in `transform: translate(...)`, and a 1.1s `transition`
  makes it lag behind, so it feels soft.
- **Lean (parallax)**: the same composable writes `--sl-lean-x/y` (-1 to 1). Two layers move a
  few pixels by it, in opposite directions, which gives depth.
- **Vignette**: a `radial-gradient` that darkens the edges.
- **Grain**: an inline SVG `<feTurbulence>` noise filter at low opacity (no blend mode, which
  would make the browser repaint the whole page on every frame).
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
  The page's single main action has `sl-cta`: its light goes round three times when the page
  opens, then waits like the others.
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

## Scrolling landing page (`/login`)

`LoginChooserView.vue` now shows `components/landing/LandingStory.vue` above the family / senior
choice. It is plain CSS and one scroll listener: no animation library (the sign-in screens may not
use `motion-v` or `@vueuse`).

- **Pinning**: each scene is a tall `<section>` (3.4 and 5.2 screens tall) holding a
  `position: sticky` stage one screen high. While you scroll through the tall section, the stage
  stays put, so scrolling plays the scene instead of moving the page.
- **Progress**: the `scroll` listener (once a frame with `requestAnimationFrame`) works out how far
  through each section you are (0 to 1, `sectionProgress` in `lib/landing-scroll.ts`) and writes it
  to the CSS variables `--p` and `--g`. Everything else is CSS: `calc()` on those variables drives
  `transform`, `opacity` and `filter: blur()`.
- **Scene 1**: the headline blurs away as a card grows to fill the screen. Inside it a phone shows
  the step ring filling and the number counting up (`countUp`), beside "CARE+".
- **Scene 2**: six real screenshots of the app (`public/landing/*.jpg`) slide past one at a time.
  `holdThenMove` keeps each screenshot still for the first half of its share of the scroll, then
  eases to the next, so every screen stays long enough to read. A counter ("2 / 6") and bar show
  where you are.
- **The end**: the last scene finishes exactly where the sign-in section (`#sign-in` in
  `LoginChooserView.vue`) starts. That section is a full screen tall (`min-height: 100dvh`) and
  runs up behind the see-through header, so arriving there shows one background colour with the
  choices in the middle, never a strip of the dark story. "Get started" jumps straight there, and
  a gentle snap (`scroll-snap-type: y proximity` on this page only, `scroll-snap-align: start`)
  settles the page there if you stop scrolling just short of it. No snap with reduced motion.
- **Stacked and still** (the `.still` class): the pinning is dropped and the scenes become a
  normal page read from top to bottom. This happens with reduced motion, and also when the screen
  is too short for a pinned scene to fit (under 600px high once Care+'s text size is counted: a
  phone turned sideways, or a big zoom), so nothing is ever cut off. `decide()` checks again on
  resize, on a zoom change and when the reduced-motion setting changes.
- The band is full width (`width: 100vw` with a negative margin). `100vw` includes the scroll bar,
  so on this page only, `:global(.shell:has(.landing)) { overflow-x: clip }` cuts off those few
  pixels instead of scrolling sideways (`clip`, unlike `hidden`, does not break
  `position: sticky`).

## Morning summary (Home)

A pop-up the first time a family member opens Home each day.

- **What it says** comes from `buildSummary` in `lib/morning-summary.ts` (pure function, unit
  tested): the latest day's steps against a usual day, a short note, and up to four things for
  today (today's visits and who is going, open tasks, visits in the next three days that still need
  a helper, and the watch battery if it is low).
- **The note** is not worked out on the page. It comes from the API's own decision for the senior
  (`attention_band`, the last decision, and whether sharing is on), mapped by `verdictOf` to one of
  "All's good.", "Keep an eye on it.", "Keep monitoring." or "Sharing is paused." It describes
  activity only, never health.
- **A day that can't be read**: when the watch was not worn long enough, the API's policy says
  "stable, no action" because it will not judge that day (`signal.quality.safe_to_interpret` is
  false). The summary then says "Not enough watch wear to compare." and shows no percentage,
  rather than "All's good".
- **The pop-up** (`components/home/MorningSummary.vue`) is a native `<dialog>` opened with
  `showModal()`. The browser keeps keyboard focus inside it, closes it with Escape, and dims the
  page behind it (`::backdrop`). Focus starts on the title (`tabindex="-1"` and `autofocus`), so a long summary opens at
  its top. Clicking outside closes it (only when the press started outside too, so selecting text
  and letting go outside does not).
- **Once a day**: `localStorage` key `careplus.morning.v1` stores the day it was shown for each
  senior, as JSON (`{"mdm-lim":"2026-11-04"}`), so it does not show again that day for that senior,
  even after switching to another senior and back. "Show this each morning" off stores `off`.
  The "Today's summary" button on Home opens it at any time.
- The browser tests start with it switched off (`e2e/playwright.config.ts`), so it does not cover
  the page in other tests; `e2e/tests/morning-summary.spec.ts` turns it on and tests it.

## Home on a phone

Below 768px wide (`matchMedia('(max-width: 767.98px)')` in `HomeView.vue`):

- **Today's tasks** come first, above the family updates. There is still only one Tasks panel:
  `<Teleport defer to="#home-tasks-spot" :disabled="!isPhone">` moves it up on a phone and leaves
  it in its usual place on wider screens. Moving (rather than drawing a second copy) keeps it
  alive, so a half-typed task survives turning the phone sideways.
- **Family updates** start folded: one line with the latest update and a "Show all (n)" button
  once there is more than one update (`ActivityFeed.vue`, `collapsible` prop). The button has `aria-expanded` and `aria-controls`, and
  the list is hidden with `v-show`.
- **The week ahead** is replaced by a single "The week ahead" link (with the number of visits and
  an arrow) that opens the calendar.
- Desktop and tablet are unchanged.

## Accessibility kept

- Text sits on near-solid panels (84% opaque), so contrast is as before (WCAG AA).
- With reduced motion turned on, nothing drifts, leans, follows, spins or stretches.
- Keyboard focus gets the same effects as the mouse (the bubble, the button light, the fill).
- The background is `aria-hidden`, ignores clicks (`pointer-events: none`) and is not printed.
