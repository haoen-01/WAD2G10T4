# Walking badges

Small rewards for walking, on the senior's own page (the **Badges** tab) and, to cheer her on, on
the family's **Walk** page. Encouragement only: badges never feed a decision, `policy.py` never sees
them, and missing a goal costs nothing.

## Where the numbers come from

- **Daily steps**: `GET /v1/people/{id}/metrics?days=90` through `services/careApi.ts`, the same
  readings Home shows. Nothing new is asked of the API and nothing is written to it.
- **Finished walks**: a walk finished on the Walk page **while she shares her walk** (the demo watch,
  `composables/useWalk.ts`), credited to that senior. Only the part she shared counts, and the
  time recorded is the real time it finished. What she did not share is never recorded.

The rules are pure functions in `client/src/lib/badges.ts`, tested in `badges.test.ts`.

| Group     | Badge                                   | How it is earned                                           |
| --------- | --------------------------------------- | ---------------------------------------------------------- |
| Challenge | _Month_ Challenge                       | About 20 usual days' steps in a calendar month (see below) |
| One day   | First Steps                             | 1,000 steps in one day                                     |
| One day   | 3,000 / 5,000 / 8,000 / 10,000 Step Day | That many steps in one day                                 |
| Habit     | Steady Week                             | 5 walking days (2,000+ steps) in any 7 days, gaps allowed  |
| Habit     | Weekend Walker                          | A walking Saturday and the Sunday after                    |
| Habit     | Month of Walks                          | 20 walking days in any 30 days                             |
| Milestone | Marathon, Step by Step                  | 65,000 steps within 90 days (about 42 km at a 0.65 m step) |
| Milestone | 100,000 Steps                           | 100,000 steps within 90 days                               |
| Milestone | Quarter Million                         | 250,000 steps within 90 days                               |
| Milestone | Personal Best                           | Beat every earlier day, once there are 14 days to beat     |
| Walk      | Park Loop                               | Finish a shared walk of 2 km or more                       |
| Walk      | Regular Walker                          | Finish 3 shared walks of 1 km or more                      |

**Monthly challenge.** The goal is the median day over the 28 days before the month, times 20,
rounded to 5,000 (100,000 when there are fewer than 7 readings to go on). The latest month always
shows, won or in progress; an earlier month shows only if it was won. A missed month is never shown.

**Milestones are rolling.** The API returns at most 90 days, so a total is counted over the 90 days
ending on each day ("82,000 of 100,000 steps in the last 90 days"), never over a mix of seasons.

**No failure states.** There are no streaks to break. A badge once earned stays earned: each one is
remembered on the day it was first earned, so it stays when its days roll out of the 90 in view. A
goal not yet reached says how close she is ("Best day so far: 6,809 of 8,000 steps"). If the steps
cannot be read, only walk badges and badges already earned are shown.

## Claiming

Earned badges start grey with a gold rim and a **Claim** button (senior only; the family sees
"Earned, not claimed yet"). Claimed badges are in colour, with nothing boxed around them: on hover
the medal itself lifts out and turns slowly, showing the back engraved with who earned it, the day,
and the moment it was claimed. A sideways drag across a medal spins it by hand (on a phone too;
up and down still scrolls), and it lands face on when let go.

A tap or click shows the medal up close, the way Apple Fitness shows an award: it flies out of the
shelf onto a full-screen dark stage, turns once as it lands, and then it is hers to spin. There is
no card, only the medal, its name and one line ("You earned this for walking 5,000 steps in one
day, on Tue, 21 Jul 2026."). **Turn over** does what the drag does; **‹ Badges** (or Escape) sends
the medal back to its place on the shelf.

**The first look is celebrated.** The first time a claimed badge is opened up close, the whole
screen celebrates: confetti in the badge's colours bursts from both bottom corners and out of the
medal, then falls from the top; gold light turns slowly behind the medal, sparkles twinkle around
it, it lands with two turns, and "Congratulations!" (with "You earned a new badge", or "Mdm Lim
earned a new badge" for the family) shows above it. A phone gives a short buzz where it can. It
happens once for her and once for her family (`seen` in the store); after that the badge opens in
the calm view. Claiming a badge up close celebrates there and then. Screen readers hear
"Congratulations! You earned a new badge: …". The confetti never takes a tap, so the medal can be
spun through it; with reduced motion there is no confetti, turning light or buzz, only the heading
and a still glow.

Claims, first looks, remembered badges and finished walks are kept **in this browser only** (`localStorage`, key
`careplus.badges.v1`, per senior), like Tasks: they are encouragement, not care data. Two tabs open
at once join each other's saves rather than writing over them. Another device starts with nothing
claimed. If badges ever need to follow the senior between devices, the claims would
move into the API (a small table and two routes, via `models.py` and `pnpm client:generate`).

## Look and motion

Original enamel-pin designs drawn as SVG (`lib/badge-art.ts`, `components/badges/BadgeMedal.vue`):
a polished gold rim, enamel with the picture inlaid in gold wire, and a gloss. The 3D coin
(`BadgeCoin.vue`) is CSS 3D with a stacked gold edge. How it turns, coasts and settles is
`lib/coin-spin.ts` (tested), run each frame by `composables/useCoinSpin.ts`. Motion is CSS, the Web
Animations API, a `<canvas>` for the confetti (`lib/confetti.ts`, tested) and
`requestAnimationFrame` only (no `motion-v` on the senior screen). For reduced
motion nothing turns by itself, there is no flight, and a let-go medal lands on its face at once.
