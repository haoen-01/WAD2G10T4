# Care priorities — who a caregiver should follow up with first

> **Removed in step 7.** `GET /v1/coordinator/priorities`, `triage.py` and their tests were removed
> with the other routes no screen used (`docs/research/aac-route-removal.md`). This page is kept
> as the record of what the feature was; nothing below describes running code any more.

Delivered 2026-09-15 on `test/main` in commit `2f252b6`. This page covers what the feature does,
why it is safe, where its thresholds come from, and how to demo it.

## The problem it answers

A caregiver or AAC coordinator looks after many seniors. At the start of a shift their question is
not "which cases are open"; it is **"who do I follow up with first, how soon, and what should I know
before I call?"**

Care Team could answer only part of that. The queue showed people with a review case, and the
roster showed everyone as an unordered band word. That roster was deliberately built never to rank
anyone (see [the decision this reverses](#the-decision-this-reverses)).

The care-priority board answers the full question:

- It ranks the whole caseload in follow-up order.
- It pulls out the **top-k** people to follow up with first (3, 5 or 10).
- For each person it gives a one-line reason, a suggested human approach, and the specific things
  to take note of before reaching out.

## What it is not

Care+ is **not a medical or emergency service**, and this board keeps that boundary:

- **It reads daily activity only**: steps, active minutes and tracker wear-time. It never uses
  heart rate or SpO2, and makes no diagnosis, risk prediction or fall detection.
- **The windows are outreach timeframes, not triage.** Daily data cannot support anything finer
  than a day, so there is no "urgent" and no "within the hour".
- **The board never contacts anyone.** It is read-only: opening it writes nothing, sends nothing and
  schedules nothing.
- **Every board carries a boundary note:** _"Not an emergency or medical service. These priorities
  come from daily activity patterns only, and Care+ cannot judge anyone's health or safety. If
  you are worried about someone's immediate safety, call 995."_
- **It is rules only.** No language model orders anyone or writes any sentence. Every headline and
  note is a fixed template, so the feature works identically with `LLM_ENABLED=false`.

## The follow-up windows

| Window                  | Shown when                                                                                                                                                                                                                                                                        | Suggested approach                                                                                  |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| **Reach out today**     | A review case the policy opened is still unresolved (the policy opens one at the person's review setting: by default more than 40% below their own usual for 3+ valid-wear days, a coordinator-approved setting within fixed bounds, and always at 60%+ for 3 days; see ADR 0008) | Call or visit today; ask in your own words how their week has been; record the decision on the case |
| **Check in within 48h** | The policy already permits outreach: a programme suggestion (25%+ below for 2 days), or a gentle nudge whose recent messages got no reply or were declined                                                                                                                        | A friendly check-in; ask what would make getting out easier rather than repeating the suggestion    |
| **Keep an eye on**      | A sensitive threshold fired, or a safety rule is holding outreach back                                                                                                                                                                                                            | No contact needed yet; look again after the next reading                                            |
| **No action needed**    | Within their usual range                                                                                                                                                                                                                                                          | Nothing to do                                                                                       |
| **Set aside**           | Consent withdrawn, or the tracker reading is too thin to interpret                                                                                                                                                                                                                | Respect their choice / nothing to act on from the tracker                                           |

An acknowledged case (a coordinator chose to keep monitoring) is only "Reach out today" once it is
[due back](#the-due-back-rule); before that it is "Keep an eye on".

**Top-k** is taken only from the two contact windows. It is never padded with people who are merely
being watched, so an empty top-k is honest good news.

## The safety ceiling: why no guardrail is overridden

The board is a **reading of decisions the policy ladder (`policy.py`) already made**. It is never a
second policy. The one-way ceiling:

1. **Contact windows come only from permitted decisions.** "Reach out today" needs an unresolved
   case, and only `COORDINATOR_REVIEW` opens one. "Check in within 48h" needs a
   `PROGRAMME_SUGGESTION`, or a `GENTLE_NUDGE` that did not land.
2. **Sensitive thresholds never create contact.** They only place someone on "Keep an eye on" and
   break ties inside a window.
3. **The board uses the decision that was recorded, not a fresh re-run.** Re-running the ladder at
   read time is not the same decision:
   - it skips the downgrades `advance()` applies (a muted suggestion or stale programme evidence
     becomes `NO_ACTION`);
   - it counts the day's own intervention against the weekly cap.
4. **A hold that arises after the decision wins.** The person accepting the suggestion the same day,
   explaining their week, or withdrawing consent overrides the recorded decision.

How each gate on the ladder is respected:

| Policy gate                               | Effect on the board                                                                                            |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Consent withdrawn                         | Set aside, no notes, never in top-k; overrides even an open case (withdrawal also closes the case)             |
| Data quality / confidence                 | Set aside as "tracker reading unclear", unless a review case is already open (see the exception below)         |
| Person's own explanation for a quiet week | Never a contact window, even with an open case; the headline is neutral so the explanation is not revealed     |
| Rain context                              | Never a contact window, even with an open case                                                                 |
| Baseline too small to interpret           | Never a contact window, even with an open case; a 600-step change is impossible on a sub-500-step baseline     |
| Weekly contact cap                        | "Keep an eye on", with the note that more contact risks becoming pressure; also caps an open case              |
| Accepted-outreach cooldown (3 days)       | "Keep an eye on", with the note to give them space; also caps an open case                                     |
| Review already answered by a human        | "Keep an eye on"; the board does not ask the caregiver to reach out again                                      |
| Review acknowledged, not yet due back     | "Keep an eye on" until the case's review day; then back to "Reach out today" (see [groups](#care-team-groups)) |

**The one stated exception.** An open review case stays at "Reach out today" on a day the tracker
was not worn. The case was opened on earlier, readable days, and an unworn tracker does not retract
it. The board still makes no claim about that unreadable day.

## Care Team groups

Each row also says which part of the Care Team workflow the person belongs in. The server decides
this in `triage.py`, from the same facts as the follow-up window, so the group and the window can
never contradict each other. The web app only maps the enums to labels and never re-derives the
placement from cases, outreach history or proposals.

| `care_team_group`     | `care_team_group_reason`      | When                                                                   |
| --------------------- | ----------------------------- | ---------------------------------------------------------------------- |
| `no_attention_needed` | `consent_withdrawn`           | Consent is withdrawn (checked first, as the policy ladder checks it)   |
| `no_attention_needed` | `tracker_unclear`             | The tracker reading cannot be interpreted and no case is unresolved    |
| `needs_judgement`     | `open_case`                   | A review case is waiting for its first review                          |
| `needs_judgement`     | `monitoring_due_back`         | An acknowledged case has reached its review day                        |
| `silverloop_handling` | `monitoring_until_review_day` | An acknowledged case has not reached its review day                    |
| `waiting_for_senior`  | `awaiting_reply`              | No unresolved case, and an outreach offer is still waiting for a reply |
| `silverloop_handling` | `keep_an_eye_on`              | Otherwise, the window is "Keep an eye on"                              |
| `needs_judgement`     | `check_in_suggested`          | Otherwise, the window is "Check in within 48h"                         |
| `no_attention_needed` | `nothing_needed`              | Otherwise                                                              |

The rows are checked in that order and the first match wins. How the groups sit with the windows:

- "Reach out today" is only ever `needs_judgement`.
- "Check in within 48h" with no unresolved case and no reply awaited is `needs_judgement`
  (`check_in_suggested`): it asks a person to check in within two days, which Care+ cannot do for
  them. It is the one `needs_judgement` reason with no `open_case_id`.
- `silverloop_handling` is never "Reach out today" or "Check in within 48h", and `waiting_for_senior`
  is never "Reach out today".
- `no_attention_needed` is always "No action needed".
- An open case held back by a safety rule today is still `needs_judgement`, at "Keep an eye on":
  review the case before contacting them.

The row's other workflow fields:

| Field                            | Meaning                                                                                                     |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `open_case_id`                   | The unresolved case (open or acknowledged) the group refers to                                              |
| `review_back_on_day`             | That case's review day (simulated), or `null` when there is no case or no day was recorded                  |
| `awaiting_reply_until`           | The latest last-day-of-waiting across offers still open; the same value the person's outreach history shows |
| `review_timing_proposal_waiting` | A proposed review-timing change for the person is waiting for a coordinator's decision                      |

When consent is withdrawn all four are empty (`null` or `false`). Withdrawal closes the case and the
open offers, and a review-timing change cannot be approved without consent.

### The due-back rule

A case is **due back** when it has a recorded review day and that day is on or before the row's
`as_of_day`. One predicate, `triage.case_due_back`, decides it everywhere: the group, the headline,
the "come back to the queue" note and the reading order.

**A case with no recorded review day is not due back.** Only a case opened before the case clock
existed has no day, and the repository reports that day as "not recorded" rather than inventing
one. So an open case of that kind still needs judgement, as every open case does. An acknowledged
one stays `silverloop_handling` with `review_back_on_day: null` and the headline "Care+ is
monitoring until it is resolved". It stays on the board and in the case queue, and a coordinator can
still resolve it. This matches the board's earlier ordering, which never treated such a case as past
its day.

## Thresholds, set as low as the evidence allows

The user brief asked for thresholds "as low as possible" and grounded in the literature. They sit
in `triage.py`, and the board shows them to the caregiver under **How this order is set**.

| Threshold            | Value                                                    | Source                                                                                                                                                                | Used for                             |
| -------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| Early dip            | ≥ 10% below personal usual **and** ≥ 600 steps/day lower | 600-1,100 steps/day was the minimal important difference in Demeyer et al., _PLoS One_ 2016 (adults with COPD). The lower bound is used only as a **noise floor**     | Keep an eye on                       |
| Slow drift           | ≥ 20% below the anchored reference (and ≥ 600 steps)     | Same size as the policy's gentle-nudge rung, applied to the earliest settled routine, which a rolling baseline absorbs                                                | Keep an eye on                       |
| Persistence          | 2+ low valid-wear days in a row                          | The existing watch band                                                                                                                                               | Keep an eye on                       |
| Activity level bands | under 3,500 steps/day; under 5,000 steps/day             | Tudor-Locke & Bassett, _Sports Med_ 2004 (under 5,000 is described as sedentary); Tudor-Locke et al., _IJBNPA_ 2011 (ranges described for older adults, 3,500-10,000) | Ordering inside a window, and a note |
| Unreadable day       | under 8 hours of wear                                    | Existing data-quality gate (`quality.py`)                                                                                                                             | Set aside                            |

**Why two floors for the early dip.** A 10% dip on its own is within most people's day-to-day noise.
Requiring a 600-step absolute change as well keeps the watch list from filling with noise, which
would teach a caregiver to ignore it. It also means a tiny baseline can never trip the flag,
consistent with the policy's small-baseline gate.

**Honest limits of the sources.**

- The 600-step figure comes from a COPD population, not from general older adults. It is a
  defensible noise floor, not a validated clinical threshold for this caseload.
- The step-count bands describe activity levels. They are never presented as a health judgement.

## Ordering inside a window

The ordering is lexicographic, and every term is a named fact the notes can state. It is
deliberately **not a weighted score**, because a score can only be argued with by reading its
weights.

1. An open case waiting for first review, before an acknowledged one.
2. A case [due back](#the-due-back-rule): past the day Care+ said it would come back to the
   queue.
3. More consecutive low valid-wear days.
4. A larger change band (more than 40%, more than 25%, early dip or drift).
5. Lower daily activity (under 3,500, then under 5,000 steps).
6. More recent Care+ outreach that got no reply or was declined.
7. Longer in review.
8. More days the tracker may not have synced.
9. Name, then id, as a stable tie-break.

## "Take note": the pointers for better human intervention

Each row carries plain sentences, chosen by rules, that help the caregiver prepare:

- **Persistence:** "Below their usual on 3 valid-wear days in a row."
- **Change, as a band:** "Activity is well below their own usual level (more than 40% lower)."
- **Activity level:** "Their latest daily activity is under 3,500 steps… A smaller change matters
  more here."
- **What Care+ already tried:**
  - "1 recent Care+ message got no reply. A familiar voice may reach them where a message did
    not."
  - "They declined 2 recent suggestions. Ask what would suit them better rather than offering the
    same thing again."
- **Avoid doubling up:** "A Care+ message is still waiting for their reply, so avoid asking
  about the same thing twice."
- **Give space:**
  - "Care+ has already contacted them twice this week. More contact risks becoming pressure."
  - "They are acting on a recent suggestion…"
- **Context:** rain, or a public holiday.
- **Review case:** its status, day of review, and whether it has come back to the queue.
- **Tracker:** "The tracker may not have synced on 2 days of the last 7. Missing readings say nothing
  about how they are."

## Privacy on a coordinator surface

- **No per-person figures.** No step count, percentage or score about a person, the same standing
  rule as the roster. Changes appear as bands with fixed thresholds.
- **Nothing the senior told Care+ appears.** That covers the content of a stated explanation,
  a disputed day, and even the fact that they said something. The row carries no policy gate name,
  because `stated_explanation` alone would disclose it.
- **Role-gated.** Coordinator only: a senior or demo operator gets 403.

## The decision this reverses

`CoordinatorPersonRow` recorded a standing decision: _"no priority score, no ordering that reads as
a ranking of people… a per-person risk score would turn a care queue into a leaderboard."_

The caregiver brief explicitly asked for a priority ranking, so the board now orders people.

**What was kept** from that decision:

- no score and no per-person figures;
- ordering from named facts only;
- the people who are fine stay on the list.

**What changed:**

- The "Your seniors" card on Care Team now renders the board's full ordered list instead of the
  unordered roster.
- `GET /v1/coordinator/people` is unchanged and still feeds the caseload counts.

## Where it lives

| Layer    | File                                                                                                                                                            |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rules    | `apps/api/src/silverloop/triage.py` (pure, no I/O)                                                                                                              |
| Contract | `models.py`: `FollowUpWindow`, `PriorityHold`, `CareNote`, `CareTeamGroup`, `CareTeamGroupReason`, `CarePriorityRow`, `CarePriorityBoard`, `ThresholdReference` |
| Data     | `sql_repository.py`: `care_priorities`, `_care_context`, `_with_recorded_decision`, `_runs_with_open_threshold_proposal` (one query)                            |
| API      | `GET /v1/coordinator/priorities?top_k=3` (1-10, default 3); see `docs/api.md`                                                                                   |
| Client   | `libs/api-client`: `coordinatorPriorities(topK)` (generated from `openapi/silverloop.json`)                                                                     |
| Web      | `apps/web/components/silverloop/care-priority-board.tsx` (`FollowUpFirstCard`, `CaseloadPriorityList`), wired in `care-team-view.tsx`                           |
| Labels   | `apps/web/lib/view-models.ts`: `carePriorityLabel`, `carePriorityTone`, `CARE_PRIORITY_GROUPS`                                                                  |

No schema change and no migration. The policy ladder itself (`policy.py`) was untouched by this
feature, so no YAML scenario changed. (It has since gained a per-senior review setting, ADR 0008; the
board reads it through the recorded decision and needed no change.)

## Verification

- **`apps/api/tests/test_triage.py`: 26 tests (38 with parametrisation).**
  - The ceiling checked against the real `policy.decide` across more than 1,000 input combinations.
  - Every gate short of outreach, and every holding gate with an open case.
  - Consent overriding an open case.
  - The recorded decision each day of a decline.
  - A decision downgraded by the person's mutes.
  - A same-day acceptance.
  - No figures and no senior disclosures in the output.
  - Read-only.
  - Top-k bounds and the reading order.
- **`apps/api/tests/test_care_team_group.py`:** every group and reason, the due-back rule including
  a case with no recorded day, and group/window agreement across a grid of gates, case states, review
  days and open offers. It also walks a decline through the repository: waiting, judgement,
  monitoring after acknowledgement, then judgement again on the review day.
- **`apps/api/tests/test_auth_rbac.py`:** coordinator 200; senior and demo operator 403.
- **`apps/e2e/tests/product-loop.spec.ts`, "care team leads with who to follow up with first, within
  the policy":**
  - the boundary note;
  - the top-k list after a sustained decline;
  - the top-k control asking the API;
  - the link to the review case;
  - consent withdrawal removing the person from top-k.
- **Full gates at delivery:**
  - `uv run pytest`: 3731 passed, 11 skipped.
  - `pnpm test:e2e`: 29/29 on ports 3100/8100.
  - Ruff, ESLint, TypeScript, Prettier and `pnpm build` all clean.
- **Independent review:** two rounds, whose findings were fixed and re-verified (see
  `docs/WAYFINDER.md`, "Care priorities — delivered 2026-09-15").

## Demo walkthrough (about 60 seconds)

1. **Open Care Team.** Point at the boundary note first: _"Not an emergency or medical service."_
   With a fresh reset: "No one needs a follow-up from you right now".
2. **Run "A decline that persists"** (three `activity_declines`), then reopen Care Team. Mdm Lim is
   #1, **Reach out today**:
   - a suggested approach;
   - take-note pointers: 3 low days in a row, well below her usual, under 3,500 steps, a message
     that got no reply, a message still waiting.
3. **Click "Go to their review case",** choose what to do, add a note, and **Mark resolved**. She
   drops to **Keep an eye on**: the board does not ask again once a person has answered.
   Acknowledging instead ("keep monitoring") also moves her to **Keep an eye on**, grouped as
   Care+ handling, until the case's review day. On that day she is back at "Reach out today".
4. **Open "How this order is set"** to show the thresholds and their sources.
5. _Optional, for a fuller caseload:_ run `pnpm seed` for all five personas, then use the Decision
   Simulator's persona switch:
   - run `activity_declines` twice for **Mdm Siti**: the weekly contact cap holds her at **Keep an
     eye on**;
   - run `low_wear` for **Mdm Devi**: she is **Set aside** as "tracker reading unclear".

> "The board is sensitive enough to notice a 600-step dip, but it can never suggest contact the
> safety rules did not already allow. A person still decides."

## Likely questions

- **"Why not 'urgent' or 'within an hour'?"** The data is one set of numbers per day, and the
  product is not an emergency service. A one-hour promise on daily data would be a claim we cannot
  back up.
- **"Is this a risk score?"** No. There is no number about anyone. The order comes from named facts
  in a fixed sequence, each of which the notes state.
- **"Could the thresholds be lower?"** Below about a 600-step change, the literature treats the
  difference as noise, and a watch list full of noise gets ignored.
- **"What if the AI is wrong?"** No AI orders anyone or writes any sentence here. The rules are
  deterministic and tested against the actual policy.
