# Care+ personalisation v2 — fresh product-comprehension review

Branch `feat/personalisation-ranking-worldmodel-v2` @ `7a1cf77` ("Merge track: one attendance fact
per programme, never per unattended session"). Reviewed in a throwaway worktree, API on 8900
(offline / SQLite / fixture / `LLM_ENABLED=false`), web on 3900. Nothing tracked was edited.
Walked with Playwright at 1280 px, 390 px and with the senior text-size control at "Largest".
Screenshots referenced below live in `./shots/`.

---

## 1. A senior (`/senior`, `/senior/activities`, `/senior/privacy`)

### What is being suggested, and why?

One thing at a time, always framed as optional. `shots/10-senior-home-after-case.png`:

> "One thing you might like today. / It is only a suggestion. Saying no is completely fine."
> "Chair Mobility & Balance — Would you like to hear more about Chair Mobility & Balance at
> Kampung Admiralty AAC? **Nothing has been booked.**"

Typing "something gentle near home with other people" produces a confirmation step before any
results (`shots/11-senior-ask-result.png`):

> "Here is what I understood · Somewhere close by · With other people · Something gentle
> [That's right] [Change something]"

and then three cards with per-card justifications (`shots/13-senior-thats-right.png`):

> "Why this may suit you · 650 m away, within the 1 km you asked for. · You will be among other
> people, as you asked. · Gentle, as you asked."

**Are the "why this may suit you" lines true to what I asked?** Every line I saw was true. But the
list is **match-only** — an unmet criterion is silently dropped rather than named.
`activity_search.py:768-772` appends a reason **only** when the axis outcome is `Tri.MATCH`; there
is no MISMATCH sentence anywhere. Combined with `_too_far` (`activity_search.py:240-257`, which by
deliberate design only filters when the person typed an explicit number), this means a search that
was confirmed back to me as "Somewhere close by / Something gentle" can return, with no caveat at
all:

```
r1  Karaoke & Social Hour           3400m  (intensity null)  "You will be among other people, as you asked."
r2  Cool-of-Day Park Walk           1600m  moderate          "You will be among other people, as you asked."
r3  Warm Water Exercise             2800m  moderate          "You will be among other people, as you asked."
...
r9  Community Gardening              650m  light             "650 m away, within the 1 km you asked for. | … | Gentle, as you asked."
```

(recorded live from the browser's own request, intent `max_distance_m: 1000, intensity: "light"`.)
The card still prints "About 3.4 km away (from the listing)", so a careful reader can work it out —
but the app never says "farther than you asked for", and "Why some things are not shown" only ever
lists the hard filters (I saw "5 did not match who you wanted to go with. · 2 are full."), never
distance or intensity. See §4 M-1 for the ordering half of this.

### What happens if I decline? What does each reason / clarification chip do?

"Not for me" opens a calm reason sheet (`shots/16-decline-reasons.png`):

> "Anything you would like to add? / Only if you feel like it. **Your answer is already saved
> either way.** [It is not for me] [It is too far] [It sounds too tiring] [The timing does not suit
> me] [I would prefer something else] [I'd rather not say]"

and the learning is stated back in one plain sentence (`shots/17-declined-too-far.png`,
`shots/18-decline-tiring.png`):

> "Care+ will look for somewhere closer than about 650 m."
> "Care+ will look for something gentler than light."

Two reasons ("too far", "too tiring") also ask a scope question before recording; the other three
record straight away. The nudge's own "Not today" offers a different, correctly-scoped set
(adds "Just a bad day", "I am already getting about" — `shots/33-nudge-not-today.png`).

Refinement chips (Nearer / Indoors / Earlier / More social / Something else) re-run the search with
the previous intent patched, and correctly refuse to layer a chip onto freshly typed text.

**"Change something" is a mislabel.** It does not let you change one of the three understood items;
it discards the parse and returns you to the empty ask (`ask-silverloop.tsx:186-189`,
`shots/12-senior-change-something.png`). Minor.

### Has anything been booked? Is "booked" ever claimed?

No — and this is the strongest thing on the senior surface. Every path says so, unprompted:

- card acknowledgement: "Added to your week for Wednesday 19 August. **Nothing is booked.**"
- nudge accept (`shots/21-nudge-tell-me-more.png`): "**Nothing has been booked and nobody has been
  told you looked.** … If you would like to go, you can turn up or ring the centre yourself.
  Care+ will not contact them for you. … There is nothing to reply to and nothing you have
  committed to."
- nudge decline: "Understood. We will not book anything."
- detail card: "Booking: Turn up at the rooftop. No need to register." and "Example listing for this
  demo." with a real phone number to call yourself.
- page footer, every senior page: "Care+ offers suggestions only. It never makes a booking,
  contacts anyone for you, or gives medical advice."

### What does Care+ remember about me? Are the ordinal beliefs honest?

Yes. `/senior/privacy` (`shots/19-senior-privacy.png`, `shots/37-pref-before-forget.png`):

> "**Your preferences** — Picked up from what you have asked Care+ for and what you have said
> no to. **It only ever changes the order of what you are shown — never what you are allowed to ask
> for.**
> How far you like to go — _Just a hint so far — one or two things you have said._ — Picked up from
> what you said no to — **You prefer somewhere closer than about 650 m.** [That's right] [Forget this]"

Direction and pivot, no inversion, no "lean away from nearer home". Strength is words, never a
number. "What Care+ does not know" is a first-class list ("No routine by time of day is
learned — every reading is a daily total. … No home area or usual travel distance is recorded;
distances are from a fixed listing.").

"Forget this" works and confirms: "Forgotten. Care+ will not use that any more."
(`shots/38-pref-after-forget.png`). Disputing a day says "You told Care+ the tracker got some
days wrong; those days are marked as **contested, not corrected**." and "Nothing was deleted."

**But one class of remembered fact is false — see §4 M-2.** The same page told me:

> "You were offered "Five-minute movement option" and **passed on it**."

for two nudges whose recorded outcome is `no_response`, and once for an offer that was still
**open and unanswered on the same screen**.

### What happens next?

"Your week" lists plans as days, not commitments ("Nothing planned this week. **That is a fine week
too.**"). The replan notice is honest (`shots/25-replan-notice.png`):

> ""Community Gardening" is now fully booked. "Sheltered Morning Walk" looks like a similar option,
> if you would like it instead. … [Use this instead] [No thanks]"

The reason is a real programme fact, produced by the `programme_becomes_full` simulation event, and
`ReplanReason` keeps `WEATHER` separate precisely so a forecast is never dressed up as "fully
booked" (`models.py:1686-1697`). Accepting swaps the entry; the senior's week then shows only
"Wednesday, 19 Aug — Sheltered Morning Walk". Nothing fabricated.

**But "Your week" contradicts the card that just wrote to it — see §4 M-3.**

### Does anything read as monitoring, medical, a score, a percentage, a deadline or a status word?

**No.** I scanned the rendered text of all three senior routes for `score|risk|alert|monitor|status|
overdue|deadline|adherence|diagnos|symptom|percentile` and `\d+%`: **zero hits on every page**. The
only numeric line on any senior page is "You are 74 years old." Step counts never appear; the
strongest phrasing is "You have been getting about less than usual for a few days now", always
followed by "Care+ only notices how much you get about each day. **It never decides anything
about your health.**"

### Is the tracker-not-synced state calm?

Yes (`shots/31-tracker-not-synced.png`):

> "Your wearable was not worn for long enough today for Care+ to say anything about it."

No blame, no number, no prompt to fix anything. (The API behind it holds
"Wear-time was 2.1 hours; at least 8 hours is required" and `device_suspected: true` — none of that
reaches the senior, correctly.)

### Does a failed tap ever wipe the page?

No (`shots/32-failed-tap.png`). With every POST forced to 500, tapping "Not today" left the whole
page intact, the card unanswered and its buttons re-enabled, and added one line:

> "That didn't go through. Try again?"

### Accessibility

At 390 px and at "Largest" (root font 22 px) there is **no horizontal overflow**
(`scrollWidth == clientWidth == 390`), the layout reflows to one column, and every app control is
≥44 px tall (`shots/40-senior-390.png`, `shots/41-senior-390-largest.png`,
`shots/43-results-largest.png`). Focus is moved to the confirmation heading, then the results
heading, then the decline-learning sentence.

---

## 2. A coordinator (`/care-team`, `/coordinator`)

### Who needs attention and who is fine? Are bands words?

Per-person standing is words only (`rosterStandingLabel`, `view-models.ts:137-150`): "Waiting for
your review", "Care+ has suggested something", "Being watched — nothing to do yet",
"Tracker may not have synced on N of the last M days", "No attention needed". Never a score, never
a percentage, never two people compared. The queue tiles above are caseload counts, each captioned
("No reply recorded — _Closed as silence, not a refusal_") and totalled ("Across your caseload of
1 senior."). `shots/50-care-team.png`.

### Why? (`why_human`, gate caption, prior outreach)

`shots/50-care-team.png`:

> "Activity has stayed far enough below this person's own usual range, for enough valid-wear days,
> that the ladder stopped and asked for a person. 2 lighter steps were tried (a check-in on
> 2026-08-19; a suggestion on 2026-08-20); neither was answered."
>
> "**What Care+ tried first** — Wed, Aug 19 — Wellbeing check-in: Gentle movement check-in.
> _No reply recorded_ / Thu, Aug 20 — Activity suggestion: Chair Mobility & Balance.
> _Nothing recorded yet_"

The gate caption is on the Evaluation surface and is explicit about provenance
(`shots/60-evidence.png`): "The ladder evaluates in this order and stops at the first gate that
decides the outcome… Which one stopped it is reported by the API (`decided_by_gate`), not inferred
here." — followed by seven named gates, one marked "Determined the decision" and the rest
"Passed" / "Not reached".

Note how carefully this surface distinguishes **"No reply recorded"** from **"Nothing recorded
yet"** — exactly the distinction the senior-facing world model gets wrong (§4 M-2).

### What did the senior say? Any per-person leak?

Aggregated only. "Mdm Lim's outreach, end to end — Suggestions sent 2 / Asked to see more 0 of 2 /
Reported back None yet", with "Tapping "tell me more" and actually doing something are recorded
separately and shown separately." The caseload knowledge panel is counts-only and says so:

> "10 facts recorded across your caseload — 0 told directly, 6 picked up from behaviour, 0 from
> outside information and 4 from demo profiles. … **Counts only — never the facts themselves.**"

I typed a distinctive phrase into the senior's free-text ask and then searched `/care-team`,
`/operations`, `/evidence`, `/simulator` and the audit-event feed: **the raw text appears nowhere**.
The audit event records `parsed_by`, counts and a `query_id` only.

### What requires human judgement? Does the structured review make sense?

Yes. Three radio choices with honest descriptions (`shots/52-override-reason.png`):

> "Agree with the suggestion — The suggested next step is what you would do."
> "Hold — not acting yet — Neither agreement nor disagreement — recorded as "not yet"."
> "Do something else — **Needs a reason, so the pattern can be counted later.**"

Choosing "Do something else" blocks submission until a reason is picked ("Say why you are not
taking the suggested step.") from four options, of which "Another reason" exists so the list is not
forced. The note field is scoped honestly: "Kept on this case for your team. **It is never added to
the operator audit trail, which records only that a note exists.**" And the whole panel is preceded
by: "Acknowledging or resolving a case only appends reviewer evidence here; **neither action sends a
message or call.**"

After resolving, the caseload header gains a denominator'd counter:

> "1 of 1 recorded review took a different step from the one Care+ suggested. Kept for review
> and evaluation only — **a coordinator's decision never changes how suggestions are ranked.**"

### Can I reach resolved cases?

Yes — Showing [Needs attention | Resolved | All] (`shots/55-resolved-cases.png`). The prior decision
and note are readable (`shots/57-resolved-action-history.png`):

> "Action history — Resolved / coordinator · 9/13/2026, 8:54:10 PM / **Do something else — We
> already know why — context Care+ does not have** / Family already checking in daily; no
> outreach needed this week."

Two snags: that history is hidden behind a disclosure labelled "Why this reached a human, and what
to do", which does not advertise that it contains what a colleague already decided (minor); and a
resolved case still renders the full, empty review form including a "Mark resolved" button (minor).

---

## 3. A judge (`/evidence`, `/operations`, `/simulator`, `/scenario-lab`)

### Deterministic vs AI

Unambiguous. System Health (`shots/62-system-health.png`): "Agent — Outreach planner — **model off,
deterministic ranker in use** · _Model off_"; "Policy engine — Deterministic ladder, policy
`silverloop-policy-v1`". Per decision (`shots/03-sim-day2.png`):

> "**Chosen by the ranker — planner off** · _Deterministic_ — The deterministic policy had already
> decided whether to reach out and which kind of action was allowed. The ranker only chose among
> those permitted options — it could not escalate, contact anyone, or reach an option the policy had
> filtered out. **No model was involved, so there was nothing for the safety gate to intercept.** The
> wording came from a fixed, reviewed template."

and the planner panel: "Outreach decisions 2 / Chosen by the agent 0 of 2 / Fell back
(fallback_disabled) — 2", with "Agreement is not a quality score."

**The `NOT_A_MODEL` banner is not in the product at all.** It exists only in
`docs/evaluation/ranking-llm.{json,md}`; `grep -rn "NOT_A_MODEL\|ranking-llm" apps/web` returns
nothing. So a judge who asks "what did the LLM arm show?" is told only "model off" and has to be
handed a repository file. See §4 m-8.

### What actually learns?

Two learners, only one of which is shown.

**Shown, well:** the outreach Beta-Bernoulli learner, as the "Expected fit" card
(`shots/61-policy-evaluation.png`):

> "Each score is an expected fit — the chance this option is both taken up and, once tried, enjoyed
> — for suggestions Care+ is already allowed to make. **It never decides whether an action is
> permitted: consent, data-quality and contact-cap gates stay fully deterministic and are never
> influenced by this learner.** An option with no history yet starts at 25%, not 50% — two separate
> unknowns … multiplied together rather than one."
> "Five-minute movement option — 20% · 0 accepted / 1 offer" … "Sheltered Morning Walk — 25% ·
> Not enough recorded history yet for a confident estimate."

**Not shown at all:** the _activity-ranking_ learner — the thing this branch is named after. The API
computes a six-factor breakdown per candidate (`intent`, `preference`, `engagement`, `repetition`,
`context`, `friction`) each with a coverage note (`activity_search.py:955-1010`, e.g. "Judged on
{coverage:.0%} of what is known about the kinds of activity that suit them; positive where this
listing confirms it, negative where it contradicts it"). **None of it reaches the API response** —
`RankedActivity` carries only `rank`, `reasons`, `selected_by` — and none of it reaches any screen.
A judge asking "why was this ranked first?" gets at most three match bullets. See §4 M-1/M-4.

### What is synthetic?

Labelled everywhere, at three levels: a persistent header band ("Demo data · **Synthetic**: this
environment uses synthetic personas and simulated programme data. No real senior health data is
used."); a Data provenance table ("AAC programme catalogue — Simulated fixtures — not a live AAC
integration"; "Healthy 365 — Future authorised adapter, not connected"; "Garmin — Column-shape
sample import only"); and per-persona honesty in the evaluation itself:

> "Mdm Devi · synthetic, not in the product playbook — **SYNTHETIC -- not in the product playbook;
> no research or interview basis.** Invented to give the evaluation harness a second, independent
> persistent-decline case … so M2/M3 are not measured on a single data point."

Individual listings carry "Example listing for this demo." and distances carry "(from the listing)".

### What has been measured?

Policy comparison is exemplary (`shots/61-policy-evaluation.png`). Header: "5 personas · 15
scenarios · 59 decisions". Every figure carries n/d _and_ a percentage, an empty stratum reads
`0/0 (n/a)` rather than 0%, there is a full 3×7 matrix, and a per-persona table for all five
personas. The caveat is a card of its own:

> "**Not clinical evidence** — Seeded software-policy simulation; not clinical validation. These are
> deterministic software-policy tests replayed over synthetic scenarios: they measure how each
> policy behaves against scripted expectations, not clinical or real-world accuracy, and say
> nothing about health outcomes."

The nudge-effectiveness panel refuses to fold a tap into a rate ("A tap is not an outcome… The
distance between the two is the most interesting number this product produces, so it is shown here
rather than folded into a rate"), labels a sample of one ("Sample of 1 — too few to read as a
rate."), and refuses to print a zero it does not have ("**No number is shown, because there is not
one to show — this is not a result of zero.**").

Ranking evaluation (`shots/62-system-health.png`) shows six metrics, each with a 95% interval and n:

> "NDCG@1 0.850 (CI 0.776–0.919, n=60) … MRR 0.574 (CI 0.453–0.697, n=60)
> 60 cases · seed 20260908 · digest 34adab71f123746c… — Seeded software-policy simulation over a
> synthetic catalogue and synthetic personas — not clinical validation, not real senior data."

### Is any number presented without its denominator or its caveat?

I found **no bare number** on any surface. I found one number presented without its **comparator**,
which is worse for this particular card — see §4 M-5: the ranking card is titled "**Does
personalised ranking actually do better than the floors?**" and then shows no floor.
`docs/evaluation/ranking-evaluation.json` holds `reference_lines`, `lift_over_reference_discriminable`,
`lift_over_reference_persona_clustered`, `metrics_persona_clustered`, `per_persona`, `strata`,
`ablations`, a frozen `holdout` split and a `not_user_truth` string — the product surfaces the
`core` split's six headline metrics and none of the rest.

---

## 4. Comprehension failures

### Major

**M-1 — The "why" list can only affirm, so an unmet request is invisible; and once the ranker has
been taught, it can surface the opposite of what was asked.**
`apps/api/src/silverloop/activity_search.py:760-772` (reason appended only on `Tri.MATCH`),
`apps/api/src/silverloop/activity_search.py:240-257` (an implied "near home" never filters).
Reproduced live: the intent shown back to me was "Somewhere close by / With other people /
Something gentle" (`max_distance_m: 1000, intensity: light`) and the top three results were 3.4 km,
1.6 km (moderate) and 2.8 km (moderate), each justified with the single line "You will be among
other people, as you asked."; the 650 m gentle option sat at rank 9. `shots/11-senior-ask-result.png`
is the confirmation step; the ranking was captured from the browser's own network response. On a
clean `demo/reset` the same query returns 650 m / 700 m / 850 m, all `light` — the divergence
appears only after the ranker has accumulated decline-derived preferences and engagement history,
i.e. exactly when personalisation is supposed to be helping. A senior cannot tell either that the
list has drifted or why. Even if the ordering is defended as "you said no to all the near gentle
ones", the screen never says so: "Why some things are not shown" lists only `wrong_company` and
`full`.

**M-2 — The senior's own memory page says they refused offers they never answered.**
`apps/api/src/silverloop/world_model.py:622-640` — the three-way branch is
completed / accepted / **else**, and the else prints _"You were offered "X" and passed on it."_
`apps/api/src/silverloop/sql_repository.py:2427-2436` states outright that its `offered` tally
"includes the ones they never replied to". Verified against the database: `int_fabca9e948` and
`int_c90dab9ea9` both carry outcome `no_response`; a third (`int_827adb53d5`) had **no outcome row
at all** and was still open on the senior's home page as
"Would you like to hear more about Chair Mobility & Balance? … [Yes, tell me more] [Not today]
[Maybe later]" — while `/senior/privacy` simultaneously read "You were offered "Chair Mobility &
Balance" and **passed on it**." (`shots/19-senior-privacy.png`). This contradicts the product's own
rule, written in four places: `view-models.ts:1123` ("a reply that never comes is recorded as
silence, not a refusal"), `care-team-view.tsx:390` ("Closed as silence, not a refusal"),
`outreach-history-card.tsx:97`, `sql_repository.py:1206`. The coordinator surface gets this right
("No reply recorded" / "Nothing recorded yet"); only the senior is told they said no.

**M-3 — "Added to your week" and "Nothing planned this week" on one screen.**
`apps/web/components/senior/ask-silverloop.tsx:212` fires `onPreferencesLearned?.()` but there is no
week-changed callback, and `apps/web/components/senior-view.tsx:667` passes only that one prop.
Reproduced from a clean reset: tapping "I'm interested" printed _"Added to your week for Wednesday
19 August. Nothing is booked."_ on the card while the "Your week" panel beside it still read
_"Nothing planned this week. That is a fine week too."_; after a reload it read _"Wednesday, 19 Aug
— Community Gardening"_. The POST response already contains the updated week. `shots/45-week-stale-contradiction.png`.

**M-4 — The result card headlines the ranker's first session, not the soonest one — and that feeds
the plan.** `apps/web/lib/view-models.ts:1378-1395`: `groupSearchResults` keeps the first result in
_rank_ order as the card's date and pushes the rest into `alsoOn` in rank order; the field's own
doc at `:1364` claims "earliest first", which is not what the code does. On simulated day
2026-08-21 the card read _"Community Gardening — Wed, 26 Aug, 9:00 am / Also on Sat, 22 Aug"_ and
_"Chair Mobility & Balance — Wed, 26 Aug, 9:30 am / Also on Fri, 21 Aug, Sun, 23 Aug"_ — i.e. the
next chance to go was today or tomorrow, and the headline said next week. This is not cosmetic:
"I'm interested" plans against the headline date, so on that card the API answered
`planned: false, plan_day: null` ("not on this week's list yet") when a session inside the current
plan week existed. The same programme's own nudge detail card gets it right: _"Fri, 21 Aug,
9:30 am"_ (`shots/21-nudge-tell-me-more.png`). So does `/senior/activities`, which is ordered by
day (`shots/39-senior-activities.png`).

**M-5 — "A nearby activity" is still offered after the senior turns suggestions off.**
`apps/web/components/senior-view.tsx:799` — `{!suggestion && nearest && …}` is the one block on the
page not guarded by `consentActive` (contrast `:772`, `:774`, `:778`). `shots/35-consent-off-home.png`
shows the headline _"Suggestions are off. Care+ will not suggest anything until you turn
suggestions back on."_ with _"A nearby activity — Chair Mobility & Balance — Kampung Admiralty AAC ·
0.7 km away"_ in the column beside it. The one promise the consent control makes is visibly broken
on the screen that makes it.

**M-6 — The ranking-evaluation card asks a comparison question and shows no comparator.**
`apps/web/components/evidence-view.tsx:1323` — "Does personalised ranking actually do better than
the floors?" followed only by Care+'s own six metrics. `docs/evaluation/ranking-evaluation.json`
already carries `reference_lines`, `lift_over_reference_persona_clustered`, per-persona rows, strata
and a frozen holdout; none is surfaced, and the card points at a repository path a judge cannot
open ("this app does not serve repository markdown, so this is a path, not a link"). A judge who
asks "better than what, and by how much?" gets nothing from the product, while the policy-comparison
card two tabs away answers exactly that question for the decision ladder.

### Minor

- **m-1** `apps/web/components/silverloop/outreach-history-card.tsx:117` renders the real wall-clock
  `created_at` next to simulated-day copy: _"Chair Mobility & Balance — Sun, Sep 13, 8:50 PM"_ above
  _"Waiting for a reply until Sat, Aug 22."_ Two clocks in one card, with the deadline apparently
  three weeks before the offer. The case card above it uses simulated days correctly.
- **m-2** `apps/web/components/care-team-view.tsx:478-480` puts `rosterStandingLabel` ("No attention
  needed", because `open_case_id` is now null) next to a `StatusBadge` built from `attention_band`,
  which the API leaves at `"review"` after resolution — so the roster row reads "Mdm Lim / No
  attention needed / **Needs review**". `shots/58-care-team-all-open.png`.
- **m-3** `apps/web/components/senior/senior-activities.tsx:75` — "Everything on near home, with the
  times…" is missing a comma and reads as a broken template.
- **m-4** "Change something" (`ask-silverloop.tsx:186-189`) discards the parse instead of letting you
  edit one of the three understood items.
- **m-5** "You prefer something gentler than **light**" — the ordinal template is right but `light`
  is an enum token, not a word a senior uses; the pivot stored for that preference is `0.0`.
- **m-6** `POST /v1/demo/reset` does not clear `interventions`, so world-model outreach facts (and
  the M-2 "passed on it" lines) survive a reset while "Your preferences" correctly resets to
  "Nothing learned yet" — a demo run inherits the previous run's memory.
- **m-7** `programme_becomes_full` and `weather_turns` are accepted by `POST /v1/simulation/advance`
  but are absent from the simulator's Advanced controls (`shots/24-sim-advanced.png`), so the
  branch's replan loop — goal → plan → the world changes → replan → ask — cannot be demonstrated
  from the product's own screens. I had to fire it over the API to see it.
- **m-8** `NOT_A_MODEL` and the whole ranking-LLM arm are not surfaced anywhere in the web app.
- **m-9** Confirmation sentences land out of position: "Understood. We will not book anything." and
  "Thank you — that is helpful to know." render after the "How Care+ works" block rather than
  where the question was.
- **m-10** A resolved case still renders the full review form with an active "Mark resolved" button,
  and the prior decision is hidden behind a disclosure titled "Why this reached a human, and what to
  do".
- **m-11** `GET /v1/people/{id}/week` returns both the superseded and the replacement entry after an
  accepted replan; the senior UI filters it, so the screen is correct, but the contract is not.

---

## 5. The five strongest judge-defensible claims

1. **The senior surface contains no score, no percentage, no step count and no clinical word.** A
   programmatic scan of all three senior routes for score/risk/alert/monitor/status/deadline/
   adherence/diagnosis language and for `\d+%` returned zero hits; the only numeral is the person's
   age. Answered on screen.
2. **Nothing is ever booked, and the product says so before you can ask.** Six independent places,
   including "Nothing has been booked and nobody has been told you looked." Answered on screen.
3. **Silence is a first-class recorded state, not a refusal — in the policy, the coordinator queue
   and the effectiveness panel.** "No reply recorded — Closed as silence, not a refusal";
   "Not reported back — 1 — silence, not a refusal"; "No number is shown, because there is not one
   to show — this is not a result of zero." Answered on screen — **except on the senior's own memory
   page (M-2)**.
4. **The decision is deterministic, gate-by-gate, and says which gate decided.** Seven named gates,
   one marked "Determined the decision", the rest "Passed"/"Not reached", with the source of that
   claim named (`decided_by_gate`, "not inferred here"). Answered on screen.
5. **The policy beats two simpler policies on a replayed library, and every figure carries its
   denominator and its caveat.** 5 personas · 15 scenarios · 59 decisions; `0/17`, `0/19`,
   `0/0 (n/a)`; per-persona tables; "Not clinical evidence". Answered on screen.

## 6. The five questions a sceptical judge would ask

1. **"Better than the floors — what floors?"** The ranking card poses the question and shows no
   comparator (M-6). The artefact has the lift numbers; the screen does not. **Not answered.**
2. **"You say it learns what suits me — show me it working."** Partly answered: the preference is
   stated ordinally with strength in words and a Forget control. **But the ranking it produced put
   3.4 km and 'more active' first for a request confirmed back as 'close by' and 'gentle', with no
   caveat (M-1), and no per-candidate score breakdown exists in any screen.** Not answered.
3. **"How do you know a non-reply isn't a refusal?"** Answered four times over on the coordinator and
   evaluation surfaces — and contradicted on the senior's own privacy page (M-2). **Half answered.**
4. **"What did the LLM do?"** Answered for this build ("model off", "planner off", "fallback
   (fallback_disabled) — 2") but the recorded LLM-arm evidence and its `NOT_A_MODEL` disclaimer live
   only in the repo (m-8). **Half answered.**
5. **"Show me the whole loop — plan, the world changes, replan."** The loop works and the replan copy
   is honest, but neither triggering event is reachable from the simulator UI (m-7), and the week
   panel contradicts the card that writes to it (M-3). **Not demonstrable from the product alone.**

## 7. What is already good

- The senior vocabulary. "That is a fine week too." / "There is no right answer." / "Your answer is
  already saved either way." / "marked as contested, not corrected" / "Nothing was deleted."
- The refusal to fold a tap into a rate, and the refusal to print a zero that is really an absence.
- Honest labelling of synthetic data down to individual invented personas ("no research or interview
  basis"), and of what is _not_ known ("What Care+ does not know").
- The gate trace naming its own source of truth rather than re-deriving it.
- Error handling: a failed POST never blanks a page, and an out-of-week plan gets a written, truthful
  acknowledgement instead of a rejection.
- Accessibility: no horizontal overflow at 390 px or 22 px root font, ≥44 px targets, managed focus
  through the ask → confirm → results → decline sequence.
- The coordinator review's boundary statements: acknowledging never sends anything; a coordinator's
  decision never changes ranking; the note is never added to the operator audit trail.
