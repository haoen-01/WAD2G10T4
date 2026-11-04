# 0015. The family-facing agents are read-only, always have a fallback, and stay off until their data is approved

Status: Proposed (2026-11-04).

Care+ has three agents that families and seniors see directly, besides the outreach planner
(`agenticlayer.md`): the **catch-up** on family Home, **"Read my day"** on the senior's Today tab,
and the **appointment draft** ("Describe it" on the new-appointment form). Each could make a
model write words a person reads about someone they care for, so the limits are set here. What
each sends to a provider is listed in `docs/agentic-features.md`.

## Decisions

1. **Read-only, bounded loops.** All three run the one loop in `server/src/silverloop/agent/loop.py`.
   The route first assembles a context through the stores' own permission-checked reads (the
   feed, the calendar, the task list), so an agent can never see more than the caller already
   can. The model may only call read-only tools over that context, then one submit tool. A
   deterministic check (`validate_catch_up`, the "Read my day" check, the draft check) approves the
   submission or sends it back with reasons, for at most `LLM_MAX_ITERATIONS` turns. Nothing is
   written: no agent has a tool that changes anything, and the draft only fills in the form the
   member then checks and adds with `POST /appointments`.
2. **Always a deterministic fallback, and the response says which.** With `LLM_ENABLED=false` (the
   default), under the offline demo, on a provider error, past the per-person agent limit
   (`AGENT_RATE_PER_10_MIN`), past the run's deadline (no turn starts whose worst case would end
   after 55 s, inside the browser's 60 s wait), or when the check keeps rejecting, the same answer
   is assembled without a model. Every response carries `mode` (`agent` or a `fallback_*` reason),
   `source` (`live` or `recorded`, only when `mode` is `agent`) and `steps` (each tool call and the
   check's ruling), and the screens word it accordingly ("Put together by Care+" for a fallback).
3. **`LLM_PROVIDER` gains `openai`.** `agent/openai_client.py` puts OpenAI's Chat Completions behind
   the `messages.create` surface the loops already use, and reuses the assistant's `OPENAI_*`
   settings (`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`); `LLM_MODEL` may override the
   model. This amends ADR 0013 decision 1, which kept `LLM_*` for Claude only: OpenAI may now also
   serve the agents, though no provider is switched on for them yet (decision 4).
4. **No provider is switched on until the data is approved.** The agents' context includes family
   members' first names and display names, what they did in the family feed, appointment titles
   and days, and tasks. That is more than ADR 0013 approved for Kaki, and it is not covered by it.
   No provider is enabled for these agents until issue #10 approves the data listed in
   `docs/agentic-features.md`, per feature. Until then they run as fallbacks, and the tests drive
   the real loops, tools and checks with a synthetic scripted stand-in.
5. **The voice is local.** "Read my day" is spoken by Kokoro-82M on the API server's own CPU
   (`silverloop.tts`, the opt-in `tts` dependency group); no cloud service, no key. Without it, or
   when it is busy or fails, the speech route answers 503 and the browser reads with its own
   speech, using **only on-device voices** (`localService === true`). Online browser voices (Edge's
   "Online (Natural)", Chrome's "Google …") are never chosen or offered, because they would send
   the senior's day to Microsoft or Google. With no on-device voice, the card says it cannot read
   aloud on this device.

## Consequences

- Five routes and their models join the contract (`CatchUp`, `MyDay`, `AppointmentDraft`,
  `AgentStep`, `SpeechVoice`, `SpeechRequest`, …): `GET /v1/groups/{id}/catch-up`,
  `POST /v1/groups/{id}/appointments/draft`, `GET /v1/people/{id}/my-day`,
  `GET /v1/people/{id}/my-day/voice` and `POST /v1/people/{id}/my-day/speech` (`docs/api.md`).
- No schema change: the agents read through the existing stores, and nothing they produce is
  stored. The speech cache lives in memory only, keyed by a hash, never the words.
- Switching a provider on is a decision recorded against issue #10, not a config change alone.
- Readers on a device without on-device English voices (some Chrome installs on Linux or
  ChromeOS) cannot have their day read aloud unless the server has Kokoro.
