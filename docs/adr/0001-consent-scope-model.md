# 0001. The consent scope model: search is not monitoring

Status: Deferred (2026-09-13). The proof of concept assumes the person has already consented to
sharing their non-sensitive activity data, so consent design is parked rather than decided. The
findings and the open questions below are kept as the starting point for when it is picked up;
`consent_scopes.py` stays because it changes no behaviour.

## Context

`ConsentEvidenceRow.active` is one boolean (`db_models.py:88-99`, `models.py:190/251/521-522`).
`repository._consent_active` reads the latest row _for the currently active scenario run_ (see
Context, item 6, for why that qualifier matters) and hands that single value to every consumer
that asks "is consent on?". The ticket that opened this ADR asked whether a senior's own search
("find me something nearby") should be gated by the same permission as proactive monitoring and
outreach ("Care+ noticed your activity dropped").

Reading every place the boolean is read or written (`policy.py`, `sql_repository.py`,
`baseline_confirmation.py`, `context_question.py`, `world_model.py`, the web senior/coordinator
surfaces, `docs/api.md`, `docs/data-and-privacy.md`) shows the codebase already answers this
question inconsistently in the sense that different call sites already implement _different_
rules against the same one boolean, without ever naming that they are different rules:

Line numbers below are cited only where a specific statement lives at a narrow, stable point
(schema columns, a short module); everywhere else this ADR names the function, which does not
drift the way a line number does. All were checked against this branch, not carried over from an
earlier draft.

1. **`policy.decide`'s `consent_active` parameter** — the first rung of the deterministic ladder.
   When false, every outreach decision becomes `SUPPRESS`: no nudge, no programme suggestion, no
   coordinator-review referral. `_close_open_cases_for_consent` additionally closes any review
   case already open, and `_withdraw_open_interventions` withdraws anything still waiting for a
   reply. `context_question.py` and `baseline_confirmation.py`'s `question_for` both refuse to ask
   their one question while this is false, because asking is itself a form of contact.

2. **`_apply_activity_decline` / `_apply_activity_enjoyment`** — folding a tap or an enjoyment
   report into an _inferred_ dimension preference. Both already check consent and return `[]`
   (nothing learned) when it is inactive, while leaving the response/enjoyment row itself on the
   record. The docstrings on both call this "pausing inference," distinct from blocking the
   action.

3. **`search_activities` and `respond_to_activity`** — a senior asking for something to do, or
   answering a listing they were shown. Neither function's own scope check calls `_consent_active`
   anywhere in its body. `main.py`'s route docstring for `search_activities` says why: "the ladder
   answers 'should we contact this person?', which is the wrong question here — they contacted
   us." `respond_to_activity` always records the response row and the audit event; only the
   _learning_ half, item 2 above, is conditional. `state_preference` (an explicit "prefer" /
   "avoid" / "forget") never checks consent either, and its docstring calls this deliberate: "a
   person's own belief about themselves outranks anything inferred from their taps."

4. **`_evaluate`'s call to `analyse_signal`** — the baseline, signal and data-quality computation
   that produces `PersonState.baseline` / `.signal` / `.attention_band`. This is an
   activity-pattern reading (a comparison against the person's own step-count history), never a
   health or wellness judgement, and Care+ must not be read as making one. The computation
   runs unconditionally, before consent is even read; only the _decision_ that follows (item 1) is
   gated. `attention_band` is derived from `severity` / `sustained_low_days` **or**
   `policy.decision == Decision.COORDINATOR_REVIEW` — not purely independent of the decision, as
   an earlier draft of this ADR said, but not fully determined by it either: the
   `severity >= 20 or sustained_low_days >= 2` branch that produces `WATCH` never looks at
   `policy.decision` at all, and the `severity >= 40 and sustained_low_days >= 3` clause inside the
   `REVIEW` branch is an independent path to the same band. So it can still read `watch` or
   `review` for a person who has withdrawn consent (whose `policy.decision` is always `SUPPRESS`),
   through the severity/persistence path alone.

   **Who can actually see it, checked route by route rather than assumed:**
   - `GET /v1/people/{id}/state` and `GET /v1/people/{id}/world-model` (`main.py`'s
     `person_state` and `person_world_model`) both require the `Senior` role
     (`current_user: Senior`, resolved by `require_senior` in `auth.py`). Under real auth
     (`AUTH_ENABLED=true`) a Coordinator token is rejected with 403 by `require_senior` itself,
     before `main.py`'s `_check_person_scope` ever runs. **A real Coordinator cannot fetch
     `attention_band` for anyone, including a person who has withdrawn consent** — it is
     Senior-scoped, not coordinator-scoped.
   - The one surface where `attention_band` _is_ visible to a caller other than the person
     themselves is the demo/operator "Overview" screen (`apps/web/components/overview-view.tsx`'s
     use of `PersonCard`, `apps/web/components/silverloop/person-card.tsx`). It only works because
     `AUTH_ENABLED=false` makes `require_senior` hand every caller the same synthetic senior
     identity and `_check_person_scope` skips the check entirely (its own docstring: "Nothing is
     scoped when authentication is off"). This is a sanctioned-demo artifact, not a
     Coordinator-role capability, and should not be read as "the coordinator sees the band."
   - A real Coordinator does, however, already see two other kinds of per-person, consent-
     independent activity data: `GET /v1/coordinator/people/{id}/outreach-history`
     (`main.py`'s `coordinator_outreach_history`, `Coordinator` role, **no per-person scope check
     at all** — any `person_id` is accepted) returns `OutreachSummary` rows carrying
     `FollowUpObservation` (`models.py`), a derived step/percentage change in the days after one
     piece of outreach; `list_outreach_summaries` (`sql_repository.py`) has no consent check
     anywhere in its body, and the Care Team UI (`apps/web/components/care-team-view.tsx`) renders
     it per person via a `PersonaSwitcher` regardless of that person's consent. Separately,
     `GET /v1/coordinator/queue` and `GET /v1/cases/{id}` (`main.py`'s `coordinator_queue` and
     `get_case`) return every `ReviewCase` regardless of status via `list_cases` / `get_case`
     (`sql_repository.py`), with no consent check on read — a case
     `_close_open_cases_for_consent` auto-closed on withdrawal stays visible with its full derived
     summary text indefinitely; only _writing_ a new review is refused, in `review_case`. The Care
     Team view renders resolved cases alongside open ones.

   So the precise finding is: **`attention_band` itself is not exposed to a real Coordinator at
   all** (Senior-scoped only; its apparent coordinator visibility is a demo-mode, auth-disabled
   artifact). A real Coordinator does already see other per-person, consent-independent activity
   data today — outreach follow-up figures and case summaries — unaffected by the person having
   withdrawn consent. See "Needs human decision" below, which also questions whether that
   per-person visibility should exist at all, independent of consent.

5. **The ambient context fetch inside `advance`** — rain and public holiday lookups, read via
   `ExternalContextProvider.fetch`. Runs unconditionally; `docs/WAYFINDER.md` already flags this
   as an accepted gap under §49 ("Consent does not gate the external-context fetch... no person
   identifier leaves the process, so the privacy harm is nil").

6. **Consent is scoped by `run_id`, not by person, and a demo reset silently re-enables it.**
   `ConsentEvidenceRow` (`db_models.py:88-99`) carries a `run_id` foreign key, and `_consent_active`
   reads only the latest row _for that run_ (`.where(ConsentEvidenceRow.run_id == run_id)`). A
   scenario reset (`reset()`) ends the previous run (`ScenarioRunRow.active = False`) and starts a
   brand-new one with its own `run_id`, and unconditionally inserts a fresh
   `ConsentEvidenceRow(active=True, reason="Synthetic demo consent fixture activated on reset.",
source="synthetic_fixture")` scoped to that new run. A withdrawal recorded against the old run
   has no corresponding row in the new run's history at all — there is nothing to read as
   withdrawn, so the new run starts with consent on regardless of what the person decided in the
   run before it. This was not stated anywhere in this ADR's first draft, which said only that
   `_consent_active` reads "the latest row," implying a single per-person history rather than a
   per-run one. Contrast **ADR 0004** (`docs/adr/0004-run-scope-activity-dimension-preferences.md`),
   where a _standing_ `senior_statement` preference deliberately keeps `run_id = None` so it is
   never run-scoped and survives a reset unchanged — the opposite choice, made deliberately, for a
   different kind of record. Consent has no such carve-out. See "Needs human decision" below.

The schema backing all of this is one `Boolean` column, scoped to one `run_id`, with no notion of
scope at all — so today's behaviour is six different hand-written rules against the same value on
two undeclared axes (which permission, and which run), not a modelled scope. That is the actual
problem this ticket names: not that search is wrongly gated (it is not — the code already gets
that right, and
`test_activity_responses.py::test_withdrawing_consent_pauses_inference_but_not_the_person_s_own_voice`
already pins it), but that nothing in the codebase said _why_ these call sites disagree, or that
withdrawal does not survive a reset, so the next person to touch consent had no way to tell a
deliberate asymmetry from a bug.

Evidence run this pass (architecture-review revision, on top of `feat/wayfinder-frontier`):
`uv run pytest` → **925 passed, 8 skipped** (924 passed, 8 skipped before adding this revision's
one new test); `uv run python -m silverloop.scenarios ../../scenarios` → **15/15**;
`.../scenarios/holdout` → **5/5**; `uv run ruff check .` and `uv run ruff format --check .` →
clean; `pnpm exec prettier --check docs` → clean. All confirm this revision changes no observable
behaviour — it corrects and extends what the ADR says, and adds one test pinning the reset finding
above, without touching `policy.py` or any scenario outcome.

## Options considered

**A. Leave the boolean exactly as-is, document nothing.** Rejected — this is the status quo the
ticket was opened against. The rules above keep drifting independently (new code checking
`_consent_active` has no way to know which permission it is actually answering, or that it is
reading a per-run history rather than a per-person one), and the sibling ticket ("does a tap while
consent is withdrawn count as engagement?") stays unblocked on nothing, because there is no
written model to check its answer against.

**B. Add a `scope` dimension to `ConsentEvidenceRow` now (one row per scope, or a bitmask column)
and let a senior grant/withdraw each independently.** This is the "real" fix and the one a mature
product needs. Rejected _for this pass_ only because it needs a migration, and this ticket may not
add one (see the frontier-track constraint). Specified below as the deferred follow-up.

**C. Name the scopes as pure functions over the existing boolean, route the call sites that
already implement per-scope rules through that one lookup, and defer the schema change with the
mapping fully specified.** Chosen. It is reversible (one new module, `consent_scopes.py`, with no
storage), it makes today's already-correct-but-unnamed behaviour explicit and testable in one
place, and it gives the eventual schema change (Option B) a single function to change rather than
several scattered `if not self._consent_active(...)` sites to hunt down and reinterpret.

**D. Collapse `search` and `outreach` onto one permission (i.e. make search need consent too).**
Rejected on product grounds, not just because it would be a behavioural change this track may not
make: a person who wants to keep browsing programmes but stop being watched has a legitimate,
common preference (the AAC coordinator interviews this project is grounded in surface exactly this
complaint about other outreach tools), and the ladder's own framing — "should we contact this
person?" is the wrong question when they contacted us — is correct. `docs/api.md`'s existing line,
"Consent pauses inference... a search is still answered and a tap is still recorded," already
states this product decision; this ADR keeps it and gives it a name.

## Decision

Adopt five named consent scopes, encoded as `ConsentScope` in
`server/src/silverloop/consent_scopes.py`, and a pure function `scope_permitted(scope, *,
consent_active)` that states what the one stored boolean means for each of them **today**:

| Scope                   | Gated by the stored boolean?                                                                   | What it covers                                                                                                                                                                                                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PROACTIVE_OUTREACH`    | **Yes**                                                                                        | `policy.decide`'s consent gate, the context question, the baseline-confirmation question, closing/refusing coordinator review cases, withdrawing open interventions, the weekly contact cap not spending on a withdrawn offer.        |
| `PREFERENCE_LEARNING`   | **Yes**                                                                                        | Folding a decline reason or an enjoyment report into an _inferred_ `DimensionPreference` (`_apply_activity_decline`, `_apply_activity_enjoyment`).                                                                                    |
| `USER_INITIATED_SEARCH` | **No — always permitted**                                                                      | `search_activities`, `respond_to_activity`'s recording of the response itself, `state_preference` (explicit prefer/avoid/forget).                                                                                                     |
| `PROACTIVE_MONITORING`  | **No — today.** Whether it _should_ be is an open question — see "Needs human decision" below. | `analyse_signal`'s baseline/signal/quality computation (an activity-pattern reading, never a health judgement) and the resulting `attention_band`.                                                                                    |
| `EXTERNAL_CONTEXT`      | **No — always permitted**                                                                      | The rain/public-holiday fetch in `advance`. Carries no person identifier; named as a scope because a future per-category consent model should cover it (`docs/WAYFINDER.md` §49), not because withholding it protects anything today. |

Default on grant (`consent_active → true`): every scope permitted; `PROACTIVE_OUTREACH` resumes
for future decisions (it is not retroactive — nothing withdrawn is re-sent); `PREFERENCE_LEARNING`
resumes inferring from new taps.

Default on withdrawal (`consent_active → false`): `PROACTIVE_OUTREACH` suppressed immediately,
existing open interventions withdrawn, existing open review cases closed;
`PREFERENCE_LEARNING` paused for new taps only — nothing already learned is deleted, and an
explicit statement through `state_preference` is never affected because it is not this scope.
`USER_INITIATED_SEARCH`, `PROACTIVE_MONITORING` and `EXTERNAL_CONTEXT` are unaffected.

**Legacy boolean mapping.** There is exactly one stored signal today, so both gated scopes read it
directly and identically; the model does not (yet) let a person withdraw one without the other.
That coupling is named as the thing Option B's migration would break apart, not hidden. A second,
orthogonal axis is also unmodelled: that signal is scoped per `run_id`, not per person (Context,
item 6), so "the stored boolean" is really "the stored boolean for whichever run is currently
active." Option B's migration must decide both axes, not only the scope one — see "Needs human
decision" below.

**Auditing.** `ConsentEvidenceRow` records `active`, `reason`, `actor`, `source` and
`recorded_at` per change, and every action a scope permits or refuses already writes its own
audit event referencing the outcome (`consent_updated`, `case_review_recorded`,
`activity_response_recorded`'s `inference_paused` field, etc.). No new audit trail is added by
this ADR: the two gated scopes are one boolean, so there is nothing to attribute independently
yet. A future scope-scoped consent needs the audit event itself to name which scope changed —
specified in the deferred migration below.

**Implementation shipped now (no schema change):** `server/src/silverloop/consent_scopes.py`
(the enum and `scope_permitted`), with four call sites routed through it: the two
`PREFERENCE_LEARNING` reads that gate learning itself (`_apply_activity_decline`,
`_apply_activity_enjoyment`), a third `PREFERENCE_LEARNING` read that only feeds an audit label
rather than gating anything (`respond_to_activity`'s `inference_paused` value, added in this
revision — it was still calling `_consent_active` directly, which this ADR's own "one place"
claim should not have missed), and the one `PROACTIVE_OUTREACH` call site (`_evaluate`'s call into
`policy.decide`). `policy.py` itself is untouched — its `consent_active: bool` parameter and its
decisions are unchanged; the repository now states, at every place it computes that argument,
which scope the argument means. `USER_INITIATED_SEARCH`, `PROACTIVE_MONITORING` and
`EXTERNAL_CONTEXT` call sites are _not_ touched, because they correctly never call
`_consent_active` today — routing them through `scope_permitted` would only wrap a call that does
not exist.

**Deferred (needs a migration, out of scope for this track):** a `scope` or per-category
representation on `ConsentEvidenceRow` — e.g. either a small `ConsentScopeStateRow(person_id,
scope, active, ...)` table (one row per scope, append-only like the existing table) or a
`scope: Mapped[str]` column added to the existing table with `NOT NULL DEFAULT
'proactive_outreach+preference_learning'` for backfill, plus a second write path in `set_consent`
that accepts a scope and only updates that scope's current value. `ConsentRequest` (`models.py`)
would need an optional `scope: ConsentScope | None` field (defaulting to "both gated scopes," to
keep `POST /v1/people/{id}/consent` backward compatible for any caller that still sends only
`active` + `reason`). `PersonState.consent_active` would become derived as "is
`PROACTIVE_OUTREACH` permitted," so every existing consumer of that field keeps working unchanged.
This migration would also have to settle whether consent stays run-scoped or becomes
person-scoped (Context, item 6; "Needs human decision" below) — the two questions are separable in
principle but land in the same table and the same `set_consent`/`reset()` code, so one migration
should decide both rather than two migrations disagreeing about what "the latest row" means. This
is deliberately not attempted here: it is a genuine API and schema change (`ConsentRequest`,
`ConsentEvidenceRow`, a new repository read/write path) and this track may not add a migration.

## Consequences

- `consent_scopes.py` is the one place future code should ask "is X permitted while consent is
  Y", instead of reading `_consent_active` directly and re-deriving the rule inline. Four call
  sites already do; the rest of the file's module docstring names the two more (`policy.py`'s own
  parameter, `baseline_confirmation.py`'s check) that were left alone because touching them would
  mean editing `policy.py` or duplicating a check that already reads `PersonState.consent_active`,
  which is itself already `PROACTIVE_OUTREACH`'s value.
- The sibling ticket ("does a tap made while consent is withdrawn count as engagement?") is
  answered by this model, with one consequence that must be stated rather than assumed away: a
  tap is always `USER_INITIATED_SEARCH` (never gated, always recorded as an audited fact —
  `ActivityOfferResponseRow`, `activity_response_recorded`), and it only becomes
  `PREFERENCE_LEARNING` evidence (an `inferred` `DimensionPreference`) when `PREFERENCE_LEARNING`
  is permitted. **But it is not only recorded — it is read back.** `_activity_engagement`
  (`sql_repository.py`) rebuilds every listing's engagement/repetition figures straight
  from `ActivityOfferResponseRow` (and follow-through/enjoyment rows) for the whole run, with no
  consent filter, and `rank_candidates_with_breakdown` (`activity_search.py`, weighted by
  `RANKING_WEIGHTS`) feeds that straight into every later search's ranking: a "not for me" recorded while consent was withdrawn
  still starts the `DECLINE_COOLDOWN_DAYS` (14-day) cooldown on that listing, and an "interested" /
  "went" / "enjoyed" tap still adds its weight to the engagement score, for searches run after
  consent is restored. So: **yes, it counts as engagement, in the fullest sense — it is recorded,
  and it shapes what this person is shown next**, whether or not `PREFERENCE_LEARNING` was
  permitted at the time of the tap. Only the _dimensional_ inference (item 2) is paused; the
  per-listing engagement/repetition factors (a distinct mechanism, never gated by any scope in
  this ADR) are not. No new code is needed to implement this answer, but the answer itself is more
  consequential than "it happened, and the record says so" — it is a decision about later
  ranking behaviour, and it deserves its own explicit sign-off if the sibling ticket is picked up.
- `docs/api.md`'s existing "Consent pauses inference" paragraph and `docs/data-and-privacy.md`'s
  retention paragraph both already describe scopes 2 and 3 correctly in prose; this ADR is the
  first place all five are named together and cross-referenced from `consent_scopes.py`.

## Needs human decision

Three questions this ticket and the later coordinator work surfaced are not decided by anything
above. What is settled (the `ConsentScope` model, `scope_permitted`, and the four routed call
sites) does not depend on any of the answers — none of it changes `attention_band`'s visibility,
how `reset()` treats a withdrawal, or what the roster shows. All three are presented neutrally,
for a human to decide, not as this track's recommendation stated as fact.

### A. Coordinator visibility of derived activity data — an aggregates-only question first, a consent question second

**The verified facts** (see the route-by-route evidence under Context, item 4): a real Coordinator
cannot fetch `attention_band` for anyone — `GET /v1/people/{id}/state` and `.../world-model` are
Senior-scoped, and a Coordinator token is rejected before any per-person check runs. Its apparent
visibility on the "Overview" screen is a demo-mode artifact of `AUTH_ENABLED=false`, not a
Coordinator-role capability. A real Coordinator does already see two other kinds of per-person
activity data regardless of that person's current consent: `FollowUpObservation` step/percentage
changes via outreach history, and full review-case summaries (including ones auto-closed on
withdrawal), both unfiltered by consent on read.

**This is not only a consent question, and treating it as one first would answer the wrong
question.** The product already has a standing, decided rule for care-team visibility, stated in
`docs/api.md` and echoed in `docs/WAYFINDER.md`'s decision table: coordinator visibility into the
senior's own search loop is **aggregate only** — "that a senior self-initiates and how often,
never the content of what they asked for." `FollowUpObservation`'s per-listing step/percentage
change is exactly the kind of per-person "content," not a count, that rule was written to keep off
the coordinator surface — it is a different loop (outreach, not search), so the rule does not
apply to it by its own letter, but the reasoning behind the rule applies just as well: a coordinator
reading "went for a walk, steps up 12% after this suggestion" for one named person is not an
aggregate any more than reading what they searched for would be. Whether that reasoning should be
extended to `coordinator_outreach_history` is the prior question; whether it should also depend on
current consent is downstream of it, because if the answer to the aggregates question is "no
per-person figures at all," consent status stops mattering for that route. The case queue
(`list_cases`/`get_case`) is different in kind: a coordinator reviewing one open case necessarily
sees that one person's derived summary, which is the queue's entire purpose, so an aggregates-only
argument does not apply to it the same way — its open question stays a consent question (should a
case already closed for consent withdrawal keep surfacing that summary indefinitely on read).

**Options, laid out neutrally** (now split by which question they answer):

- **(a) Keep computing `PROACTIVE_MONITORING` internally, but withhold every per-person reading
  from a Coordinator while that person's `PROACTIVE_OUTREACH` is withdrawn.** Concretely: filter
  `list_outreach_summaries` and `list_cases`/`get_case` (or redact their derived figures) for a
  person whose current consent is inactive, in addition to whatever `attention_band` fix a future
  Option B scope split would add. Computation continues so a review case already open stays
  correct and re-baselining on re-consent has continuity. This answers the consent question only,
  and leaves the aggregates-only question about `coordinator_outreach_history` open even for a
  person whose consent is active.
- **(b) Status quo.** Computation continues, and today's two real (non-demo) Coordinator-visible
  surfaces — outreach follow-up figures and case summaries — keep showing derived activity data
  for a withdrawn person, exactly as now.
- **(c) Stop `analyse_signal` while `PROACTIVE_OUTREACH` is withdrawn, and re-baseline from scratch
  on re-consent.** No new signal is computed at all until consent returns, so there is nothing new
  to show or to feed a review case; the baseline restarts cold rather than resuming continuity.
- **(d) Answer the aggregates-only question first:** decide whether `coordinator_outreach_history`
  should ever return per-listing `FollowUpObservation` figures, or only an aggregate ("how often
  outreach led to activity picking up," with no per-listing detail) — matching the standing rule
  for the search loop. If the answer is "aggregate only," the consent question for that route
  becomes moot, and only the case-queue read-after-close question (part of options a-c) remains.

**Recommendation (not a decision): (d) first, then (a) for whatever remains a per-person read.**
The aggregates-only principle already exists in this product for exactly this reason (visibility
into a senior's private activity, even without content, being enough to feel like being watched);
applying it consistently to `coordinator_outreach_history` is a smaller, more defensible move than
deciding a new consent rule for a route whose level of detail may not have been meant to exist at
all. For whatever per-person detail remains after that (at minimum, the case queue), recomputing
nothing (option c) risks a coordinator safety net going blind exactly when a case was already open
and unresolved, so (a) — computation continues, but nothing per-person reaches a Coordinator once
`PROACTIVE_OUTREACH` is withdrawn — is preferred over status quo (b) or (c).

**This is marked "Needs human decision," not decided,** because (A) trades off a real safety-net
argument (a coordinator who already has an open case losing sight of someone) against a real
privacy argument (surfacing derived facts about a person after they said stop, or surfacing
per-person detail a standing aggregates-only rule may already forbid), and that trade is a product
call this track should not make unilaterally.

### B. Should a consent withdrawal survive a demo reset?

**The verified facts** (Context, item 6): `ConsentEvidenceRow` is scoped by `run_id`, not by
person. `reset()` ends the active run and starts a new one with a fresh `active=True` fixture row
scoped to that new `run_id`; a prior withdrawal has no row in the new run's history at all. So
today, every reset silently re-enables consent, regardless of what the person decided in the run
before it. Contrast **ADR 0004**, where a _standing_ `senior_statement` preference deliberately
keeps `run_id = None` specifically so it survives a reset — the product has already made "this
kind of record should outlive a reset" a real, precedented choice for preferences, and has never
made that choice, in either direction, for consent.

**Options, laid out neutrally:**

- **(e) Consent survives a reset, the way a standing preference does.** Make consent person-scoped
  (`run_id = None`, or read across all of a person's runs for the newest row) rather than
  run-scoped. A demo reset would no longer touch consent at all; a withdrawal made before a reset
  stays withdrawn after it, and `reset()`'s "Synthetic demo consent fixture activated on reset" row
  would only be written for a person who has never recorded a consent decision at all (new-person
  provisioning), not unconditionally.
- **(f) Status quo.** Consent stays run-scoped; a reset always re-enables it, matching how the
  simulated calendar and most of a run's derived state (interventions, outcomes, offer responses)
  already reset with the story.
- **(g) Make reset ask, or refuse, rather than silently override.** `reset()` could require an
  explicit flag to carry a prior withdrawal forward versus discarding it, so neither behaviour is
  silent.

This ADR does not recommend between these: unlike Section A, there is no existing product rule
this can be checked against — ADR 0004 decided the analogous question for preferences, not for
consent, and reasonable product intent could go either way (a reset is explicitly a "start the
story over" action in this demo product, which argues for (f); a withdrawal is explicitly a
standing instruction in every other surface's own language — "you can turn suggestions back on
here at any time," never "until the next reset" — which argues for (e)). `test_consent_boundary.py`'s
`test_a_demo_reset_reactivates_consent_after_a_prior_withdrawal` pins option (f) as today's
behaviour, without endorsing it, so whichever option is chosen has a test to change on purpose
rather than a behaviour to rediscover.

### C. The coordinator roster shows one attention band per named person

`GET /v1/coordinator/people` (added 2026-09-13 with the case clock and override memory) lists
every person for the care team with an attention band as a **word** (never a figure), consent
standing, a tracker-not-synced count over the last seven days, an open-case flag and the last
decision class, so that people who need nothing still appear as "No attention needed" rather
than disappearing. A band per named person is derived activity data of exactly the kind §A
discusses; it is coarser than the outreach-history figures, and it exists because a roster with
no signal at all cannot tell a coordinator whom to look at. Whether a band word per person is
inside the aggregates-only rule, or is the first thing §A's decision should narrow, is a human
call. Recorded here, not decided; the roster ships with the band because the alternative was a
roster that lists nobody as fine.

## What would change our mind

- If a real senior interview or the coordinator team surfaces a request to control
  `PROACTIVE_MONITORING` and `PROACTIVE_OUTREACH` independently (e.g. "let the coordinator watch
  for a safety net, but never message me"), Option B's migration should be built next; the mapping
  table above already specifies its shape.
- If `EXTERNAL_CONTEXT` is ever extended to carry anything person-identifying (e.g. a home
  postcode sent to a weather API), it stops being "no privacy harm to withhold" and must move into
  the gated column of the table above before that data leaves the process.
- If evidence shows the ungated `USER_INITIATED_SEARCH` path is being used to route around a
  withdrawal (e.g. a client re-deriving outreach-shaped nudges from search results), that is a
  product abuse case this ADR does not currently defend against and would need its own gate.
- If this product ever moves past being a single-session demo (persistent accounts across visits,
  not a resettable scenario run), question B's premise changes: "does a reset re-enable consent"
  stops being a demo-ergonomics question and becomes "does anything ever re-enable consent without
  the person asking," which only option (e) or (g) can answer safely.
