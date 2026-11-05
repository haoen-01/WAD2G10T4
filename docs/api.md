# API contract

Pydantic response and request models are the cross-language source of truth. The committed OpenAPI
snapshot lives at `openapi/silverloop.json`, and the generated TypeScript SDK lives at
`client/src/api-client/generated`.

After changing a Pydantic contract, run `pnpm client:generate`. `pnpm client:check` regenerates both
artifacts and fails when either differs from the committed files. CI runs that check before linting,
type checking and tests. `client/src/api-client/index.ts` is only a small convenience facade around
the generated SDK; it contains no handwritten copies of API model types.

## What the web app uses

The web app calls only the routes in `client/src/services/careApi.ts`, plus `/v1/auth/me` at
sign-in: person state and metrics, interventions and their outcomes, every route under
[Accounts, family groups and the calendar](#accounts-family-groups-and-the-calendar) except
`POST /v1/groups/{group_id}/open`, and the assistant (`POST /v1/assistant/chat`).

Beyond those, the API serves `/health`, `/ready`, `POST /v1/demo/reset`,
`POST /v1/simulation/advance` and `POST /v1/people/{person_id}/consent`, which the e2e suite and
the demo tooling call. `POST /v1/groups/{group_id}/open` records the last-opened group but has no
caller in the web app yet. Routes for features with no screen no longer exist; see
[Routes that no longer exist](#routes-that-no-longer-exist).

## Auth, in brief

Every route below runs `AUTH_ENABLED=true` behind a Supabase-issued bearer JWT
(`Authorization: Bearer <token>`, verified in `auth.py`), except `/health` and `/ready`, which are
always public. The **Auth** column names the role a route requires:

- **any authenticated** -- a valid token of any role (`require_any_authenticated`).
- **reader** -- the senior themselves, or an active member of the senior's family group
  (`PersonReader` plus `check_reader`); anyone else gets 404.
- **senior** -- role `senior`. `person_id` in the token payload is resolved through
  `auth_user_person_links` (`lookup_person_for_sub`), never trusted from the request. A 403 with
  "No person mapped to this senior account" means the Supabase user exists but no link row does.
- **demo_operator** -- an exact role match; anything else is 403. The `coordinator` role still
  exists in `AuthRole`, but no route requires it.
- **own person only** -- for a `senior`, the `{person_id}` in the path must equal the identity's own
  linked person, or the route returns 404 (not 403) so that another person's record is
  indistinguishable from one that does not exist.

With `AUTH_ENABLED=false` (the offline profile, most tests) every request is handed a fixed
synthetic identity -- the senior identity is always pinned to `mdm-lim` (`DEMO_PERSON_ID`) -- and
person-scoping is not enforced at all, because there is no real identity to protect. Do not read
"own person only" or "reader" below as active in that mode.

## Person, outreach and demo routes

| Method | Route                            | Auth                     | Purpose                                                 |
| ------ | -------------------------------- | ------------------------ | ------------------------------------------------------- |
| GET    | `/health`                        | none                     | Runtime mode and LLM-disabled status                    |
| GET    | `/ready`                         | none                     | Database backend, connectivity, Alembic and RLS posture |
| GET    | `/v1/auth/me`                    | any authenticated        | Confirm the caller's own identity and role              |
| POST   | `/v1/demo/reset`                 | demo_operator (see note) | Restore the deterministic Mdm Lim fixture               |
| GET    | `/v1/people/{person_id}/state`   | reader                   | Personal baseline, signal, decision and reasons         |
| GET    | `/v1/people/{person_id}/metrics` | reader                   | Daily metric history, oldest to newest                  |
| POST   | `/v1/people/{person_id}/consent` | senior, own person only  | Append consent evidence and withdraw open actions       |
| POST   | `/v1/simulation/advance`         | demo_operator            | Apply one allowlisted synthetic event                   |
| GET    | `/v1/interventions`              | senior                   | Read proposed low-risk actions                          |
| POST   | `/v1/interventions/{id}/outcome` | senior                   | Append a permitted senior outcome and preference update |
| POST   | `/v1/assistant/chat`             | reader                   | One answer from Kaki, the read-only assistant           |

`POST /v1/demo/reset` returns 403 unconditionally when `APP_ENV=production`, regardless of role.
With `AUTH_ENABLED=true` outside production it additionally requires a `demo_operator` token
(checked directly against the `Authorization` header, since the route needs to run before FastAPI's
dependency-injected auth would); with `AUTH_ENABLED=false` it is open.

`GET /v1/people/{person_id}/metrics?days=` (default 14) is clamped to `[1, 90]` rather than
rejecting an out-of-range value with 422.

`POST /v1/assistant/chat` takes `{messages, person_id?, page?}`. A senior always asks about
themselves; a family member names the senior (`person_id`), checked like any reader route. The
reply's `source` is `safety` (a fixed answer to an emergency, medicine or symptom question, which
never reaches a model), `openai` (when `OPENAI_API_KEY` is set and the profile is not `offline`) or
`helper` (the built-in answers). Too many questions in a short time is 429. See
[the assistant](assistant.md).

Every `/v1/people/{person_id}/...` route above returns 404 ("Person not
found") for a `person_id` that does not exist in the database, distinct from the 409 returned when
a real person exists but has no active scenario run (has never been through `/v1/demo/reset` or
the equivalent seed step for this database) -- see
[Fallback error handling](#fallback-error-handling) for how both are produced. `POST
/v1/people/{person_id}/consent` additionally requires `reason` to be 2-240 characters.

### Simulation event vocabulary

`POST /v1/simulation/advance` accepts one `event` per call, from a fixed allowlist enforced in
`sql_repository.SqlAlchemyRepository.advance` (not the request schema, so the allowlist can change
without a contract-breaking model edit): `activity_declines`, `rain_explains_decline`,
`rain_clears_activity_low`, `recovery`, `low_wear`, `consent_revoked`, `public_holiday`,
`programme_becomes_full`, `weather_turns`. An event outside that set returns 422.
`programme_becomes_full` marks `full` the listing the person has **themselves planned** -- the
soonest entry of the active run from the next simulated day onwards, skipping any entry they have
already replaced. With nothing planned it changes no listing. `weather_turns` changes no listing at
all: it sets the rain context. Each produces a replan offer only when the person has a plan it
affects (see [architecture](architecture.md#the-activity-catalogue-and-replanning)). No route
writes a plan, so in the running app neither event produces an offer.

`public_holiday` is context only. It sets `ContextSignal.holiday = True` on the synthesised day,
but `policy.decide` never reads `context.holiday` -- only `context.rainy` -- so a public holiday
never excuses or explains a decline on its own; the fixture's own comment says as much ("the
policy does not treat a holiday as an automatic excuse for a decline"). `rain_clears_activity_low`
is the counterpart to `rain_explains_decline`: skies have cleared (`context.rainy = False`) but
activity has not recovered, which is the scenario that should make the rain-cover NO_ACTION gate
stop applying. When live external context is enabled (`EXTERNAL_CONTEXT_ENABLED=true`), a fetched
public holiday can also set `context.holiday` outside the simulator; it is subject to the same
limitation.

`AdvanceRequest.event_id` is an optional idempotency key, `4-96` characters. Browser calls include
one; reusing the same `event_id` in the active scenario run replays the persisted response without
adding a daily metric, decision, notification or audit record. Reusing an `event_id` for a
different `event` returns 422. Calls that omit it remain supported for scripts and tests; the API
creates one server-side. Two concurrent `advance` calls for the same person racing on the same
simulated day return 409, not 500 -- the unique constraint on `(run_id, day)` does its job, but the
losing request needs a status code that says "retry", not "something broke".

`AdvanceRequest.person_id` is optional; omitting it targets the demo person (`mdm-lim`).

`AdvanceResponse.loop_trace` is the ten-stage decision trace -- see
[architecture.md](architecture.md#the-decision-trace) for the full stage list and where it is
built and persisted. Outcome responses include their evidence ID and the candidate preference
before and after the update (`preference_before`/`preference_after` on `OutcomeResponse`, and
`candidate_preference_score` in decision evidence). The learner cannot modify the policy decision.
These numbers are a product of two Beta posteriors (attend x enjoy-given-attend,
[ADR 0005](adr/0005-engagement-and-experience-as-two-learned-signals.md)), so a candidate with no
history reads 0.25.

`/health` is process liveness and takes no auth. `/ready` reports `ready` only when the database
responds, its Alembic revision matches the repository head, and `tables_without_rls` is empty; it
returns backend/profile metadata but never a database URL or credential. `tables_without_rls`
names any public ORM table whose PostgreSQL row-level security is off — the posture the lifespan
re-establishes on every start (`migrations.apply_rls_posture`, see `docs/supabase.md`) — and is
always empty off PostgreSQL, where there is no such flag and no Data API to be exposed to.

## Accounts, family groups and the calendar

These are the routes the Home, Senior, Calendar and Family screens use. They are registered in
`family_routes.py`. **signed in** is any valid token; **senior** and **family** are the account kind
chosen at sign-up (`/v1/me/onboard`). **reader** means the senior themselves, or an active member of
the senior's care group. **member** means an active member of that group.

| Method | Route                                                        | Auth      | Purpose                                                        |
| ------ | ------------------------------------------------------------ | --------- | -------------------------------------------------------------- |
| GET    | `/v1/me`                                                     | signed in | Who is signed in, the seniors they care for, whether onboarded |
| POST   | `/v1/me/onboard`                                             | signed in | Choose `senior` or `family`, once                              |
| POST   | `/v1/me/link-pin`                                            | senior    | Show a single-use senior-link PIN (10 minutes)                 |
| POST   | `/v1/groups`                                                 | family    | Create a family group with `senior_name` or `senior_pin`       |
| POST   | `/v1/groups/join`                                            | family    | Ask to join with a join PIN; waits as `pending`                |
| GET    | `/v1/groups/{group_id}`                                      | member    | The group and its members, including pending ones              |
| POST   | `/v1/groups/{group_id}/open`                                 | member    | Make this your current group (204, anyone else 404)            |
| POST   | `/v1/groups/{group_id}/join-pin`                             | member    | A new 7-day join PIN, replacing the old one                    |
| POST   | `/v1/groups/{group_id}/members/{member_id}/approve`          | member    | Let a pending member in                                        |
| POST   | `/v1/groups/{group_id}/members/{member_id}/decline`          | member    | Turn a pending request down                                    |
| POST   | `/v1/groups/{group_id}/link-senior`                          | member    | Link the senior with their PIN (400/404/409/429)               |
| PUT    | `/v1/groups/{group_id}/senior-name`                          | member    | Fix the typed name while unlinked (409 once linked)            |
| GET    | `/v1/people/{person_id}/calendar`                            | reader    | Appointments, family availability and helpers for a date range |
| GET    | `/v1/groups/{group_id}/calendar`                             | member    | The same for the group, also before its senior is linked       |
| POST   | `/v1/groups/{group_id}/appointments`                         | member    | Add an appointment, once or repeating                          |
| PUT    | `/v1/groups/{group_id}/appointments/{appointment_id}`        | member    | Change an appointment (every day of it, if it repeats)         |
| POST   | `/v1/groups/{group_id}/appointments/{appointment_id}/delete` | member    | Remove an appointment with its answers and helpers             |
| POST   | `/v1/groups/{group_id}/availability`                         | member    | Share a time you are free or busy                              |
| POST   | `/v1/groups/{group_id}/availability/{entry_id}/delete`       | member    | Take back one of your own shared times                         |
| POST   | `/v1/groups/{group_id}/answers`                              | member    | Available or not for one day of an appointment                 |
| POST   | `/v1/groups/{group_id}/helpers`                              | member    | Help with one day of an appointment                            |
| POST   | `/v1/groups/{group_id}/helpers/step-back`                    | member    | Stop helping with one day; the availability answer is kept     |
| GET    | `/v1/groups/{group_id}/activity`                             | member    | The family feed, newest first (`limit`, `before` cursor)       |
| POST   | `/v1/groups/{group_id}/check-ins`                            | member    | Tell the group you called, visited or messaged the senior      |
| POST   | `/v1/groups/{group_id}/asks`                                 | member    | Ask a member to take one appointment day                       |
| GET    | `/v1/groups/{group_id}/asks`                                 | member    | The group's open asks (`state=open`)                           |
| POST   | `/v1/groups/{group_id}/asks/{ask_id}/accept`                 | member    | The asked member says yes and becomes the helper               |
| POST   | `/v1/groups/{group_id}/asks/{ask_id}/decline`                | member    | The asked member says no                                       |
| POST   | `/v1/groups/{group_id}/asks/{ask_id}/withdraw`               | member    | The asker takes the ask back                                   |
| GET    | `/v1/me/notifications`                                       | family    | Your notifications, newest first, with the unread count        |
| POST   | `/v1/me/notifications/read`                                  | family    | Mark your notifications read (`notification_ids` or `all`)     |
| GET    | `/v1/groups/{group_id}/appointments/{appointment_id}/notes`  | member    | The family's notes on one day of an appointment (`date`)       |
| POST   | `/v1/groups/{group_id}/appointments/{appointment_id}/notes`  | member    | Add a note to one day of an appointment                        |
| POST   | `/v1/groups/{group_id}/notes/{note_id}/delete`               | member    | Remove one of your own notes                                   |
| GET    | `/v1/groups/{group_id}/tasks`                                | member    | The group's tasks and days ticked off, also before linking     |
| GET    | `/v1/people/{person_id}/tasks`                               | reader    | The senior's tasks and days ticked off                         |
| POST   | `/v1/groups/{group_id}/tasks`                                | member    | Add a task (once, daily or weekly)                             |
| PUT    | `/v1/groups/{group_id}/tasks/{task_id}`                      | member    | Change a task (every day of it); ticks stay                    |
| POST   | `/v1/groups/{group_id}/tasks/{task_id}/delete`               | member    | Remove a task and its ticks                                    |
| PUT    | `/v1/groups/{group_id}/tasks/{task_id}/days/{day}`           | member    | Tick one day done or not (`{done}`): today or a past day       |
| PUT    | `/v1/people/{person_id}/tasks/{task_id}/days/{day}`          | reader    | The senior ticks one of today's tasks done or not (`{done}`)   |
| GET    | `/v1/people/{person_id}/wearable`                            | reader    | Simulated watch status: connected, last sync, battery          |
| GET    | `/v1/groups/{group_id}/catch-up`                             | member    | The catch-up card: what changed (`since`), who is needed       |
| POST   | `/v1/groups/{group_id}/appointments/draft`                   | member    | Fill in the appointment form from typed text; saves nothing    |
| GET    | `/v1/people/{person_id}/my-day`                              | reader    | "Read my day": today's script for reading aloud                |
| GET    | `/v1/people/{person_id}/my-day/voice`                        | reader    | Whether the Kokoro voice can speak here, and its voices        |
| POST   | `/v1/people/{person_id}/my-day/speech`                       | reader    | One sentence spoken by Kokoro, as `audio/wav`                  |

A family group can exist before its senior is linked (ADR 0010). `POST /v1/groups` takes
`{relationship, senior_name?, senior_pin?}`, at least one of the two (else 422): with only
`senior_name` the group has no senior; with `senior_pin` the senior is linked at once and their
own account name wins. Until linked, `person_id` is null on `MyGroup`, `CareGroup` and the group's
`FamilyCalendar`, and `senior_name` is the typed name; once linked it is the senior's account name.
`link-senior` (`{senior_pin}`) checks membership before the PIN (pending or non-member: 404), so it
cannot be used to try PINs; a wrong or expired PIN is 400 and counts toward the lockout (429). It is
409 when the group already has a senior or the senior already has a group (the other group is not
named); a refusal leaves the PIN usable. `senior-name` (`{senior_name}`, 1-80 characters) is 409
once linked. `GET /v1/groups/{group_id}/calendar` is for active members (a senior gets 403, anyone
else 404). Linking and renaming add `senior_linked` and `senior_renamed` feed entries.

Each `MyGroup` also carries `member_count` (active members only; pending ones do not count) and
`last_opened`, true on at most one group: the caller's active membership with the latest
`last_opened_at`. A pending group is never true, and none is true if no active group has been
opened; an exact tie goes to the greatest `group_id`. `POST /v1/groups/{group_id}/open` sets that
time for the caller and returns 204 with no body; a pending member, a non-member, a senior and an
unknown group all get 404, and it adds no feed entry. Creating a group (by name or by PIN) also makes
it current. Joining, being approved, linking a senior and renaming do not. With `AUTH_ENABLED=false`,
the demo reset clears it for the demo group's members.

Each `MyGroup` also carries `unread_count`: the caller's unread notifications in that group (the
bell's `unread_count` split by group), counted in one grouped query. It is 0 for a pending membership
and for a group with no unread notifications. The groups page shows it as a badge on each group card;
marking notifications read shows on the next `GET /v1/me`.

A wrong PIN counts against the account: 5 wrong PINs in 15 minutes locks PIN entry. PINs are stored
as SHA-256 hashes. With `AUTH_ENABLED=false`, `POST /v1/demo/reset` (for Mdm Lim) puts Mdm Lim's demo
family and schedule back to their starting state, relative to today, and API startup does the same
when the database is SQLite. With sign-in on, `pnpm demo:story` sets up the real logins instead (see
[Supabase](supabase.md)).

`GET /v1/people/{person_id}/wearable` is simulated (`source: synthetic`). `last_synced_at` is null
when the readings are synthetic or the latest reading is from an earlier day (stale), so a screen
never shows an invented sync time.

### Agents and the read-aloud voice

The catch-up, the appointment draft and "Read my day" are read-only agents (ADR 0015; data sent
once a provider is approved: [agentic features](agentic-features.md)). Each response says how it was written:
`mode` (`agent`, or `fallback_disabled` / `fallback_error` / `fallback_no_proposal`), `source`
(`live` or `recorded` when `mode` is `agent`, else null) and `steps` (the agent's tool calls). With
`LLM_ENABLED=false` (the default) the answer is assembled without a model.

- `GET /v1/groups/{group_id}/catch-up?since=` (ISO date-time, optional): for active members; a
  senior gets 403, anyone else (a pending member, an outsider, an unknown group) 404; a malformed
  `since` is 422. With no `since` (a first visit) it says where things stand; with one, what
  changed after it.
- `POST /v1/groups/{group_id}/appointments/draft` (`{text}`, up to 300 characters, else 422): the
  same callers (senior 403, anyone else 404). It returns a filled-in `AppointmentDraft` and
  **saves nothing**; the member adds it with `POST /appointments`.
- `GET /v1/people/{person_id}/my-day`: for the senior themselves and active members of their
  family group; anyone else (another senior, a pending member, an outsider) 404.
- `GET /v1/people/{person_id}/my-day/voice`: the same readers. `{available, voice, label,
voices}`; `available` is false when Kokoro or its model files are not installed. It never waits
  on a sentence being spoken.
- `POST /v1/people/{person_id}/my-day/speech` (`{text, voice?}`): the same readers. 200 with one
  WAV sentence (`Cache-Control: private`); 422 for an unknown `voice` or `text` over 500
  characters; 429 past `TTS_RATE_PER_10_MIN` (240) sentences per person in 10 minutes; 503 when
  Kokoro is not installed (the opt-in `tts` group), could not speak, or is busy with another
  sentence for longer than `TTS_BUSY_WAIT_SECONDS` (3 s). A busy 503 says so
  (`{"code": "speech_busy", "detail"}`, `Retry-After: 1`): the browser asks for that sentence
  again a couple of times and keeps the Kokoro voice. Any other 503 means it cannot speak, and the
  browser reads with its own on-device voice.

**Fair use for the agents.** With `LLM_ENABLED=true`, one person may send
`AGENT_RATE_PER_10_MIN` (30) agent requests to the provider in 10 minutes, across the three agent
routes. Past that the request is still answered (200), assembled without a model exactly as with
the agent off (`mode: fallback_disabled`), rather than refused: these cards always show an answer.
Each run also has a deadline: no model turn starts unless even its worst case (every attempt timing
out) ends within 55 s, inside the browser's 60 s wait; past it the answer falls back
(`fallback_error`).

### The family feed

`GET /v1/groups/{group_id}/activity` returns `{entries, next_before}`, newest first. `limit` is 1-50
(default 20, else 422). `before` is a cursor: pass the previous page's `next_before` (an
`activity_id`) to get the entries after it; `next_before` is null on the last page, and a cursor that
is not one of this group's entries is a 422. Only active members read it (anyone else, or an unknown
group, is 404); the senior never does.

Entries carry structured fields only, the browser writes the sentence: `kind` (`group_created`,
`member_approved`, `member_declined`, `appointment_added`, `appointment_changed`,
`appointment_removed`, `helper_joined`, `helper_stepped_back`, `availability_updated`, `check_in`,
`note_added`, `senior_linked`, `senior_renamed`, `helper_asked`, `helper_declined`),
`actor_name`, `is_me`, `subject_name` (`member_approved`: who was let in; `helper_asked`: who was
asked), the appointment's title and kind as
they were at the time, `on_date`, and `occurrence_id`. `occurrence_id` is worked out on read and is
null once the appointment is gone or no longer has that day. Appointment entries (added, changed,
removed) carry the appointment's `on_date` only for a one-off; for a repeating appointment the entry
is about the series, so `on_date` and `occurrence_id` are null. Saving an appointment without
changing anything records nothing. `origin` is `live`, or `demo_seed` for
the offline demo's sample entries.

Entries are written in the same transaction as the change they describe, so a refused request writes
none. Not recorded: a pending join request, a per-day availability answer (except an "unavailable"
answer that took the member off an appointment, which is `helper_stepped_back`), `volunteer` when
already helping and `step-back` when not helping. Repeated free-time edits by one member for the same
day within 15 minutes are one `availability_updated`. Rows are never edited or deleted (only the
demo reset clears them). A member who has an entry must never be hard-deleted (entries point at
members by foreign key): a future leave or remove feature has to change the member's status instead,
and needs a PostgreSQL test.

`POST /v1/groups/{group_id}/check-ins` takes `{kind: called|visited|messaged, note?}` (note: at most
200 characters, trimmed, blank is none) and returns the new entry with 201. The note is shown to the
group only: nothing is sent to the senior, and it is never logged, audited or given to the agent.

### Asks and notifications

An ask is one member asking another, by name, to take one day of an appointment that needs a helper
(`silverloop.family_asks`). "Needs a helper" means no active member is going; a day with
an open ask still needs one. A group has at most one open ask per appointment day.

| From | Event                                    | To          | Notified                          | Feed              |
| ---- | ---------------------------------------- | ----------- | --------------------------------- | ----------------- |
| —    | A member asks a named member             | `open`      | the asked member, `ask_received`  | `helper_asked`    |
| open | The asked member says yes (or "I'll go") | `accepted`  | the asker, `ask_accepted`         | `helper_joined`   |
| open | The asked member says no                 | `declined`  | the asker, `ask_declined`         | `helper_declined` |
| open | The asker withdraws                      | `withdrawn` | the asked member, `ask_withdrawn` | none              |
| open | The appointment day is removed           | `withdrawn` | the asked member, `ask_withdrawn` | none              |
| open | The appointment's start time passes      | `lapsed`    | the asker, `ask_lapsed`           | none              |
| open | Anyone else presses "I'll go"            | `closed`    | asker and asked, `ask_closed`     | `helper_joined`   |

Nobody is notified of their own action (the asker's own "I'll go" tells only the asked member), the
senior never is, and an ended ask never reopens. Nothing else moves an ask: answering
"unavailable", stepping back or changing an appointment's details or its time on the same day leave
it open. Deleting an appointment, or an edit that leaves it without the ask's day, withdraws it.
Asks lapse when read or written, not on a schedule (ADR 0014): every ask route, `POST .../helpers`,
editing or deleting an appointment and `GET /v1/me/notifications` first end open asks whose start
(Singapore time, from the appointment's current start time) has passed. So deleting an appointment
after its start, or an edit that removes a day that has started, lapses the ask (the asker is told)
rather than withdrawing it. Asking, accepting, declining, withdrawing, `POST .../helpers`, editing
and deleting lock the appointment row first (`SELECT ... FOR UPDATE` on PostgreSQL), so an ask cannot open on a day someone has just
taken or removed.

`POST /v1/groups/{group_id}/asks` takes `{occurrence_id, asked_member_id}` and returns the
`HelperAsk` with 201: `{ask_id, occurrence_id, appointment_id, on_date, asker_member_id,
asker_name, asked_member_id, asked_name, created_at, state, can_answer, can_withdraw}` (the last
two are for the caller: the asked member answers, the asker withdraws, while open). It is 422 for
yourself, someone who is not an active member of this group (the senior never is), someone already
going that day, a day that has started, or a day that no longer needs a helper; 409 "Someone has
already been asked for this day" while an ask is open (two racing requests also end in 409); 404 for
an occurrence the group's appointment does not have. `GET /v1/groups/{group_id}/asks?state=open`
returns `{asks}`, the group's open asks oldest first (`state` accepts only `open`). `accept`,
`decline` and `withdraw` return 204; the wrong member gets 403, an ask that has already ended 409
"This ask has already ended", an ask of another group 404. All ask routes are for active members
only (a senior gets 403, anyone else 404). Asks are not part of `FamilyCalendar`, which the senior
reads.

`GET /v1/me/notifications?limit&before` returns `{items, unread_count, next_before}` across the
caller's active memberships, newest first (keyset on `created_at`, `notification_id`). `limit` is
1-50 (default 20); a `before` that is not one of the caller's notifications is 422. `unread_count`
counts every unread notification, not just the page. Each item is `{notification_id, kind,
created_at, read, group_id, group_label (the senior's name), ask_id, ask_state (now), occurrence_id
(null once the appointment or day is gone), appointment_title (now, else as asked), on_date, start
(null once gone), asker_name, asked_name, ended_by_name (null while open and for a lapse),
is_open_for_me (the caller is the asked member and the ask is still open)}`. Someone in no group
gets an empty page. `POST /v1/me/notifications/read` takes `{notification_ids}` (at most 100) or
`{all: true}`, exactly one (else 422), and returns 204; ids that are not the caller's are ignored.
Both are for family accounts (a signed-in senior gets 403). With `AUTH_ENABLED=false` the demo
reset clears every ask and notification of the demo family.

### Appointment notes

A note belongs to one day of an appointment (a repeating appointment has a thread per day), like
helpers and answers. It is for the family group only: the senior never reads notes, and the calendar
response does not embed them. The appointment's own `notes` field stays what it was, its details and
what to bring.

`GET /v1/groups/{group_id}/appointments/{appointment_id}/notes?date=YYYY-MM-DD` returns the day's
notes as `AppointmentNote` (`note_id`, `appointment_id`, `occurrence_id`, `member_id`, `author_name`,
`is_mine`, `text`, `created_at`), oldest first, at most 100. `POST` on the same path takes
`{date, text}` (text trimmed, 1-500 characters, blank is 422) and returns the note with 201.
`POST /v1/groups/{group_id}/notes/{note_id}/delete` returns 204; only the author may remove a note
(another member's is 403 "You can only remove your own notes"; an unknown note, or one in another
group, is 404). A `date` that is not a day of the appointment, or an appointment not in the group,
is 404. A day holds at most 100 notes: adding the 101st is 409 "This day already has the most notes
it can hold" and records nothing. When an edit to the appointment (its date or repeat) leaves a day
that is no longer one of its days, the notes on that day are deleted in the same transaction, since
nobody could read or remove them any more; their `note_added` feed entries stay, as they hold no
text, and the notes do not come back if the day returns. Only active members
use notes (anyone else, a pending member or an unknown group is 404; a signed-in senior is 403).

Adding a note records a `note_added` feed entry in the same transaction, with the appointment's
title and kind and the note's day, and never the note's text. Deleting a note keeps that entry.
Deleting an appointment deletes its notes. The text goes to no log, audit event or the agent.

### Tasks

A task is a one-off, daily or weekly reminder for the senior, kept by the family group
(`silverloop.family_tasks`; behaviour in [tasks](tasks.md)). `TaskRequest` is `{title, kind:
task|medicine, start_date, time (HH:MM), repeat: none|daily|weekly, repeat_until?, notes?}`;
`repeat_until` before `start_date` is 422, and a one-off task's `repeat_until` is dropped. Weekly is
every seven days from `start_date`. The two reads return a `TaskList`: `{person_id, group_id,
from_date, to_date, tasks, ticks}`, where each `Task` adds `task_id`, `added_by_name`, `created_at`
and `updated_at`, and each `TaskTick` is `{task_id, day, done_by_name, done_at}` within the range
(default two months back and six ahead, at most 400 days). The client works out each day.

Adding, changing and deleting are for active members only: a signed-in senior gets 403, anyone
else (a pending member, an outsider, an unknown group) 404. The person routes use the same check as
the calendar: the senior reads their own, an active member the senior of their group, anyone else 404. Ticking is idempotent (204). A future day, or a day the task is not on, is 422; through
`/v1/people/...` only today can be ticked (422 otherwise). Editing keeps every tick; a tick that is
no longer one of the task's days is kept but not returned. Deleting removes the task and its ticks.
Tasks write nothing to the family activity feed, and nothing in `advance` reads them.

## Routes that no longer exist

The API has no routes for features without a screen: coordinator review (queue, cases, case
review), the review setting, the follow-through and enjoyment reports, activity search and the
activity catalogue, preferences, goals, week plans, replan notices and offers, proposed memories,
context answers, baseline confirmations, day disputes, the world model, the evaluator, and the
simulation history reads. The code `advance` still runs stays: the review setting still feeds
`policy.decide` and its daily checks still run, review cases are still opened and closed by the
system, replan offers are written for any plan on record, and stored goals, day disputes, context
answers, baseline confirmations, follow-through and enjoyment reports are still read. Nothing
writes those last tables, so in the running app they stay empty; no table was dropped.
`repository.metrics()` stays for `supabase_smoke.py`, and `list_candidate_preferences` for
`pnpm demo:story`.

## Fallback error handling

Beyond the per-route `try`/`except` blocks documented above, `main.py` registers app-level
exception handlers (`register_exception_handlers`) that catch whatever a route's own handling did
not, so a route that forgets to convert a repository error does not surface as a bare 500:

- **`KeyError` -> 404** ("Person not found"). In practice the only `KeyError` left uncaught by a
  more specific local handler is `_active_run`'s `KeyError(person_id)` for a `person_id` that does
  not exist in the database, so this is what an unknown person on any of the
  `/v1/people/{person_id}/...` routes returns, even on the ones without their own local
  `except KeyError`.
- **`RuntimeError` -> 409**, but only for the specific, narrowly matched "this person was never
  seeded" family: `_active_run` raising "No active scenario run" (a real person who has never been
  through `/v1/demo/reset` or the seed step for this database) or `_load_metrics` raising "Active
  scenario contains no wearable metrics". The response text tells the caller to reset or seed and
  retry. Any other `RuntimeError` is deliberately re-raised rather than mapped, and still becomes
  a plain 500 -- this handler exists to give one well-understood condition a meaningful status
  code, not to launder every internal error into "just retry".
- **`StaleRunConflict` -> 409**: a reset or another advance changed the run between the read and
  the run lock. Nothing was written; re-reading the person resolves it.
- **`IntegrityError` -> 409** ("That answer was already recorded."), only for a uniqueness
  violation (two taps racing to the same row). Any other integrity failure is a plain 500.
- **`ValueError` -> 422**, with `str(exc)` as the detail, for any route whose own body does not
  already catch `ValueError` locally.

A route's own local exception handling always takes precedence and produces its own, more specific
message (e.g. "Intervention not found" instead of the generic fallback), so read the per-route notes
above first; this section is the safety net underneath them, not a replacement for them.

### Classified server errors

`error_responses.register_server_error_handlers` handles server-side failures. Each returns a **500**
with a `ServerErrorBody` (`{"code", "message", "detail"}`), where `code` is the `ServerErrorCode` enum
and `detail` repeats `message` for clients that read `detail`. The body is declared as the 500
response of every route (app-level `responses` in `create_app`), so the code is in the generated
client (`ServerErrorCode`). The message is fixed plain language. No framework text or stored value
reaches the client; field paths go to the server log only.

- `code: "stored_state_incompatible"`: a stored simulation snapshot was written under an older contract
  (for example one missing `PersonState.decided_by_gate`) and cannot be returned whole. It is raised by
  the idempotent `event_id` replay of `POST /v1/simulation/advance`. Nothing is migrated or
  reset automatically; the recovery is `POST /v1/demo/reset?person_id=`, which the web offers as "Reset
  local synthetic demo". See `stored_state.py`.
- `code: "internal_error"`: a pydantic `ValidationError` raised while the server builds or re-reads a
  model, or a FastAPI `ResponseValidationError`. The first is a `ValueError` subclass, so it would
  otherwise reach the `ValueError -> 422` handler above with raw validation text. Routes with a local `except ValueError` re-raise `ValidationError` first. Request-body
  validation (`RequestValidationError`) is unchanged and still returns FastAPI's 422.

A 500 that none of these handlers classifies (an unexpected exception) is still Starlette's plain
`Internal Server Error` text, not a `ServerErrorBody`.

This is not a production authentication contract. Do not expose the demo API publicly without an
identity layer, durable audit storage, rate limiting and an approved retention policy.
