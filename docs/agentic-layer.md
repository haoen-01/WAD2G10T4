# The agentic layer

This page describes the outreach planner in `server/src/silverloop/agent/`: what it is, where it
sits in the daily loop, and how it is bounded. The read-only family agents (catch-up, "Read my
day", the typed appointment draft) share the same discipline and are described in
[agentic features](agentic-features.md).

## 1. What it is

Care+'s core is a **deterministic policy**. Given a senior's activity signal, it decides whether
to reach out at all and which class of action is permitted: nothing, a gentle nudge, a community
programme suggestion, a review case for a person to look at, or suppression. That logic is a
readable ladder in [`policy.py`](../server/src/silverloop/policy.py), and it is not negotiable.

The planner is a **bounded LLM loop that sits above that policy and below the message that reaches
the senior**. It never decides _whether_ to contact someone. Within a permission the policy has
already granted, it decides **which of the permitted options to offer and how to word it for this
person**, and every proposal must clear a deterministic guardrail before it can become a message.

> **The agent proposes. The deterministic policy disposes.**

The model is untrusted by construction: it gets a narrow job, and its output is validated by code
before it has any effect.

### Why an agent at all

Without the planner, candidate selection is a sort: rank the permitted options by the
Beta-Bernoulli learner and take the top one. That is still the fallback, but it cannot weigh a
group activity against a solo one for someone who is socially motivated, avoid wording close to a
suggestion they declined two days ago, or match "step-free, 400 m away, starts at 9am" to someone
who travels short distances. Those are judgements over per-person context. The decision to
intervene is a safety decision and stays deterministic; how to reach one person is a judgement,
and that is the planner's only job.

## 2. Where it sits

```text
  observation → data-quality gate → personal baseline → DETERMINISTIC POLICY
                                                              │
                                    ┌─────────────────────────┴──────────────────────────┐
                                    │                                                    │
                          no_action / suppress /                          gentle_nudge /
                          coordinator_review                              programme_suggestion
                                    │                                                    │
                          (planner never runs)                        ┌─────────────────▼──────────────────┐
                                    │                                 │        AGENTIC LAYER               │
                                    │                                 │  plan → act → adapt (bounded)      │
                                    │                                 │                                    │
                                    │                                 │  proposal ─→ GUARDRAIL ─→ approved │
                                    │                                 │      ▲            │                │
                                    │                                 │      └── rejected ┘                │
                                    │                                 └─────────────────┬──────────────────┘
                                    │                                                    │
                                    └────────────────────┬───────────────────────────────┘
                                                         ▼
                                    append-only evidence → senior → outcome → preference learner
```

The planner runs from one place in `advance`: `_prepare_outreach_plan` in
[`sql_repository.py`](../server/src/silverloop/sql_repository.py) ranks the permitted candidates
and fixes the deterministic fallback, then `_plan_outreach_safely` calls `plan_outreach` with no
database session open. If the policy returned `no_action`, `suppress` or `coordinator_review`, no
client is constructed and no request is made; a test covers this, as it does the planner never
being consulted while consent is withdrawn.

## 3. Plan → act → adapt

### Plan

The model receives a stable system prompt plus a short per-person brief: display name, preferred
language, the background note, the permitted action class, how far activity has moved from
baseline, how many sustained low days, the confidence, and local conditions (rain, public
holiday). The brief states that these figures are context for its choice and **must never appear
in the message**. The background note is labelled to the model as what it is: a synthetic fixture
description, not the person's own words.

### Act

It calls read-only tools (`agent/tools.py`):

| Tool                     | What it returns                                                                   | Why it exists                                                    |
| ------------------------ | --------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `get_candidate_options`  | The permitted candidates with their acceptance scores and raw offer/accept counts | This _is_ the allow-list. Anything outside it is rejected.       |
| `list_programme_options` | Open programmes with venue, distance, next session, accessibility                 | Lets the model match a programme to mobility and travel distance |
| `get_outreach_history`   | The last five outreach messages and how the person responded                      | Avoids repeating a recently declined option                      |
| `propose_outreach`       | The guardrail's verdict: `APPROVED`, or `REJECTED` with every reason              | The terminal step, and the adapt signal                          |

Under the default `modern` request profile every tool is declared with `strict: true` and
`additionalProperties: false`, so arguments validate against the schema. Every payload is a small
typed summary.

### Adapt

`propose_outreach` sends nothing. It runs
[`guardrails.validate_proposal`](../server/src/silverloop/agent/guardrails.py) (plain Python, no
model call) and returns the verdict as the tool result. A rejection lists every violation, and the
model revises and resubmits. An example loop, with a cap of 4:

```text
it1  get_candidate_options    ok=True   Returned 2 permitted candidate(s).
it2  propose_outreach         ok=False  Guardrail rejected:
       1. The message uses clinical or emergency language ... symptom.
       2. The message applies pressure ... you must.
       3. The message quotes a raw number ...
       4. The message gives no visible way to decline ...
it3  propose_outreach         ok=True   Guardrail approved the proposal.

Final: "Would a gentle five-minute seated stretch feel manageable today? Completely optional."
```

A rejected message never reaches a person or the database as a message; it is kept in the audit
record so a reviewer can see what the gate caught.

## 4. The guardrail

The guardrail is the security boundary and encodes the product boundary in
[the principles](principles.md). Every rule is deterministic and pinned by a test. Rules match on
a folded form of the text, so invisible characters and look-alike letters from other scripts do
not slip a word past them.

| Rule                         | Rejects                                                                                                 |
| ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| Allow-list                   | Any `candidate_key` not in the permitted set (no invented action, escalation or stale programme)        |
| Length                       | Under 20 readable characters or over 320 characters                                                     |
| No clinical language         | Diagnosis, symptoms, medication, doctor, hospital, emergency, fall detection, heart rate, risk score, … |
| No pressure                  | `you must`, `urgent`, `immediately`, `right now`, `mandatory`, …                                        |
| No third-party contact       | Bringing in a daughter, son, carer, neighbour or emergency contact                                      |
| No asserted action           | Claims that someone was informed, will call or visit, or that something was booked                      |
| No raw numbers               | Any run of 3 or more digits                                                                             |
| Visible opt-out              | Messages that are neither a question nor carry an explicit optionality marker                           |
| No channel instructions      | Asking the senior to reply, text, call, email or WhatsApp                                               |
| Plain text                   | Emoji, and copied data markers (`<<<`, `>>>`, `untrusted_text`)                                         |
| No invented history          | A claimed past experience of an option the record does not show the person accepting                    |
| True of the chosen candidate | Implied company for a solo activity, or accessibility claims the candidate does not have                |

A rejection is the loop working. What matters is that **no path exists from a rejected proposal to
a sent message.**

## 5. Bounded by construction

The iteration cap is `PlannerState.max_iterations`:

- The counter lives in Python, is incremented by the loop, and is never shown to the model. A
  model that wants another turn still stops.
- `LLM_MAX_ITERATIONS` (default 4) is clamped to `ITERATION_HARD_CEILING` (8), and
  `python -m silverloop.runtime check` refuses to start if it is set above the ceiling.

### Every failure degrades, none of them breaks

The deterministic ranker's choice is computed **before** the planner runs, so a valid, safe
message is always in hand. Every path below returns it unless the guardrail approved a proposal:

| Mode                   | Trigger                                                                          |
| ---------------------- | -------------------------------------------------------------------------------- |
| `agent`                | Proposal approved by the guardrail                                               |
| `fallback_disabled`    | `LLM_ENABLED=false`, SDK missing, no API key, or no candidates to choose between |
| `fallback_error`       | Provider error, timeout, or a refusal                                            |
| `fallback_exhausted`   | Iteration cap reached with no approved proposal                                  |
| `fallback_no_proposal` | The model ended its turn without calling `propose_outreach`                      |

This keeps the invariant intact: **the complete demo runs with SQLite, fixture adapters and
`LLM_ENABLED=false`**, with no network and no key, and the evidence record says the ranker chose
rather than pretending an agent was involved.

## 6. What it changes

- **For the senior.** The message is chosen for them: not an option they have just declined, a
  programme that is actually step-free and close, in wording that fits how they responded before.
  The guardrail keeps the tone the product promises: no diagnosis, no urgency, no numbers, always
  a way to say no.
- **For human review.** Nothing changes. A review is still a deterministic policy outcome the
  planner can neither trigger nor avoid. What a reviewer gains is a record of why this wording:
  the planner's stated reasoning, the tools it consulted, and anything the gate caught.
- **For safety.** The deterministic core is the planner's guardrail: an allow-list as a security
  boundary, a validator the model cannot talk past, a hard loop cap, and a clean fallback.

## 7. Evidence and metrics

Every planning run writes an append-only record into the intervention's evidence under `agent`:

| Field                                                                          | Measures                                                      |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| `mode`, `fallback_reason`                                                      | Whether the agent ran, and if not, why                        |
| `iterations` / `max_iterations`                                                | Loop discipline: is it converging or circling?                |
| `tool_calls`, `tool_call_success_rate`                                         | Whether it reaches for the right tools                        |
| `rejected_proposal_count`, `guardrail_violation_count`, `guardrail_rejections` | How often the guardrail intervenes, and which rules bind      |
| `usage`, `total_tokens`                                                        | Token cost per run: input, output, cache read, cache creation |
| `latency_ms`                                                                   | Time per run                                                  |
| `agent_reasoning`                                                              | The planner's own justification, for human review             |
| `boundary`                                                                     | A plain-language statement of what the planner could not do   |

`fallback_reason` names a provider exception's **class**, never its text: a provider message can
carry request ids, account ids or part of a credential, and this record is append-only. The full
text goes at WARNING to the `silverloop.agent` log with the request id
(`planner.log_provider_failure`), so an operator can still debug the failure.

The system prompt and tool list form a stable, byte-identical prefix across iterations, so a
revision after a rejection reads the prompt from cache; a test asserts the request stays
cacheable and bounded.

## 8. Configuration

Off by default. Nothing changes until it is switched on.

```bash
LLM_ENABLED=false          # default; the deterministic ranker selects every candidate
LLM_PROVIDER=anthropic     # anthropic | bedrock | openai | recorded
LLM_API_KEY=               # anthropic only; or ANTHROPIC_API_KEY
LLM_AWS_REGION=            # bedrock only; or AWS_REGION
LLM_MODEL=                 # blank → the pinned id for the provider (OPENAI_MODEL for openai)
LLM_MAX_ITERATIONS=4       # clamped to ITERATION_HARD_CEILING (8)
LLM_EFFORT=medium          # low | medium | high | xhigh | max
LLM_TIMEOUT_SECONDS=20
```

**Providers.** `anthropic` is the first-party API, authenticated by `LLM_API_KEY`. `bedrock` is
Amazon Bedrock (the Messages-API endpoint by default, or `LLM_BEDROCK_ENDPOINT=invoke`),
authenticated by the AWS credential chain, so no Anthropic key is involved. `openai` puts OpenAI's
Chat Completions behind the same surface (`agent/openai_client.py`) using `OPENAI_API_KEY` and
`OPENAI_MODEL`. `recorded` replays a committed recording (`LLM_RECORDING_PATH`) and makes no
network call; it is the one way to run the planner under the `offline` profile. `_build_client`
in `planner.py` is the only place that knows which provider is in play; the loop, the guardrail
and every fallback are provider-agnostic. `LLM_REQUEST_PROFILE=legacy` and `LLM_THINKING=off`
drop request features older models reject; neither touches the guardrail.

`runtime.validate_runtime` enforces the right credential per provider (a key for `anthropic` and
`openai`, a region for `bedrock`, a recording path for `recorded`), so a misconfiguration fails at
startup rather than falling back silently. `pnpm runtime:check` states which selector will run:

```text
Outreach planner: disabled; the deterministic ranker selects every candidate.
```

**Model choice.** `claude-opus-5` on the first-party API and `anthropic.claude-opus-5` on Bedrock,
both written out in full in [`constants.py`](../server/src/silverloop/agent/constants.py) and
selected by `default_model_id(provider)`, never assembled from fragments. Adaptive thinking is on
by default; effort defaults to `medium`.

## 9. Files

| File                       | Purpose                                                                                                                     |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `agent/constants.py`       | Model ids, version stamp, iteration ceiling, message and payload limits                                                     |
| `agent/models.py`          | `AgentRun`, `AgentProposal`, `AgentToolCall`, `GuardrailVerdict`, usage: the audit shapes                                   |
| `agent/guardrails.py`      | The deterministic security boundary. No model call anywhere in it                                                           |
| `agent/guardrail_rules.py` | Classifies violations by rule for the counters                                                                              |
| `agent/tools.py`           | Tool schemas and the read-only executor. No SQLAlchemy: the repository passes in a `ToolContext`                            |
| `agent/planner.py`         | `plan_outreach`, its fallbacks and the provider clients                                                                     |
| `agent/openai_client.py`   | OpenAI behind the same `messages.create` surface                                                                            |
| `agent/recorded_client.py` | Replays a committed recording; no network                                                                                   |
| `agent/prompt_safety.py`   | Fencing for untrusted text reaching a prompt (see §11)                                                                      |
| `sql_repository.py`        | `_tool_context` assembles what the planner may see; `_prepare_outreach_plan` and `_plan_outreach_safely` are the call sites |
| `runtime.py`               | Fail-fast configuration checks and the planner status line                                                                  |

**Why a manual loop rather than an SDK tool runner.** Here the loop _is_ the safety story: it must
carry a hard cap this code enforces, capture a complete audit trace of every call and verdict, and
fall back to the deterministic ranker on any failure. Owning the loop keeps all three explicit.

## 10. Testing, and what is not measured

`server/tests/test_agent_planner.py` and `test_agent_integration.py` run against a **fake
transport**, deterministically and offline, with no API key. They cover every guardrail rule; the
allow-list refusing an escalation; a rejected message never surviving into the result; revising
after a rejection; the iteration cap being enforced against a model that never stops; the cap
being clamped to the ceiling; every fallback mode; the cached prefix staying identical between
turns; the completeness of the audit record; and, through the real `advance()` path, that the
planner is never consulted when consent is withdrawn. `test_prompt_injection.py` probes the
fencing and the guardrail together.

**Not measured, and not to be claimed:**

- **Proposal quality.** There is no ground-truth set scoring whether the planner's choice beats
  the ranker's, and no figures for guardrail interception rate, tokens per run or latency with a
  live key. The instrumentation is in place; the measurement is not done.
- **Live provider behaviour.** The tests use fake transports and recordings; they prove the loop's
  discipline, not a live model's reasoning.
- **Untrusted input at scale.** Today's inputs are synthetic fixtures. A real wearable or
  programme feed would bring untrusted text into the prompt; the guardrail validates the _output_
  regardless, and the fencing below labels the input.

## 11. The other loops in `agent/`

- **Activity ranking** (`plan_activity_ranking` in `planner.py`, with
  `guardrails.validate_activity_order`) may reorder and narrow an already-filtered list of
  activities. Its guardrail rejects a key the tool never returned, a duplicate, an empty proposal
  when options exist, an option moved more than `MAX_PROMOTION` (3) places above its
  deterministic rank, and narrowing below `MIN_SHOWN_AFTER_NARROWING` (3) options. No route calls
  it, because the activity search it served no longer exists.
- **Review-setting calibration** (`threshold_planner.py`, `threshold_tools.py`,
  `threshold_guardrails.py`) proposes at most one step of change to a person's review setting
  after a reviewer's false-alarm judgement, and writes up a revert; nothing applies until a
  reviewer approves it ([ADR 0008](adr/0008-coordinator-calibrated-review-threshold.md),
  [calibration and trust](calibration-trust-spec.md)). The routes that record a review or an
  approval no longer exist, so in the running app it is not reached.
- **The family agents** (`loop.py`, `catchup.py`, `my_day.py`, `appointment_draft.py`) are
  read-only and described in [agentic features](agentic-features.md).

### Fencing untrusted text (`agent/prompt_safety.py`)

`fence_untrusted` wraps any string nobody on the Care+ team wrote (the profile note, every
free-text field of a tool payload such as a programme's name and venue, and in the family agents
names, titles and text people wrote) in `<<<untrusted_text ... >>>` delimiters, and neutralises a literal `>>>`
inside it so the text cannot forge its own closing marker. Identifiers such as a `candidate_key`
are left bare: they are allow-list tokens Care+ mints. The explanation of the markers lives once in
each system prompt, so the cached prefix stays identical.

Fencing is defence in depth on the input side, not the boundary. A context note engineered to make
the model write "your daughter has been informed" is still caught by `validate_proposal`'s
third-party and asserted-action rules, and a message that copies the markers is rejected outright.
