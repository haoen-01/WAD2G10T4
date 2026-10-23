# ADR 0005: Engagement and experience as two learned signals

Status: Accepted (2026-09-13). The weaker social tie-break (exact ties only) is accepted for
now.

## Context

`learning.PreferenceLearner` (`apps/api/src/silverloop/learning.py`) is the Beta-Bernoulli learner
that ranks outreach candidates (`GENTLE_NUDGE`/`PROGRAMME_SUGGESTION`) `policy.py` has already
permitted. Before this change it kept exactly one posterior per candidate key, folded from
whichever report was most informative: `enjoyment` (`enjoyed`/`okay`/`not_for_me`) superseded
`follow_through` (`completed`/`partial`/`not_this_time`/`unable`), which superseded the bare
`outcome` (`accepted`/`declined`/`no_response`/`deferred`). "The most informative report
supersedes the earlier ones" is the right rule for `accepted` vs. `completed` -- once we know what
happened, the fact that they tapped "yes" first teaches nothing more. It is the wrong rule for
`completed` vs. `enjoyed`: attendance is not evidence that goes stale the moment a taste verdict
arrives, it is a different fact answering a different question, and collapsing them into one
number threw the attendance fact away.

Concretely: `_ENJOYMENT_WEIGHTS["okay"] = (0.5, 0.5)`, the Beta(1, 1) prior's own mean. Every time
a person reported "okay", that report _replaced_ whatever the follow-through weight would have
contributed for that intervention. A candidate attended ten times out of ten offers and rated
"okay" every time therefore read, after this change (the enjoyment split) shipped, almost exactly
like a candidate that had never been offered at all -- ten repeated `okay` reports averaged the
posterior straight back to ~0.5, discarding the fact that the person chose this option every
single time it was on offer.

The ticket's own framing names the two questions this conflates: **engagement** ("would I choose
/ attend this?") and **experience** ("did I like it once I did?"), with a worked example --
chair exercise (high attendance, neutral enjoyment) vs. gardening (medium attendance, very high
enjoyment) -- chosen because it is exactly the case the collapsed posterior gets wrong.

## Options considered

### A. Keep one collapsed posterior (status quo)

Simplest, no change. Rejected: it actively discards real attendance history the moment a
lukewarm-but-honest "okay" report arrives, and it is the collapsed posterior, not policy or
consent, that decided which suggestion a permitted set led with -- the wrong axis is winning the
tie-break. Demonstrated below with real numbers, not asserted.

### B. Two independent Beta-Bernoulli posteriors, combined as `engagement x experience`

ENGAGEMENT is folded from `_OUTCOME_WEIGHTS`/`_FOLLOW_THROUGH_WEIGHTS` exactly as before --
`follow_through` still supersedes `outcome`, `enjoyment` no longer touches it at all. EXPERIENCE
is folded from `_ENJOYMENT_WEIGHTS`, and only when `follow_through` is `completed` or `partial`
(the only two values that mean the person actually attended -- see `_ATTENDED_FOLLOW_THROUGHS`).
`expected_value(key)` -- the one number every caller outside `learning.py` reads -- becomes
`engagement_value(key) * experience_value(key)`, an honest `P(attend) x E[enjoy | attend])`. A
key with no reports on either axis defaults to `0.5 x 0.5 = 0.25` (down from the old collapsed
learner's `0.5`); a key with engagement evidence but no experience report yet keeps its
EXPERIENCE factor at the neutral `0.5` prior -- missing, never negative, so an unreported
experience can never drag a well-attended candidate below what its engagement alone would earn
it, only a genuinely poor _reported_ experience can.

### C. Two posteriors, but experience is a penalty-only multiplier bounded at 1.0

Same two posteriors, but `expected_value = engagement * min(1.0, experience / 0.5)` -- so no
experience data is a true no-op (multiplier exactly 1) and only a _below-neutral_ experience
report ever discounts engagement; a glowing experience cannot lift a candidate above its raw
engagement score. Rejected in favour of B: the ticket's own formula is
`P(attend) x E[enjoy | attend]`, a genuine joint probability, and the chair/gardening example
below shows option B already produces the desired ranking (gardening's reported enjoyment lets it
compete despite lower engagement) without inventing an asymmetric multiplier that has no
probabilistic reading. Noted here because it was seriously considered and would also have fixed
the chair-exercise defect; B was preferred for being the more literal, easier-to-explain reading
of the requested formula, and because the codebase already treats a Beta(1, 1) prior mean as the
standard way to represent "we don't know" everywhere else in this module (`deferred`'s `(0, 0)`,
`coordinator_resolved`'s `(0, 0)`).

## Evidence gathered

All computed with the actual (post-change) `PreferenceLearner`; see
`apps/api/tests/test_learning_weights.py::test_reliable_but_lukewarm_attendance_can_outrank_rare_but_loved_attendance`
for the pinned, executable version of this exact scenario.

**The chair-exercise / gardening example from the ticket.** Chair exercise offered and completed
10/10 times, rated `okay` every time. Gardening offered 6 times: completed and rated `enjoyed` 3
times, declined twice, no-response once (i.e. "medium attendance").

|                | old collapsed posterior | new: engagement | new: experience | new: combined |
| -------------- | ----------------------- | --------------- | --------------- | ------------- |
| chair_exercise | 0.500                   | 0.917           | 0.500           | **0.458**     |
| gardening      | 0.533                   | 0.533           | 0.800           | **0.427**     |

Under the old collapsed posterior, gardening (0.533) already narrowly outranked chair exercise
(0.500) -- despite two outright declines and a third of its offers going unanswered -- because
`okay`'s `(0.5, 0.5)` gave chair exercise's ten-for-ten attendance record no way to show up in the
number at all. **Under the split posteriors this reverses**: chair exercise (0.458) now outranks
gardening (0.427), because ENGAGEMENT finally reflects the ten-out-of-ten acceptance record
(0.917) rather than losing it to the enjoyment override, while EXPERIENCE still honestly records
that gardening, when tried, was loved (0.800) and that chair exercise, when tried, was merely
"okay" (0.500, the neutral prior -- `okay` neither rewards nor punishes).

**Is the new order desirable?** Yes, for two reasons this product cares about. First, revealed
behaviour: a person who accepts and completes chair exercise every single time it is offered has
demonstrated, ten times over, that this is a viable, sustainable option for them regardless of how
enthusiastically they rate it -- "okay" is not "no", and treating it as erasing the attendance
record was the actual defect. Second, gardening's two outright declines and one silence are real
negative engagement evidence that the old system let three "enjoyed" reports fully overwrite; the
split keeps that evidence live rather than discarding it the moment any enjoyment report exists
for the same key. Neither ordering is a safety question -- both are policy-permitted candidates
for the same decision, and the choice only affects which message text is offered first -- but the
split is the more honest read of what the person has actually shown they will do.

**Missing-report handling.** A key with engagement evidence and zero enjoyment reports keeps
EXPERIENCE at 0.5 (neutral), not below it:
`test_engagement_does_not_reset_when_an_enjoyment_report_arrives` and the docstring's own claim
are pinned by `PreferenceLearner.experience_value` reading straight off the untouched Beta(1, 1)
prior. This satisfies the ticket's "handle a missing enjoyment report as missing, not negative":
the only way EXPERIENCE moves below 0.5 is an actual `not_for_me`/`okay`-heavy report set, never
silence.

**Attendance precondition.** An enjoyment report the API happens to accept alongside
`not_this_time`/`unable` (a client-side edge case `record_enjoyment` does not currently forbid --
see `sql_repository.record_enjoyment`'s docstring, which only requires _some_ prior
follow-through, not specifically an attending one) is excluded from EXPERIENCE entirely:
`test_enjoyment_attached_to_a_non_attendance_follow_through_is_not_experience_evidence`. This is a
stricter, more defensible reading of "experience conditional on attendance" than the code
previously enforced anywhere.

## What moved, and why every number is explained rather than "fixed"

- **`docs/evaluation/policy-comparison.{json,md}`**: unchanged (verified by re-running
  `python -m silverloop.evaluation ../../scenarios --out ../../docs/evaluation`; git diff empty).
  That harness explicitly does not exercise `learning.py` -- see its own
  `NOT_MEASURED["Intervention-adaptation rate"]` entry, unaffected by this change -- because it
  never runs the record/outcome loop this learner reads from. Outreach _decision_ ordering
  (`Decision.GENTLE_NUDGE` vs. `NO_ACTION` etc.) is `policy.py`'s ladder, never the learner's; the
  15 deterministic scenarios under `scenarios/*.yaml` all still pass unchanged
  (`python -m silverloop.scenarios ../../scenarios`), because none of them assert on
  _candidate_-level ordering within a decision, only on the decision itself.
- **`docs/evaluation/ranking-evaluation.{json,md}`** (E1, `evaluation/ranking/`): unchanged
  (re-run and diffed empty). That benchmark scores `activity_search`'s dimensional preference
  learner (`preferences.py`'s `apply_decline`/`apply_enjoyment`/`dimension_score`), a separate
  learner for the user-initiated activity-search surface, not `learning.PreferenceLearner`.
- **`apps/api/tests/test_persistence.py::test_state_and_outcomes_survive_repository_restart`**:
  the hardcoded assertion `scores["gentle_nudge"] > 0.5` failed, because a bare `accepted` outcome
  with no follow-through now combines weak ENGAGEMENT evidence (`0.25, 0.0` -> 0.556) with a still
  entirely-unreported EXPERIENCE factor (0.5 default) to give 0.278, below the old single-posterior
  threshold of 0.5. This is not a bug being routed around: the test's actual intent (persisted
  preference reflects the recorded evidence and exceeds "no evidence") is preserved by comparing
  against a freshly built `PreferenceLearner` fed the identical single outcome, rather than a
  hardcoded number that assumed a single-posterior scale.
- **Every other test in `test_learning_weights.py`, `test_response_clock.py`,
  `test_multi_person.py`, `test_follow_through_ownership.py`,
  `test_intervention_outcome_ownership.py`, `test_failure_paths.py`**: pass unchanged, because
  they compare `expected_value` against a freshly constructed `PreferenceLearner` fed the same
  inputs, or compare relative before/after movement, rather than against a hardcoded absolute
  number -- the correct pattern this ADR's fix to `test_persistence.py` brings that one test back
  in line with.
- **`PRIOR` in `test_learning_weights.py`**: kept (0.5, one posterior's own prior mean) and a new
  `COMBINED_PRIOR = PRIOR * PRIOR` (0.25) added; every assertion that previously compared
  `expected_value` against "no evidence at all" now compares against `COMBINED_PRIOR`, with the
  reasoning inline at each site.

## Decision

Split `PreferenceLearner` into two Beta-Bernoulli posteriors, ENGAGEMENT and EXPERIENCE (Option
B), combined multiplicatively into the single `expected_value` every caller outside `learning.py`
already reads. No schema change: both posteriors are rebuilt, exactly as the one posterior was
before, from `InterventionRow`/`InterventionOutcomeRow`/`InterventionFollowThroughRow`/
`InterventionEnjoymentRow` already joined in `sql_repository._preference_learners`. The public
surface (`record`, `expected_value`, `snapshot`) is unchanged in shape; every existing call site
in `sql_repository.py` (ranking, audit deltas, `OperationalMetrics.preference_scores`/
`candidate_preference_scores`, the planner's `CandidateOption.preference_score`) keeps working
without modification, because they all consume `expected_value`/`snapshot`, not the internal
representation. One consumer of that same number is prose, not code, and needed a matching fix
even though nothing broke: `agent/tools.py`'s `get_candidate_options` tool description is what
tells the planning LLM what `preference_score` means, and prose does not update itself when the
number it describes changes scale -- see "Lead review corrections" below.

Deliberately **not** surfaced: `engagement_value`/`experience_value` are not exposed on any
Pydantic model (`CandidateOption`, `OperationalMetrics`), so no OpenAPI/TS client regeneration is
needed. The senior surface already shows no scores, and the operations dashboard
(`evidence-view.tsx`'s "Preference learning" card) already shows one number per candidate plus
its offer/accepted sample counts -- adding a second pair of numbers there is a real, separately
reviewable UI decision, and touching `models.py` in a seven-way-parallel worktree round is
avoidable surface area for a decision that does not require it. This is the smallest reversible
implementation that makes the decision real; splitting the surfaced number later is additive, not
a reversal.

## Consequences

- Outreach candidate ranking within a decision can now differ from before wherever a candidate has
  been attended reliably but rated lukewarmly, or attended rarely but rated highly, exactly as
  demonstrated above. This never changes _whether_ outreach happens, only which permitted
  candidate is offered first.
- The "no evidence" baseline for `expected_value` moved from 0.5 to 0.25. Anything reasoning about
  `expected_value` in absolute terms (rather than relative to a freshly built learner fed the same
  inputs) needs to know this. All such call sites in the codebase were audited and fixed as part of
  this change (see above). `OperationalMetrics.preference_scores`/`candidate_preference_scores` is
  rendered as a raw percentage in `evidence-view.tsx`'s "preference learning" card -- see "Lead
  review corrections" below for why that card's copy, not just its number, needed to change.
  `docs/api.md` and `docs/observability.md` now say so wherever `preference_before`/
  `preference_after`/`candidate_preference_score` are described.
- `docs/architecture.md`'s "Learning boundary" section and the `learning.py` module docstring now
  describe two posteriors; both were updated in this change.

## Lead review corrections (applied on this branch before merge)

The first pass of this ADR left two consequences as "flagged, not fixed" -- deferring them turned
out not to be acceptable, and both are now fixed by construction rather than deferred further.

**1. `SOCIAL_DIMENSION_RANKING_WEIGHT` could override a single real observation.** The original
0.15 was tuned against the single-posterior scale: before this ADR, one `accepted` + `completed`
report moved `expected_value` from 0.5 to 0.667 (a gap of 0.167, barely above the 0.15 ceiling).
After the split, the same report moves 0.25 to 0.333 (a gap of 0.083) -- now _below_ 0.15, so a
maximal opposing `social_shape_score` could flip a candidate the person actually accepted. Worse,
the realistic worst case is two-sided, not one: a person can hold both a `senior_statement`
`PREFER` on one SOCIAL value and an `AVOID` on the other at once, so within `GENTLE_NUDGE`'s three
candidates (two SOLO, one SOCIAL `companion_walk`) one permitted candidate can score +1 while
another scores -1 simultaneously, doubling the nudge's effective reach to `2 x WEIGHT`.

Fixed by deriving the weight from the weight tables themselves rather than picking a new constant
by hand: `learning.MIN_SINGLE_OBSERVATION_DELTA` enumerates every `expected_value` movement a
single `record` call can produce from a fresh key (every bare outcome, every `accepted` +
follow-through pairing, and every `accepted` + attended-follow-through + enjoyment triple) and
takes the smallest magnitude -- 0.017, from `accepted` + `partial` (with or without `okay`, which
leaves EXPERIENCE exactly at its own prior). `SOCIAL_DIMENSION_RANKING_WEIGHT` is now
`MIN_SINGLE_OBSERVATION_DELTA / 4` (0.0043): halved once for the two-sided worst case
(`2 x WEIGHT < 0.017` needs `WEIGHT < 0.0085`) and halved again for headroom against
`expected_value`'s own 3-decimal rounding. This is a computed expression, not a hardcoded number,
so a future retune of `_OUTCOME_WEIGHTS`/`_FOLLOW_THROUGH_WEIGHTS`/`_ENJOYMENT_WEIGHTS` keeps the
invariant true instead of silently invalidating it. Rejected alternative: a single flat rescale
(e.g. halving 0.15 to 0.075, matching the halved default baseline) -- rejected because it does not
generalise to the smallest real delta (`partial`'s 0.017), which a flat rescale would still
override.

Scope, stated precisely: this bounds a _single_ real observation against _no_ observation, the
case named above and pinned by
`test_social_nudge_cannot_override_a_single_real_acceptance`/
`test_social_nudge_cannot_lift_a_single_real_decline_to_the_top`
(`apps/api/tests/test_agent_integration.py`). It does not, and does not claim to, bound two
candidates that have each accumulated a long, nearly-tied history -- breaking that near-tie is
what this nudge exists for.

Verified unaffected: the grounding-guardrail and social-shape unit tests
(`test_agent_planner.py`, `test_preferences.py`) and the "Yes, tell me more" -> companion-walk
follow-through tests (`test_follow_through_api.py`, `test_outreach_content.py`) all still pass.
The default `GENTLE_NUDGE` selection on a fresh persona (no history, no stated SOCIAL preference)
is unchanged by both this ADR's split and this correction: all three candidates tie at whatever
the baseline is (0.5 before this ADR, 0.25 after), the SOCIAL nudge is exactly 0.0 for all three
either way (no stated preference to read), and the tie is broken the same way it always was -- by
`candidate.key`, alphabetically, landing on `gentle_nudge:chair_mobility` before and after every
change in this ADR. Confirmed by direct measurement (`build_repository`/`advance_to_intervention`
against a fresh in-memory database), not assumed.

**2. The evidence-view display silently changed meaning.** `evidence-view.tsx`'s "preference
learning" card renders `candidate_preference_scores` as a raw `Math.round(score * 100)%` under the
heading "Preference learning". A never-offered suggestion now reads 25% instead of 50%, and a
once-accepted one 33% instead of 67% -- with no copy change, an evaluator reads a neutral
"no data yet" candidate as one the system actively dislikes.

Fixed by making the label match what the number now means, rather than by changing what the
surface renders (`personal-world-model.tsx` only _sorts_ by this value and never prints it, so it
needed no change). The card's heading changed from "Preference learning, over already-permitted
options only" to "Expected fit, over already-permitted options only", and its body now states the
new neutral starting point explicitly: "An option with no history yet starts at 25%, not 50% --
two separate unknowns, would they take it up and would they enjoy it, multiplied together rather
than one." The alternative the review offered -- display the ENGAGEMENT posterior there instead,
keeping the product only for ranking -- was rejected: that would make the number shown no longer
the number driving the visible order (`personal-world-model.tsx`'s own sort, and this same card's
implicit ranking), which is a worse mismatch for an evaluator trying to read "why is X above Y"
from the percentages than a relabelled, honestly-scaled combined number is. This is the evaluator
surface (`/evidence`), not the senior one; the senior surface (`senior-view.tsx` and siblings)
shows no scores, percentages or deadlines today and this change adds none. `apps/e2e` was grepped
for any assertion on this card's text or percentages (`preference learning`, `already-permitted`,
`expected fit`, `%`) -- none exist, so nothing there needed updating. `pnpm install
--frozen-lockfile`, `web:typecheck` and `web:lint` all pass with no other changes required (no
`models.py` change, so no OpenAPI/TS-client regeneration).

**3. Two more places describe the old scale.** `docs/api.md` (the `AdvanceResponse.loop_trace`
paragraph, which names `preference_before`/`preference_after`/`candidate_preference_score`) and
`docs/observability.md` ("Decision evidence") now both state the 0.25 neutral baseline and link
to this ADR, so a reader comparing a value recorded before this change against one recorded after
it is warned rather than misled.

**4. The planning LLM was still being told the old semantics.** `agent/tools.py`'s
`get_candidate_options` description called `preference_score` "the transparent Beta-Bernoulli
acceptance estimate (0-1, higher means more often accepted)" -- exactly the single-posterior,
0.5-neutral reading this ADR replaced, handed to the model as fact on every planning call.
Reworded to say what is now true: it combines how often the option is taken up with how it went
once tried, 0.25 (not 0.5) is the neutral starting point before any history exists, and it only
reorders options the safety policy has already permitted. Checked and found clean: `planner.py`,
`intent_planner.py`, `guardrails.py`, and every recorded-LLM-response fixture and prompt/schema
test (`test_agent_planner.py::test_every_tool_is_strict_and_closed`, which checks schema shape,
not description text) contain no other description of this number -- `agent/tools.py` was the
only place it was written down for the model to read.

## Amendment (2026-09-13): ENGAGEMENT is reason-keyed, and the bound enumerates it

Accepted as an amendment rather than a new ADR: it changes nothing about the two-posterior split,
`expected_value`'s shape, or any public surface. It changes what one ENGAGEMENT observation is
worth, and it closes a hole in the bound this ADR's own "Lead review corrections" section opened.

**What changed.** `record` takes a fifth argument, `reason` -- the one-tap `DeclineReason` already
stored on `InterventionOutcomeRow` since declines first carried one, and until now read only by
the deterministic suppression guard (`_suppress_after_repeated_declines`, which has always known
that a `bad_day` decline must not count toward muting a candidate). `_preference_learners` now
selects that column and passes it through, so the posterior that actually _orders_ outreach sees
what the suppression ladder above it has always seen. A new `_DECLINE_REASON_WEIGHTS` table is
applied INSTEAD OF `_OUTCOME_WEIGHTS["declined"]`: `bad_day` and `already_active` are `(0, 0)`,
every other reason is exactly the bare decline's weight, and an unrecognised reason falls back to
the bare decline. `_FOLLOW_THROUGH_WEIGHTS["unable"]` moved from `(0, 1)` to `(0, 0.5)`.

**Why.** "Just a bad day" is a fact about the day. "I am already getting about" is a person
correcting the _sensor_ -- ground truth `policy.py` routes into data quality, not a verdict on the
suggestion. Both used to teach "this option is a poor fit" as hard as "it is not for me", so three
declines in one quiet week took a perfectly good candidate to a tenth of its starting value and
the demo's own reason chips actively mistrained the ranking. `unable` is the one follow-through
the product promises is never read as a statement about the person (`models.FollowThrough`); at a
full unit against the candidate it was the harshest answer on the list. Half a unit keeps the
direction ("offer something else next time") without matching a flat refusal.

**The bound.** `MIN_SINGLE_OBSERVATION_DELTA` is recomputed at import from the weight tables so a
retune cannot silently invalidate `SOCIAL_DIMENSION_RANKING_WEIGHT = MIN_SINGLE_OBSERVATION_DELTA
/ 4`. A reason-keyed table is a _second_ source of single-observation deltas, and
`_single_observation_deltas()` had no knowledge of it: today's reason weights are all either zero
or the bare decline's, so the minimum is unchanged at 0.017 (from `accepted` + `partial`), but a
future reason weight below that would have shrunk the real minimum while the computed constant
stayed put -- false in the **unsafe** direction, with
`test_social_nudge_cannot_override_a_single_real_acceptance` still passing. The enumeration now
carries a `declined x reason` arm, and
`test_a_retuned_reason_weight_smaller_than_todays_minimum_shrinks_the_enumerated_bound` injects a
hypothetical small weight and asserts the minimum follows it. `ResolvedPreference.weight` and
`social_shape_score`'s `[-1, 1]` Pydantic bounds are untouched, so the other half of the argument
still holds.

**Reason amendment, restated.** The senior screen records "Not today" first and offers the
optional reasons afterwards, so a reason arrives as a second POST and is stored as a superseding
append-only row. "One answer, one unit of evidence" is unchanged -- the amendment replaces the
original row rather than adding to it -- but the unit is no longer necessarily the same size, so
attaching `bad_day` to a decline already recorded now legitimately takes back what the bare
decline provisionally applied. `record_outcome`'s amendment branch therefore reads
`preference_before` _before_ the amendment lands instead of reporting the post-amendment value
twice, and its audit `learning_boundary` says "re-weights that single answer" rather than "the
posterior was left untouched", which had become false.

**`coordinator_resolved` and `activity_recovered`, decided.** Audit D-§11 calls both phantom.
Only one is. `coordinator_resolved` cannot reach the learner at all: `record_outcome` rejects it
("Coordinator outcomes must be recorded through case review") and `review_case` writes a
`CaseReviewRow` and an audit event, never an `InterventionOutcomeRow`. Its deliberate `(0, 0)`
therefore read as a chosen ranking weight for a path no data takes, and the test that asserted it
described that path. Both are gone; the value is named in
`_OUTCOMES_NEVER_REACHED_BY_THE_LEARNER` instead, the exhaustiveness guard over `OutcomeKind`
accepts either a weight or that name, and the fail-safe if such a row ever did arrive is
`record`'s silent no-op -- the same zero, reached by construction rather than by a decision nobody
made. `activity_recovered` is **not** phantom: `record_outcome`'s allow-list carries it, so a
client can post one today, and
`test_follow_through_api.py::test_activity_recovered_is_a_live_outcome_the_senior_route_accepts`
now pins that live path rather than leaving the entry justified by prose. Whether a recovery
should credit the _candidate_ with a full unit at all -- `docs/architecture.md` says it "is not
attributable to the offer" -- is a separate semantic question about what that weight means, not
about whether the path exists, and is deliberately left open here.

## What would change our mind

- If a future ops surface needs to show _why_ a candidate ranks where it does (not just that it
  does), `engagement_value`/`experience_value` should be added to `CandidateOption` and
  `OperationalMetrics` and regenerated through the OpenAPI/TS client pipeline -- deferred here, not
  rejected.
- If product research on real (non-synthetic) usage shows attendance-without-enjoyment should
  never be allowed to outrank a strongly loved, rarely-attended option -- i.e. Option C's
  penalty-only reading is actually the intended product behaviour -- that is a one-function change
  to `expected_value` (bounding the EXPERIENCE factor's contribution at 1.0) with no further
  restructuring needed, since the two posteriors are already separately tracked.
