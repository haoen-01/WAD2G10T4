# 0007 — A senior's own explanation of a quiet day, and what it may change

**Status:** accepted, implemented 2026-09-14 on `feat/context-explanation`
**Supersedes:** nothing. **Related:** [0001](0001-consent-scope-model.md) (the one-lookup shape this
copies), `context_question.py`, `context_explanation.py`, `policy.py`.

## Context

`context_question.py` decides, with real restraint, whether to ask a person why a quiet day was
quiet. The answer was recorded and then went nowhere. `ContextQuestionAnswerRow` was read in exactly
two places: an existence check so the question is not asked twice (`asked_recently`), and the world
model for display. The **value** of the answer was never read by anything that decides.

So "I'm away" and "I don't feel like going out" were indistinguishable to `policy.decide`. The
question's own `asked_because` string told the person a nudge was permitted because there was "no
rain, prior note, or other explanation on record" — which stopped being true the moment they
answered, and nothing acted on it.

## Decision

An answer becomes evidence the ladder reads, bounded by a window in the person's simulated calendar,
subject to a hard ceiling on how far it can reach.

### 1. A stated explanation may defer outreach and may never defer a human

The gate is bounded by `sustained_low_days < EXPLANATION_MAX_SUSTAINED_DAYS` (3), which is disjoint
from the `COORDINATOR_REVIEW` rung's `>= 3` threshold. This mirrors how the rain gate's `< 2` bound
makes it structurally incapable of blocking escalation.

The person this product should worry about most is the one who answers "I'm resting" every day for a
week. A system that can be talked out of putting that in front of a human, by the person it is
worried about, has the one failure review cannot recover from. Deferring a nudge on someone's word is
support; declining to involve a human on their word is not.

**Rejected:** letting an explanation apply at any severity.

### 2. The gate returns `NO_ACTION`, not `SUPPRESS`

`SUPPRESS` means outreach is blocked — consent, or a fatigue guard. Someone explaining an ordinary
week means nothing is warranted, which is `NO_ACTION`, a first-class audited result. Priority 10,
matching the rain gate, so the two are comparable in the attention ordering.

### 3. The person's account is checked before the weather

Both gates return `NO_ACTION`, so the order changes only which explanation is recorded. When someone
has told us why their week was quiet, that is the honest thing to put in the audit and on the trace.

### 4. The window is counted in simulated days

`ContextQuestionAnswerRow.answered_on_day` was added for this. A window derived from `answered_at`
would reproduce the `_weekly_contact_count` bug exactly: a demo advancing ten simulated days in one
wall-clock minute would see every answer as given "today", so no explanation would ever expire. Same
split, same justification, as `BaselineConfirmationRow.decided_on_day`.

The column is nullable and **not backfilled**. An existing row's scenario day cannot be recovered
from its wall-clock timestamp, so any value written would be a fabricated fact in an evidence table.
`active_explanation` skips such a row, making a pre-existing answer behave exactly as before.

### 5. A decided day is never re-decided

The window is anchored at `answered_on_day` and evaluated against `current_day` at decision time. A
day whose `decision_evidence` row exists is left alone: that evidence is append-only, and a second
row for one day would break the one-decision-per-day assumption the trace, metrics and scenario
runner rely on. Answering does not undo today's nudge; it shapes tomorrow's — which is correct
anyway, because the message has already been sent.

### 6. Two of five answers explain nothing, and one more is evidential only

| Value               | Window | Effect                                                                                      |
| ------------------- | ------ | ------------------------------------------------------------------------------------------- |
| `away`              | 3 days | Defers outreach for its window                                                              |
| `resting`           | 2 days | Defers outreach for its window                                                              |
| `other_plans`       | 1 day  | **Evidential only** — see below                                                             |
| `not_feeling_it`    | —      | Nothing. May _be_ the signal, not an account of it; routes to a preference proposal instead |
| `prefer_not_to_say` | —      | Nothing, and visibly nothing                                                                |

An answer set where every option conveniently confirms nothing is wrong is not listening; it is
looking for permission to stop.

**`resting` is two days, not one, and the reason is not obvious.** The question is only ever raised
_by_ a decision, so an answer always arrives after the day it describes has been decided, and
decision 5 forbids re-deciding it. **A one-day window can therefore never change an outcome.** Two
days is also the least intrusive honest reading of "I'm resting today": someone resting today is
plausibly quieter tomorrow, and one extra day of patience before nudging is what that warrants.

`other_plans` stays at one day deliberately. It is past tense about a specific day and makes no claim
about tomorrow, so inflating it to two days to give it a decisional effect would be inventing a
statement the person did not make. It is recorded, shown in the world model, and counts for
`asked_recently` — evidential, not decisional, and that is the honest description.

## Consequences

- A quiet week the person has already explained stops generating outreach. Previously they were
  contacted anyway, having taken the trouble to explain.
- `PersonState.stated_explanation` is new in the contract. It exists because the web reconstructs
  which gate fired from `PersonState` alone and is forbidden from string-matching the rationale;
  without it the Decision Audit panel would show a ladder skipping the gate that decided the day.
- The world-model display path now reads `answered_on_day` from the row, replacing a join that
  scraped the day out of audit-event details. The scrape is kept as a fallback for pre-column rows
  and can be deleted once no database holds one.
- The evaluation harness is unaffected: `evaluation/ladder.py` reimplements the ladder for ablation
  and the harness records no context answers, so `evaluate:check` did not move and
  `test_full_ladder_is_identical_to_the_real_policy` still holds.

## Not done

- **No scenario YAML.** The runner maps a flat list of input events to `advance()` and has no step
  for "the senior answers a question". Adding one changes the simulation contract and needs its own
  review, so the end-to-end proof is `tests/test_context_explanation_api.py`.
- **Re-asking after a window expires.** "At most one answered question per run" is a documented
  decision with its own rationale; reversing it needs its own review.
- **The wider answer set** (`WITH_FAMILY`, `DEVICE_NOT_WORN`, `NO_PARTICULAR_REASON`) and asking how
  long someone is away.
- **Free-text comprehension.** `_ALONE_KEYWORDS` is still three English string literals; that is the
  next slice, and it is worth more now that an answer does something.
