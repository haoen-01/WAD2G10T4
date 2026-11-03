# Agentic features and live LLM approval

Care+ has four agentic features. Each one runs a bounded tool loop: the model calls read-only
tools, then submits a result, and a deterministic check approves or rejects it with reasons. A
rejected result goes back to the model to fix. Each feature also has a fallback that works with
no model at all. The outreach planner is described in [`agenticlayer.md`](../agenticlayer.md).
The other three share `apps/api/src/silverloop/agent/loop.py`.

**Status: live LLM use is on hold** pending the team's data-sharing review (issue #10). Every
feature works today with `LLM_ENABLED=false` (the fallback), and the tests drive each agent's real
loop, tools and check with a synthetic stand-in model. No live provider has ever been called.

## The four features

| Feature                   | Where                                          | Route                                     | Agent module                 |
| ------------------------- | ---------------------------------------------- | ----------------------------------------- | ---------------------------- |
| 1. Outreach planner       | Senior's suggestion card (inside `advance`)    | `POST /v1/simulation/advance`             | `agent/planner.py`           |
| 2. Since you last visited | Family Home, above Recently                    | `GET /v1/groups/{id}/catch-up?since=`     | `agent/catchup.py`           |
| 3. Read my day            | Senior's Today tab (read aloud by the browser) | `GET /v1/people/{id}/my-day`              | `agent/my_day.py`            |
| 4. Typed appointment      | Calendar → New appointment → "Describe it"     | `POST /v1/groups/{id}/appointments/draft` | `agent/appointment_draft.py` |

What each check rules on:

- **Outreach planner:** the candidate must be on the policy's allow-list, the message must use
  everyday wording, with no clinical words, urgency or third-party contact (`guardrails.py`).
- **Catch-up:**
  - Length limits.
  - The shared wording rules, plus no claims about how the senior is ("she is fine").
  - Plain text, with no copied data markers.
  - Every highlight names a person, visit or task the tools returned.
- **Read my day:**
  - The same wording rules, and no list or heading markup.
  - Every clock time it says must be one the tools returned.
- **Typed appointment:**
  - Every field must be accepted by the real `AppointmentRequest`.
  - The date must come from the deterministic `resolve_date` tool in the same run.
  - Times and the place must appear in what was typed, and the title must use the typed words.
  - Blank fields must be listed as missing.
  - It never fills in notes, and it never saves: the person checks the form and presses Add.

## What the screens say about who wrote it

Each response carries `mode` and `source`. `mode` is `agent` only when a model wrote the result
and the check approved it. When `mode` is `agent`, `source` says `live` (a real provider) or
`recorded` (a replayed recording); otherwise it is null. The web app words this in
`apps/web/src/lib/agent.ts` and the card libs:

- `live` model: "Written by the Care+ assistant …"
- `recorded` replay: "… from a recorded assistant run (not a live model) …"
- Any fallback: "Put together by Care+ …" or "Filled in by Care+ …". It never mentions the
  assistant.

Each card also has a "How Care+ wrote this" section that lists the agent's steps.

## Exactly what would be sent to the provider

This is what goes to the provider once live mode is on. It is the system prompt, the tool
schemas, and the tool results below. Text written by people is wrapped in
`<<<untrusted_text … >>>`, so the model treats it as data rather than instructions.

| Feature           | Sent                                                                                                                                                                                                                                                                                         | Never sent                                                                    |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Outreach planner  | Senior's display name and preferred language; the fixture background note; the activity change from their baseline (percent, number of low days, confidence); rain or holiday; permitted options; programme names, venues, distances, session times, accessibility; recent outreach outcomes | Raw wearable metrics, heart rate or SpO2, other people's data, family notes   |
| Catch-up          | Senior's name; for each feed item since the last visit: the family member's display name, what they did, the visit title and its day; open visits (title, day, start time, kind); today's tasks (title, time, done)                                                                          | Free-text notes (check-in notes, appointment notes), places, the group's PINs |
| Read my day       | Senior's name; today's and tomorrow's appointments (title, kind, start and end times, the first names of who is going); today's reminders (title, time, done)                                                                                                                                | Appointment notes and places, task notes                                      |
| Typed appointment | The sentence the member typed (up to 300 characters); today's date; for the one slot it checks, the titles of clashing appointments                                                                                                                                                          | Names, notes, places, any other appointment                                   |

Two points for the review:

- **The typed text is free text.** A member could type anything, including health details. Today
  it is sent nowhere and is never stored or logged.
- **Data flow:** with OpenAI (`LLM_PROVIDER=openai`, the provider the team proposes), data goes to
  OpenAI's Chat Completions API at `OPENAI_BASE_URL`. With Anthropic it goes to Anthropic's API;
  with Bedrock, to the team's AWS account in the configured region.
- **Kaki is not precedent.** ADR 0013 covers what the Kaki assistant sends to OpenAI (the question,
  recent turns, the senior's name, recent steps, appointments). It does not cover the four agents'
  data above, which issue #10 puts on hold until reviewed.

## What approval is needed

1. **Live LLM integration and external data sharing.** The team decides whether to approve the
   data above going to a provider, per feature (issue #10). The decision covers which provider and
   region, and whether the typed-appointment text is acceptable.
2. **Contract review.** Three new routes and the `CatchUp`, `MyDay`, `AppointmentDraft` and
   `AgentStep` models change `openapi/silverloop.json`. CLAUDE.md asks for a reviewer.
3. **Planner guardrail change (safety policy, done, needs a reviewer).** `validate_proposal` now
   rejects a message that copies the `<<<untrusted_text` fence or its markers (rule
   `copied_data_marker`); before, such a message was approved. The newer checks already did.

Out of scope until approved separately: "Who can go?" (cut in issue #10) and nudges or reminders
(these depend on the unmerged step 3).

## Configuration once approved

Live mode needs the `shared` runtime profile, which uses PostgreSQL or Supabase. `offline`
deliberately accepts only `LLM_PROVIDER=recorded` with the flag on, and that guard should stay.
Put these in your local `.env`, which is never committed:

```bash
LLM_ENABLED=true
LLM_PROVIDER=openai           # or anthropic / bedrock
OPENAI_API_KEY=…              # the assistant's existing setting; never commit, never paste anywhere
OPENAI_MODEL=gpt-5-mini       # the agents use this unless LLM_MODEL overrides it
LLM_EFFORT=medium             # sent to OpenAI as reasoning_effort for gpt-5 / o-series models
LLM_MAX_ITERATIONS=4
LLM_TIMEOUT_SECONDS=20        # reasoning models may need 30-45
```

`agent/openai_client.py` puts OpenAI behind the same `messages.create` surface the loops already
use, so every tool, check and fallback is unchanged. It asks for a tool call on every turn
(`tool_choice: required`), never sends Anthropic-only options, and on an error status raises
`OpenAIRequestError` with the status only; the loop then falls back and records that class name.

## Verifying live reasoning once approved

```bash
cd apps/api
uv run python -m silverloop.agent.live_check --confirm-team-approval
```

This runs each of the four agents once against the configured provider. It uses **synthetic
contexts built into the command**: it opens no database and sends no real person's data. For
each agent it prints the model, the tools called in order, how many check rejections there were,
any fallback reason, and the output. It never prints a key. It refuses to run without the flag,
with `LLM_ENABLED=false`, or with the `recorded` replay. It exits 0 only when all four reached
`agent` mode.

After that, open the app on the `shared` profile:

- Each agent card should say "Written by the Care+ assistant …".
- "How Care+ wrote this" should list the steps.
- Use the flag `LLM_ENABLED=false` to switch everything back to the fallbacks.

## Offline demo of the agent loops (no network)

- `pnpm demo:agent` replays a recorded outreach-planner run. Day 1 is agent-written; day 2 falls
  back, because the history tool returns wall-clock timestamps.
- `cd apps/api && uv run python -m silverloop.agent.demo_recording replay` prints that run's
  steps.
- The test suites `tests/test_catchup_agent.py`, `test_my_day_agent.py`,
  `test_appointment_draft_agent.py` and `test_live_check.py` drive every loop with
  `ScriptedStandIn`. It is a deterministic synthetic model, labelled as one, not a live LLM.
- `tests/test_openai_provider.py` runs all four agents through the real OpenAI adapter and its
  HTTP layer against a fake OpenAI endpoint (`httpx.MockTransport`; no network). This proves the
  translation and the tool-calling round trip, not a live model's reasoning.
