# Audit G — Senior UX / accessibility

Worktree `/Users/ianpong/Projects/ismoggers-v2` @ 010aa96, read-only. Product run offline
(SQLite + fixture + LLM off) on API 8300 / web 3300, driven with Playwright (chromium from the
repo's `@playwright/test`) at 1280×900 desktop, 390×844 mobile (dpr 2, touch), the shell's own
`Largest` text step (22px root) and emulated 200 % text scaling (root 32px and 44px). axe-core
4.13 (wcag2a/aa/21aa/22aa/best-practice) was injected on every captured state.

Screenshots: `(scratch)/G-shots/`
(`A*`/`B*`/`C*`/`D*`/`E*`/`F*`/`G*` full-page, `M*`/`N*` element-level legible crops, `Z*` API
down). Scripts: `g-walk.cjs`, `g-walk2.cjs`, `g-walk3.cjs`, `g-walk4.cjs`, probes `g-probe*.cjs`;
machine output `G-shots/report-full.json`, `report-down.json`, `notes-walk2.json`, `notes-walk3.json`.
Servers were stopped and the worktree is unchanged (`git status` clean).

Ordering used in the shared brief: P0 correctness/safety, P1 high-value, P2 enhancement, P3 research.

---

## What is already good (keep it)

- Vocabulary guard holds on every rendered state. My regex sweep over `.senior-main` innerText
  (`stable|watch|review|escalat*|band|score|risk|baseline|\d+%|policy|evidence|deadline|attention|
median|confidence|percent`) matched nothing on all 59 states (`report-full.json:vocab`). No status
  words, deadlines or percentages reach the page.
- One prompt at a time (`senior-view.tsx:439-504`) actually holds: decline reason → follow-through →
  enjoyment → planned beats → context question → baseline → memory. Never two questions stacked.
- The follow-through/enjoyment prompts are genuinely neutral (`M27`, `M29`, `M30`): equal-weight
  buttons, "There is no right answer", "Nothing in particular" as the primary when nothing picked.
- "Yes, tell me more" leads to real, fixed, reviewed content with a stop note at body size and a
  boundary note (`M26`; `outreach_content.py:22-30`).
- The confirmation step before any search result (`M02`, `M10`, `M12`) exposes parser gaps in plain
  words ("I did not understand "walk, down"").
- Activity card facts are honest: "Not listed" for unknowns, "(from the listing)" on distances,
  "Not listed — worth ringing to check" for booking (`view-models.ts:1085-1105, 1335-1345`); "More
  details" gives address, transport, cost, language, access, phone (`M04`, `M82`).
- Contradictions are shown on both sides ("You've told us something different — what you said
  wins" / "This is what Care+ goes by", `N20`), and "Forget this" is offered regardless of source.
- Trust copy is consolidated (`SENIOR_TRUST_LINE`, `TrustNote`), footer carries the boundary at
  readable size, "Suggestions are off" state is calm and reversible (`M48`, `M68`).
- Text-size control works, applies before paint, scales buttons with type; measured secondary text
  AAA and control borders 3:1 (existing e2e). No horizontal overflow at 390px at Normal or Largest
  (`report-full.json:overflow` — only the ×200 emulations overflow, see G-12).
- Every interactive control inside `.senior-main` measured ≥ 44px tall at all sizes EXCEPT the Ask
  text field (G-2). Focus rings are the 3px green ring on every button/link/input/summary (`M83`,
  tab-order dumps in `report-full.json:tabOrder`). Tab order follows visual order.
- Double-tap protection via `busyRef` on every write.

---

## Findings

### G-1 (P1) A single failed tap replaces the whole home page with a developer error

**Evidence.** `M47-outcome-save-failed-viewport.png`: after "Maybe later" with one aborted
`POST /v1/interventions/*/outcome`, the greeting, suggestion, Ask, week and preferences all vanish and
the page shows "API unavailable / Failed to fetch / Start the FastAPI service on port 8000, then
retry." The same screen is the whole-page API-down state (`Z1-api-down-home-mobile.png`,
`Z3-api-down-privacy-mobile.png`), where it is also the only content, has no `h1` (axe
`page-has-heading-one`), no retry control (ErrorCallout only renders one when `onRetry` is passed and
`SeniorView` never passes it), and its text fails AA contrast (axe: `#ac453e` on `#f9ded9` = 4.48:1).
"port 8000" is also wrong on any other port.

**Root cause.** `senior-view.tsx:211-212` (`respond`) and `:431-432` (`optOut`) call
`setError(toViewError(caught))`, and `:528-537` returns `<ErrorCallout>` for the entire view whenever
`error` is set — the same branch as the initial-load failure at `:158`. `error-callout.tsx:86-101` is
coordinator copy ("Start the FastAPI service"); `api-error.ts:48-51` passes `Error.message` through
("Failed to fetch").

**Proposed design (S).**

- In `respond`/`optOut` catch, use the existing inline `message` channel:
  `setMessage({ text: 'We could not save that just now. Please try again in a moment.', ok: false })`
  — exactly what `addDeclineReason`, `submitFollowThrough` etc. already do (`:233-238`, `:257-260`).
  Reserve page-level `error` for the initial load only.
- Give `ErrorCallout` a `variant="senior"` (or a separate `SeniorUnavailable` component rendered
  from `senior-view.tsx:533`, `senior-privacy.tsx:82`, `senior-activities.tsx:41-49` already has
  its own) with: `<h1>Care+ is not available just now</h1>`, "Nothing has changed. Please try
  again in a moment, or ask at your community centre.", a "Try again" `Button size="lg"` calling the
  loader, text colour `text-foreground` on the soft red (or `text-destructive` at ≥ 18px semibold).
- Never render `caught.message` on the senior surface: in `toViewError` return a fixed sentence for
  `network` when the caller is a senior view, or strip it in `ErrorCallout` senior variant.

**Test.** e2e: route-abort `**/outcome`, click "Maybe later", expect `h1` still "One thing you might
like today.", expect the suggestion still visible, expect a `[role=status]` with the calm sentence,
expect no text matching `/FastAPI|port 8000|Failed to fetch/`. Same for API-down: assert `h1` exists
and a "Try again" button.

### G-2 (P1) The Ask Care+ text field is 27px tall on phones (44px floor broken on the primary input)

**Evidence.** `M01-ask-section.png`: the field is a thin pill with a clipped placeholder beneath a
52px "Ask" button. Measured: 27px at Normal, 37px at Largest (`report-full.json:targets` lists
`input "For example…" 358×27` on every mobile state; desktop 52px only because the row's
`align-items: stretch` matches the button). CDP `getMatchedStylesForNode` confirms `.h-13`
matches (`g-probe3.cjs`), so the height is being overridden by layout, not CSS.

**Root cause.** `ask-silverloop.tsx:244-256`: the form is `flex flex-col … sm:flex-row` and the
input carries `flex-1`. In a column flex container `flex-1` = `flex: 1 1 0%` makes the _height_ the
flex basis (0), so the input collapses to min-content and `h-13` is ignored below `sm`.

**Fix (S).** Replace `flex-1` with `sm:flex-1` and add `min-h-13` on the input
(`ask-silverloop.tsx:255`). Also `placeholder` is truncated at 390px ("…I can do wit"): shorten to
"For example: something nearby" or move the example into visible helper text.

**Test.** e2e at 390×844: `expect(boundingBox(getByLabel('What would you like to do?')).height)
.toBeGreaterThanOrEqual(44)` at Normal and Largest.

### G-3 (P1) "What Care+ knows about you" prints step counts, an anchor rationale, offered/took-up tallies and third-person prose

**Evidence.** `M63-what-knows.png`, `N21-knows-contradiction.png`:

- "A typical day lately is about 5,724 steps, usually within 276 or so of that."
- "When Care+ started, a typical day was about 5,747 steps -- kept as an anchor so a gradual
  change cannot quietly become the new normal."
- "Offered "Five-minute movement option" 4 time(s); took up and followed through on 2 of 4." /
  "passed on all 1"
- "Leans away from things close to home, picked up from what **they** said no to. **Their** own words
  say otherwise, and those win." on a page whose every other line says "you".
- "Wants to: spend more time with other people, 2 times a week."

This is the scoreboard the product's own comments forbid (`candidate-preferences.tsx:23-25`:
"rendering them turns their own preferences page into a record of how they have been performing";
`week-summary.ts:14-18`: "Step counts … are coordinator vocabulary"). The e2e guard
(`product-loop.spec.ts:16`, `/stable|watch|review|\d+%/`) cannot catch any of this because none of
it is a percentage.

**Root cause.** `what-silverloop-knows.tsx:48` renders `fact.statement` verbatim; the statements are
composed for the evaluator in `world_model.py:219-263` (steps/MAD), `:301-307` ("they/their"),
`:341` (goal with `target_per_week`), `:475-500` (`Offered … N time(s)`).

**Proposed design (M).** Keep `PersonWorldModel` as the evaluator contract. Add a senior projection
that never carries numbers: either
(a) a `senior_statement: str | None` field on `PersonFact` (Pydantic → regenerate SDK) filled by
`world_model.py` alongside `statement`, with the senior page rendering
`fact.senior_statement ?? null` and skipping facts that have none (routine steps → "Your usual amount
of getting about is settled and known."; reference → omit; learned_response counts → omit entirely;
goals → `goal.text` without the "N times a week" suffix; second person throughout), or
(b) a `?audience=senior` query on `GET /v1/people/{id}/world-model` returning only categories
`identity|activity_preference|interaction|context` with second-person text.
Either way replace `--` with `—` (or a full stop) in every senior-visible string
(`world_model.py:260,301-307`, gaps list, `activity_search.py:355,361,600,682`,
`sql_repository.py:5438`).

**Test.** `apps/api/tests`: for a seeded person, every `senior_statement` matches
`^(?!.*\b(\d{1,3}(,\d{3})+|\d+ steps|time\(s\)|of \d+|anchor|they|their)\b)`. e2e: privacy page
innerText has no `/\d[\d,]* steps|time\(s\)|of \d/`.

### G-4 (P1) Missing wearable data is presented as "Everything looks normal today."

**Evidence.** `M50-home-low_wear-viewport.png` after `low_wear`: h1 "Everything looks normal today.",
subline "There is nothing you need to do.", side card "Today has looked much the same as usual for
you." API state at that moment: `delta_percent 0.0, safe_to_interpret False, confidence 0.2625,
reasons ['Tracker wear-time was 2.1 hours; at least 8 hours is required.']` (curl in transcript).

**Root cause.** `week-summary.ts:20-47`: `describeRecentActivity`/`isTypicalDay` read only
`signal.delta_percent` and `sustained_low_days`; they never look at `signal.quality.safe_to_interpret`.
`senior-view.tsx:571-573` promotes that to the headline. This breaks the brief's "missing data never
becomes …" rule in the other direction: no data → "normal".

**Proposed design (S).** In `week-summary.ts` add a first branch:
`if (!state.signal.quality.safe_to_interpret) return 'Your wearable was not worn for long enough
today for Care+ to say anything about it.'` and make `isTypicalDay` return `false` in that case
so the headline falls back to "Nothing for you to do today." Same module, one source of truth as the
file's own comment asks. Optional: a `describeContext` line for `signal.context.rainy`
(`M51-how-things-look-rain_explains_decline.png` currently says "You have got about less than usual
today." with no mention of the rain the policy itself used to explain it — `policy` rationale "Rain
plausibly explains a single-day decline"). Add: "It rained today, which usually explains a quieter
day."

**Test.** unit for `describeRecentActivity`/`isTypicalDay` with `safe_to_interpret=false`; e2e:
after `low_wear`, `h1` is not "Everything looks normal today." and the side card mentions wear.

### G-5 (P1) "It sounds too tiring" on a gentle class teaches (and tells the person) "lean away from gentler activities"

**Evidence.** `M07-decline-learning-line.png` after "Not for me → It sounds too tiring" on
Chair Mobility & Balance (intensity light): "Care+ will lean away from gentler activities."
`M62-your-preferences.png`: "How active you like to be — Picked up from what you said no to —
Leaning away from gentler activities." At the same moment the client patches the _next_ search to
`intensity: 'light'` (`view-models.ts:1045-1046`), i.e. the UI narrows toward light while the API
learns to avoid light. The "too far" analogue is on the same screenshot: "Leaning away from
activities nearer home" after declining a 650 m listing as too far (`M62`, `N20`). Confirms the
lead's known flaws #1 and #2 and shows they are now _visible to the person_ as absurd sentences.

**Root cause.** `preferences.py:57-69` maps `TOO_TIRING → INTENSITY` and `apply_decline` moves the
candidate's _own_ level negative; `summarizeDeclineLearning` (`view-models.ts:1302-1305`) faithfully
narrates it. Distance is categorical near/far (`_candidate_dimension_value`).

**Proposed design (M, backend; owned by the learning audit, but the UI side is S).** Until the
learner is ordinal, the senior-facing sentence must not narrate a nonsensical update: in
`summarizeDeclineLearning` map `too_tiring` to "Care+ will look for gentler options next time."
and `too_far` to "Care+ will look for things closer to home next time." regardless of the
returned rows, and suppress the "Leaning away from gentler activities" card wording by rendering
intensity/distance declines as "Prefers something gentler than X" / "Prefers something nearer than
Y m" using the candidate that was declined (needs the candidate's value kept on the row —
`DimensionPreference.value` is already free text). Long term: ordinal dimensions (`intensity <=
light`, `max_distance_m <= 0.6 × declined`).

**Test.** API: `too_tiring` on a `light` candidate must not produce a negative `intensity=light`
row; UI unit: `summarizeDeclineLearning` never emits "lean away from gentler".

### G-6 (P1) Each visit with a pending prompt steals focus to a mid-page heading, with the browser's default blue outline

**Evidence.** `M20-home-suggestion-viewport.png`, `C1-home-suggestion-desktop.png`,
`M27-follow-through.png`, `N11-planned-follow-through.png`: on a fresh load the context question /
follow-through h2 has a blue 1px `outline: auto` and `document.activeElement` is that h2
(`g-probe2.cjs`: `active: "H2 Today looks quieter…", focusVisible: true, outline: "auto rgb(0, 95,
204) 1px"`). A screen-reader user therefore lands after the greeting and the `h1`
("Good afternoon… One thing you might like today. It is only a suggestion…") on every visit that has
a prompt, which is exactly the reassurance framing the page exists to deliver first.

**Root cause.** `use-auto-focus-heading.ts:24-36` guards only the _first render_, but the first render
of `SeniorView` is the loading skeleton (`senior-view.tsx:539`) with `activePromptKey === null`; the
fetch resolving is a key change, so focus moves. Headings have no `:focus-visible` style
(`styles.css:93-98` covers button/a/input/summary only), so the UA outline shows.

**Fix (S).** In `SeniorView` pass `state ? activePromptKey : null` _and_ seed the hook's `previous`
with the first non-null key after data arrives: simplest is to add a second argument
`useAutoFocusHeading(key, { enabled: hasLoadedOnce })` where `hasLoadedOnce` flips true in the
load `.then` and the hook records `previous = key` on the first enabled render without focusing.
Add `h1:focus-visible, h2:focus-visible, h3:focus-visible, p:focus-visible { outline: 3px solid
var(--sl-ring); outline-offset: 4px; border-radius: var(--sl-radius-sm) }` to `styles.css` next to
line 93 so intentional moves (after "Yes, tell me more", `senior-view.tsx:131-133`) look like the
product, not the browser.

**Test.** e2e: after `activity_declines`, `goto('/senior')`, `expect(page.evaluate(() =>
document.activeElement.tagName)).toBe('BODY')`; after clicking "Yes, tell me more", active element
is the `h1`.

### G-7 (P1) A chip tap returns 14 cards (~17,000px on a phone); the mandate says two or three

**Evidence.** `B2-ask-chip-results-mobile.png` (full page 18,268px at dpr 2 ≈ 9,100 CSS px),
`notes-walk3.json`: "nearby results cards: 14". The same activity appears up to three times (one
per session: `B3` heading dump shows "Chair Mobility & Balance" ×3, "Evening Tea & Chat" ×3). The
refinement chips and "Why some things are not shown" sit below all 14. A person scrolling past
fourteen near-identical cards has no way to tell which Care+ thinks suits them.

**Root cause.** `rank_candidates` (`activity_search.py:943`) returns the full ranked list; the
diversity step only reorders the top N (`:849-873`). `ask-silverloop.tsx:353-367` renders
`visibleResults` unbounded; the catalogue lists each recurring session as a separate candidate.

**Proposed design (S–M).** Client: show the top 3 (`visibleResults.slice(0, shown)`) with one
"Show a few more" `Button size="lg" variant="outline"` (increments by 3), and collapse repeated
sessions of one title into one card with "Also on Sat 22 Aug, Wed 26 Aug" under the clock line
(group by `candidate.title` + location, keep the earliest). API (optional): `results` capped at
`max_results` (default 6) with `has_more`. Keep `filtered_out` as is.

**Test.** e2e: "Somewhere nearby" → `expect(cards).toHaveCount(3)`; "Show a few more" → 6.

### G-8 (P2) Reasons on a card say the same thing twice (the double-counting made visible)

**Evidence.** `M03-result-card.png`: "You will be among other people, as you asked." + "With other
people -- you've said you enjoy the company." `N23-result-card-with-stated-pref.png`: "500 m away,
within the 1 km you asked for." + "Close to home -- you've preferred that before."

**Root cause.** `_intent_reasons` (`activity_search.py:397-435`) and `_preference_reasons`
(`:368-377`) each emit a line for the same axis; `_compose_reasons` orders by basis but does not
dedupe by axis. `activity-card.tsx:134-143` prints all three.

**Fix (S).** In `_compose_reasons` keep one line per axis (intent wins over preference; merge to
"With other people — as you asked, and you've said you enjoy the company."). Client fallback: dedupe
by a `reason.axis` field if added to `ActivityReason`.

**Test.** unit: a candidate matching intent+preference on `social` yields exactly one social reason.

### G-9 (P2) Decline-reason step on a search result: seven reasons, two of them about a nudge, and a skip that does not look tappable

**Evidence.** `M06-result-decline-reasons.png`, `M42-decline-reasons-largest.png`: "Just a bad day"
and "I am already getting about" are offered when declining a _search result the person asked for_
(they only make sense for a proactive nudge — the code says so, `view-models.ts:541-546`). The
escape "No thanks, I would rather not say" is `variant="ghost"` (`decline-reason-prompt.tsx:58-66`)
— plain text centred under seven bordered buttons, wrapping to "…rather not / say" at Largest. Same
affordance problem for "Not for me" on cards (`activity-card.tsx:268-278`), "Never mind"
(`day-dispute.tsx:128-136`), "No" on the memory prompt (`M23`), "Clear and skip" and "Forget this".

**Fix (S).** Split `SENIOR_DECLINE_REASONS` into `SENIOR_NUDGE_DECLINE_REASONS` (current seven) and
`SENIOR_ACTIVITY_DECLINE_REASONS` (`not_for_me, too_far, too_tiring, bad_timing,
prefer_something_else`), pass the list as a prop to `DeclineReasonPrompt`. Give every "quiet" choice
the `outline` variant (a border is the cue this audience reads; `styles.css` already makes borders
3:1 for this reason) and keep `ghost` for nothing on the senior surface. Shorten to "I'd rather not
say".

### G-10 (P2) Context question: the optional note sits _after_ the answers, but tapping an answer submits — most people will never get to write it

**Evidence.** `M21-context-question.png`: five full-width answer buttons, then "Anything you would
like to add? (optional)" with an empty field. Tab order (`report-full.json:tabOrder[C1]`): the five
buttons come before the input. The note is the only thing that can produce a proposed memory
(`context_question.py:127-156` needs "alone" in the note).

**Root cause.** `context-question-prompt.tsx:47-76`: options first, note second; `onAnswer` fires on
option click with whatever `note` holds.

**Fix (S).** Move the note above the answers with helper text "If you like, say a little more first",
or turn the answers into a two-step: choose → "Anything to add? (optional)" with "Send" / "Skip".
Also give the note field `min-h-13` (it is 52px already — fine) and `autocomplete="off"`.

**Test.** e2e: note is focusable before any option button in tab order.

### G-11 (P2) After "Not today" the offer stays on screen as an unanswered question

**Evidence.** `M44-suggestion-after-decline-largest.png`: the card still reads "Would you like a
gentle five-minute seated movement option today? It is completely optional." with no buttons, under
a status line that has since scrolled away. The code already recognises this hazard for
`no_response` (`senior-view.tsx:542-547`) but not for `declined`/`deferred`.

**Root cause.** `suggestion-card.tsx:42-72`: `showOffer = detailStatus === 'idle'` still true; only
`canRespond` hides the buttons.

**Fix (S).** When `suggestion.outcome` is `declined`/`deferred`/`activity_recovered`, render a short
past-tense line instead of the message: "You said not today. Nothing more will be asked about it." /
"You said maybe later. It will still be here tomorrow." (from a new `SENIOR_OUTCOME_RECAP` in
`view-models.ts`), and drop the sun icon's prominence (`text-muted-foreground`).

### G-12 (P2) At 200 % text scaling the brand, the h1 and the chips overflow the phone width

**Evidence.** `report-full.json:overflow`: `A5/C16` (Largest + 200 %: root 44px) `scrollW 572 > 390`,
offenders `a.senior-brand`, `h1`, `header.senior-prose`; `A6` (Normal + 200 %: root 32px) `scrollW
417`, offenders the four starter-chip buttons. `M45-largest-x200-viewport.png`, `M46-ask-chips-normal-
x200.png` show the clipping. The manual checklist lists "usable at 200 % browser zoom" as an unrun
human check (`docs/manual-ui-checklist.md`), so this is the first measurement.

**Root cause.** `styles.css:73` `h1 { max-width: 20ch }` plus `senior-main h1 { max-width: none }`
(:1631-1636) leaves long words unbroken; `.senior-brand` is a nowrap flex; Button base has
`shrink-0` + `inline-flex` (`button.tsx:14`) so a chip wider than its row overflows instead of
wrapping despite `whitespace-normal`.

**Fix (S).** `.senior-main h1, .senior-main h2 { overflow-wrap: anywhere }`; `.senior-brand
{ flex-wrap: wrap; min-width: 0 }`; add `max-w-full` to chip/answer buttons (or in
`buttonVariants` base: `max-w-full`). Re-run `A5/A6` overflow check.

**Test.** e2e: set `document.documentElement.style.fontSize = '32px'` and `'44px'` at 390px and
assert `scrollWidth <= clientWidth`.

### G-13 (P2) "That's right" on an inferred preference duplicates the card when the same stated row already exists

**Evidence.** `M65-pref-confirmed.png`: two identical "How far you like to go — You told us — "I do
not mind a bus ride"" cards, Next dev overlay "1 Issue", console: "Encountered two children with the
same key" (`notes-walk2.json`).

**Root cause.** `your-preferences.tsx:200-207` replaces the inferred row in place with
`result.preference` (now `source=senior_statement`) without removing the pre-existing
`senior_statement` row for the same `(dimension,value)`; both then share `preferenceKey`.

**Fix (S).** After a successful confirm, `filter` out every row with the same `dimensionValueKey`
and then append `updated` once. Better UX: merge the inferred and stated rows for one
`(dimension,value)` into a single card ("You told us … — Care+ had also noticed this") so the
duplicate-title cards in `M62`/`N20` disappear too.

**Test.** RTL/unit: confirm on `(distance, near, inferred)` with an existing `senior_statement` row →
exactly one card.

### G-14 (P2) Home order does not match the mandate; "Today's status" outranks Week and Preferences, Ask sits under the prompts, "Something new" chip is missing

**Evidence.** Mobile order (`A2`, `C2`): greeting → context question → suggestion → trust → **Ask**
→ How things look → Your week → Your preferences → A nearby activity → Suggestions are up to you.
Mandate: greeting → Ask (chips Nearby, Social, Indoors, Relaxing, **Something new**) → For you today
→ Your week → Your preferences → Today's status. `SENIOR_STARTER_CHIPS` (`view-models.ts:961-966`)
has four chips. There is no "For you today" group: on a day with a suggestion the nearby-activity
teaser is hidden (`senior-view.tsx:747-763`), on a calm day it is one unranked programme card.

**Proposed design (S).** In `senior-view.tsx` main column: greeting → (one pending prompt) → Ask →
suggestion card (rename its heading group "For you today") → trust; aside: Your week → Your
preferences → How things look. Add a fifth chip `{ id: 'something-new', label: 'Something new',
intent: {} }` with `novelty: true` if the API grows it, else reuse the `variety` reason by passing
an empty intent (the ranker already has a variety bonus, `activity_search.py:862`). Keep the calm
card first on a quiet day — the mandate's own "calm state stays the default" decision.

### G-15 (P2) "Your week" prints a question nobody can answer and a numeric quota

**Evidence.** `M70-your-week-with-plan.png`: "Nothing is booked in for this week yet -- would you like
some ideas?" with no control; "Your goals · Spend more time with other people, 2 times a week".
`N16`: same goal line above a week with one entry — it reads as 1 of 2.

**Root cause.** `sql_repository.py:5438` (`_gap_prompt`), `:5197-5202` (`_goal_text` appends
"N times a week"); `week-and-goals.tsx:160-162, 207-220` render both verbatim.

**Fix (S).** Client: render `gap_prompt` with a `Button size="lg" variant="outline"` "Show me some
ideas" that scrolls to / focuses the Ask field (or triggers the `Meet other people` chip when the
goal is `meet_people`). Show `goal.text` without the quota (strip after the comma, or add
`label`/`text_without_target` server-side) — the mandate: "never a quota the senior is failing".

### G-16 (P2) "I'm interested" on a listing outside this week yields a bureaucratic no-op

**Evidence.** `N01-interested-note.png`: "Noted. It runs on Wednesday 26 August, which is not in the
week being planned, so it is not on your week." The card was offered by Care+ for a "Somewhere
nearby" ask on 18 Aug, so the person did nothing wrong; nothing is kept anywhere they can see.

**Root cause.** `sql_repository.py:4302-4305`; the search does not filter to the plannable week.

**Fix (S).** Either filter/deprioritise sessions outside `week_starting..+6` in `filter_candidates`
with a `wrong_week` `FilterOutcome` ("3 are next week"), or make the note human: "Noted — it is next
Wednesday, so it is not on this week's list yet. Care+ will remember you were interested." and
show it under Your week as "Interested: Community Gardening, Wed 26 Aug".

### G-17 (P2) Primary buttons fail AA on hover; text-size buttons are 38px; phone numbers are not tappable

**Evidence.** axe on `C4`, `E5`: white on `#3c8671` = 4.33:1 (`button.tsx:18` `hover:bg-primary/80`).
Text-size options measure 38px (`styles.css:1760`, `min-height: 38px`; the 44px claim counts the
track padding, which is not the hit target on iOS). `M82`: "Who to ask: 6555 0202" is plain text
(`activity-card.tsx:209-213`).

**Fix (S).** `hover:bg-primary/90` or `hover:bg-[--green-strong]` (`#084f3d`); `.senior-text-size-
option { min-height: 44px; padding: 6px 12px }` and remove the 3px track padding claim; wrap the
phone in `<a href={`tel:${digits}`} className="underline">`.

### G-18 (P2) Search/refinement error and "Not listed" copy leak raw strings

**Evidence.** `M14-search-failed.png`: "We could not reach Care+ just now. Failed to fetch"
(`ask-silverloop.tsx:234-239` appends `error` = `Error.message`). Also `bad_timing` on a card teaches
nothing and says nothing (`declineReasonIntentPatch` returns null, `view-models.ts:1047`) — the person
gets no acknowledgement after choosing it beyond the card vanishing.

**Fix (S).** Drop `{error}` from the sentence (keep the fixed copy). For `bad_timing` /
`prefer_something_else` set `declineLearning` to "Understood — Care+ will not push that one."
so every reason gets a visible reply.

### G-19 (P3) The senior client receives coordinator fields it never renders

**Evidence.** `GET /v1/people/{id}/state` for the senior returns `attention_band: "watch"`,
`robust_z`, `delta_percent`, `rationale`, `permitted_actions`, and `pending_question.asked_because`
("Activity is about 41% below what is usual…", `context_question.py:119-123`). None is rendered, and
the e2e text guard passes, but the network tab on the person's own device carries the scoreboard.
Not a UI defect; recorded for the API/auth auditor: a `PersonStateSenior` projection (or field
exclusion when `require_senior`) would close it.

### G-20 (P3) Demo reset does not clear learned preferences or offer tallies

**Evidence.** After `POST /v1/demo/reset`, `world-model` still showed "Leans towards activities with
other people — they told Care+ so" and "Offered … 6 time(s)" from earlier runs; the memory prompt
then never re-appears because the belief already exists. A fresh SQLite file fixed it. Out of scope
for UX but it will bite a demo; flagging for the data/repository auditor.

---

## Heading, landmark and live-region notes (no separate finding)

- Heading outline is sane on every page (`report-full.json:headings`): one `h1`, `h2` sections,
  `h3` cards. Results: "What I found" is an `h3` and the card titles are also `h3` siblings — make
  the results heading an `h2` inside the Ask section or the titles `h4` (trivial).
- Landmarks: `header`, `nav[aria-label=Main]`, `main`, `aside`, `footer` present; the preview bar is
  outside any landmark (axe `region`, moderate) — wrap it in `<aside aria-label="Preview notice">`.
- Live regions: status messages are inserted as new `[role=status]` elements
  (`senior-view.tsx:655`); most screen readers announce that, but a persistent empty
  `<div role="status" aria-live="polite">` container that receives the text is the reliable form.
  The results container is `aria-live="polite"` (`ask-silverloop.tsx:339`) which will read all 14
  cards aloud at once — another reason for G-7.
- `Alert` sets `role="alert"` then is overridden to `status` — fine; the search error uses
  `role="status"` too, which is right for a calm tone.

## Prompt, chip and card wording vs mandate

- Memory prompt: "Yes, remember / Just for today / No" (mandate "Yes / Only for now / No") — fine.
- Card: title, when, where (in details), distance/social/environment/intensity — intensity is
  **not** shown as a fact line (only category); add it (`candidate.intensity` exists) for the
  "too tiring" decision to be informed. No "Why this may suit you" label above the reasons — a
  bulleted list with no lead-in; add a `p` "Why this may suit you" (S). "Why not?" exists as "Why
  some things are not shown" — good.
- No fake certainty anywhere; "booked" never appears unless booked.

---

## What NOT to build

- Not a chat. "Change something" returning to the question is right; do not add free-form turns.
- Not a settings page for the world model; fix the statements (G-3), do not add toggles per fact.
- Not per-card "Why this?" modals — the inline reasons are the right shape; just dedupe them (G-8).
- Not a step-count or streak widget on the senior home, even "for motivation".
- Not a slider for text size; not more than three steps.
- Not a page-level retry that reloads the tab; inline retry only.
- Not client-side re-ranking; capping/grouping results (G-7) is presentation, ranking stays in the
  API.
