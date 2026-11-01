# API contract

Pydantic response and request models are the cross-language source of truth. The committed OpenAPI
snapshot lives at `openapi/silverloop.json`, and the generated TypeScript SDK lives at
`libs/api-client/src/generated`.

After changing a Pydantic contract, run `pnpm client:generate`. `pnpm client:check` regenerates both
artifacts and fails when either differs from the committed files. CI runs that check before linting,
type checking and tests. `libs/api-client/src/index.ts` is only a small convenience facade around
the generated SDK; it contains no handwritten copies of API model types.

## What the web app uses

The web app calls only the routes in `apps/web/src/services/careApi.ts`, plus `/v1/auth/me` at
sign-in: person state and metrics, interventions and their outcomes, and every route under
[Accounts, family groups and the calendar](#accounts-family-groups-and-the-calendar). The e2e suite
also calls `POST /v1/demo/reset` and `POST /v1/simulation/advance`.

Everything else below serves features with no current screen: coordinator review, the evaluator
ranker inspector, the follow-through loop, the user-initiated activity loop and the review setting.
Those sections say so in their headings. They stay documented because the routes still exist, and
several still run inside every simulated day.

## Auth, in brief

Every route below runs `AUTH_ENABLED=true` behind a Supabase-issued bearer JWT
(`Authorization: Bearer <token>`, verified in `auth.py`), except `/health` and `/ready`, which are
always public. The **Auth** column names the role a route requires:

- **any authenticated** -- a valid token of any role (`require_any_authenticated`).
- **senior** -- role `senior`. `person_id` in the token payload is resolved through
  `auth_user_person_links` (`lookup_person_for_sub`), never trusted from the request. A 403 with
  "No person mapped to this senior account" means the Supabase user exists but no link row does.
- **coordinator** / **demo_operator** -- an exact role match; anything else is 403.
- **own person only** -- for a `senior`, the `{person_id}` in the path must equal the identity's own
  linked person, or the route returns 404 (not 403) so that another person's record is
  indistinguishable from one that does not exist. This check applies only to the `senior` role: a
  coordinator or demo operator reading another person's data is doing their job, not crossing a
  boundary, so it is never scoped for them.

With `AUTH_ENABLED=false` (the offline profile, most tests) every request is handed a fixed
synthetic identity per role -- the senior identity is always pinned to `mdm-lim`
(`DEMO_PERSON_ID`) -- and person-scoping is not enforced at all, because there is no real identity
to protect. Do not read "own person only" below as active in that mode.

## Demo routes

| Method | Route                                                  | Auth                         | Purpose                                                   |
| ------ | ------------------------------------------------------ | ---------------------------- | --------------------------------------------------------- |
| GET    | `/health`                                              | none                         | Runtime mode and LLM-disabled status                      |
| GET    | `/ready`                                               | none                         | Database backend, connectivity, Alembic and RLS posture   |
| GET    | `/v1/auth/me`                                          | any authenticated            | Confirm the caller's own identity and role                |
| GET    | `/v1/metrics`                                          | coordinator or demo_operator | Operational evidence and bounded-learning counters        |
| POST   | `/v1/demo/reset`                                       | demo_operator (see note)     | Restore the deterministic Mdm Lim fixture                 |
| GET    | `/v1/people/{person_id}/state`                         | senior, own person only      | Personal baseline, signal, decision and reasons           |
| GET    | `/v1/people/{person_id}/metrics`                       | senior, own person only      | Daily metric history, oldest to newest                    |
| POST   | `/v1/people/{person_id}/consent`                       | senior, own person only      | Append consent evidence and withdraw open actions         |
| POST   | `/v1/simulation/advance`                               | demo_operator                | Apply one allowlisted synthetic event                     |
| GET    | `/v1/simulation/latest`                                | demo_operator                | Recover the latest persisted loop trace after a restart   |
| GET    | `/v1/simulation/history`                               | demo_operator                | Recent `advance()` results, oldest to newest              |
| GET    | `/v1/simulation/events`                                | demo_operator                | Read the decision evidence trail                          |
| POST   | `/v1/evaluator/ranker/inspect`                         | demo_operator                | Trace one activity ranking; preview variants, never saved |
| GET    | `/v1/evaluator/ranker/presets`                         | demo_operator                | Scripted history presets and preview controls             |
| GET    | `/v1/interventions`                                    | senior                       | Read proposed low-risk actions                            |
| POST   | `/v1/interventions/{id}/outcome`                       | senior                       | Append a permitted senior outcome and preference update   |
| GET    | `/v1/coordinator/people`                               | coordinator                  | Read the care-team roster (bands and standings only)      |
| GET    | `/v1/coordinator/priorities`                           | coordinator                  | Who to follow up with first (read-only, policy-capped)    |
| GET    | `/v1/coordinator/metrics`                              | coordinator                  | Caseload totals: `/v1/metrics` summed over the roster     |
| GET    | `/v1/coordinator/people/{person_id}/activity-relative` | coordinator                  | Recent days as lower than usual or not (no step counts)   |
| GET    | `/v1/coordinator/queue`                                | coordinator                  | Read human-review cases                                   |
| GET    | `/v1/cases/{id}`                                       | coordinator                  | Read one review case                                      |
| POST   | `/v1/cases/{id}/review`                                | coordinator                  | Record a coordinator review outcome                       |
| GET    | `/v1/programmes`                                       | any authenticated            | Read clearly labelled synthetic AAC fixtures              |

`POST /v1/demo/reset` returns 403 unconditionally when `APP_ENV=production`, regardless of role.
With `AUTH_ENABLED=true` outside production it additionally requires a `demo_operator` token
(checked directly against the `Authorization` header, since the route needs to run before FastAPI's
dependency-injected auth would); with `AUTH_ENABLED=false` it is open.

Two path parameters carry a real clamp rather than an unbounded read: `GET
/v1/people/{person_id}/metrics?days=` is clamped to `[1, 90]` regardless of what is requested, and
`GET /v1/simulation/history?limit=` is clamped to `[1, 30]`. Both silently clamp rather than
rejecting an out-of-range value with 422.

`GET /v1/metrics` and every `/v1/people/{person_id}/...` route above returns 404 ("Person not
found") for a `person_id` that does not exist in the database, distinct from the 409 returned when
a real person exists but has no active scenario run (has never been through `/v1/demo/reset` or
the equivalent seed step for this database) -- see
[Fallback error handling](#fallback-error-handling) for how both are produced. `POST
/v1/people/{person_id}/consent` additionally requires `reason` to be 2-240 characters. `POST
/v1/cases/{id}/review` requires `reviewer_note` to be 2-500 characters and `status` to be one of
`open`, `acknowledged`, `resolved`. It also accepts the override-memory pair `human_action`
(`agree` / `hold` / `override`) and `override_reason` (`known_context` / `data_doubt` /
`recent_contact` / `other`); both are optional, `human_action` is never defaulted to `agree`
(silence is recorded as silence), and `human_action=override` without an `override_reason` is a 422. `reviewer_note` is stored on the case and returned in `ReviewCase.action_history`, but the
`case_reviewed` audit event records only `note_present` -- the same redaction rule every free-text
field a senior can write already follows. Override memory is audit and evaluation only: nothing on
the learning or ranking path reads the review table.

`GET /v1/coordinator/people` returns one `CoordinatorPersonRow` per person with an active scenario
run, ordered most-attention-first and then by name. It carries an `attention_band` word, a consent
standing, a count of days in the last week whose tracker reading was too sparse to interpret, the
id of the person's unresolved case if they have one, and the class of their last decision -- and
deliberately no step count, percentage or score. Ordering is a reading order, not a ranking: the
band is the only thing that moves a row. A run with no readings yet is omitted rather than
reported as `stable`, because a person the system has never seen is not a person it has seen and
found nothing wrong with.

`GET /v1/coordinator/priorities?top_k=3` returns a `CarePriorityBoard`: every person with an active
run in follow-up order, and up to `top_k` (1-10, default 3; out of range is a 422) of them as
`follow_up_first`. It is read-only and deterministic (`triage.py`), it never outranks the policy
ladder, and it reads the decision _recorded_ for the person's current day rather than re-running
the ladder. The full design, thresholds and sources are in
[`docs/care-priorities.md`](care-priorities.md).

`GET /v1/coordinator/priorities?person_id=mdm-lim` is the same board narrowed to one person. The
board is still built across the whole caseload, so the row is byte-for-byte the row the full board
holds: `position` is the person's place in the whole reading order, and `follow_up_first` holds the
row only if the full board's `top_k` includes it. `people` is empty for a person with no readings
yet, and an unknown `person_id` is a 404.

`GET /v1/coordinator/metrics` returns a `CoordinatorFleetMetrics`: `no_action_decisions`,
`interventions`, `awaiting_reply`, `no_reply_recorded`, `coordinator_reviews`,
`coordinator_overrides`, `device_suspected_days` and `world_model_quality`, each exactly the sum of
that field of `GET /v1/metrics?person_id=...` over the people `GET /v1/coordinator/people` lists
(`people_included` says how many). `people` is the stored people count `/v1/metrics` reports. It
replaces one `/v1/metrics` request per person with one grouped read.

`GET /v1/coordinator/people/{person_id}/activity-relative?days=7` returns an
`ActivityRelativeToUsual` for a coordinator's case view: the person's most recent stored days
(`days` is 1-14, default 7; out of range is a 422), oldest first, each with `reading_usable` and a
`position` of `lower` or `usual_or_higher`, plus `lower_days`, `usable_days`, `as_of_day` (the
latest stored day), `consent_active` and `usual_available`. Everything is derived on read with the
ladder's own rules (`analytics.activity_relative_to_usual`). A reading is usable when
`quality.assess_data_quality` says so, which is the wear-time gate. A usable day is `lower` when its
steps fall below `analytics.low_day_threshold`, which is `LOW_DAY_FRACTION` of the effective
baseline as of today (the same line and baseline the persistence count uses, including a confirmed
reference). Unusable days, and every day when there is no usual level yet (`usual_available=false`),
carry `position: null`. There is deliberately no `higher` position: the policy draws no high line,
so the API does not invent one. When the run's latest consent is withdrawn, `consent_active` is
`false` and nothing about the person's days is read back: `days` is empty, `usual_available` is
`false` and `lower_days`/`usable_days` are 0 (`as_of_day` is still reported). The response carries
no step count, percentage, baseline or score. It is coordinator-only (senior and demo operator get
403); the senior's own `/state` and `/metrics` routes stay senior-only. An unknown person is a 404
and an unseeded one a 409. It costs at most four queries whatever the history length
(`tests/test_query_counts.py`).

- `reach_out_today` applies only while a review case the ladder opened is still unresolved, and
  not on a day when rain, the person's own explanation, a baseline too small to read, the weekly
  contact cap or the accepted-outreach cooldown holds contact back (the case then shows as
  `keep_an_eye_on`). An open case does stay at `reach_out_today` on a day whose tracker reading
  cannot be interpreted, because it rests on earlier readable days.
- `check_in_within_48h` applies only where the ladder already permitted outreach
  (`programme_suggestion`, or `gentle_nudge` whose recent messages got no reply or were declined).
- A hold that arises after the day's decision was recorded (the person accepts the suggestion,
  explains their week, or withdraws consent) wins over that decision.
- Withdrawn consent and an unreadable reading are reported as a `hold`, never as a window.
- More sensitive thresholds only place someone on `keep_an_eye_on` and break ties inside a window:
  at least 10% and at least 600 steps a day below their usual, or 20% below their anchored
  reference.

Like the roster, the board carries no step count, percentage or score about a person. Every row's
`take_note` sentences come from fixed templates, never from a model. None of them repeats anything
the senior told Care+, and rows carry no policy gate name, because `stated_explanation` alone
would disclose that the senior explained their week. Every board carries a boundary note saying it
is not an emergency or medical service.

### Simulation event vocabulary

`POST /v1/simulation/advance` accepts one `event` per call, from a fixed allowlist enforced in
`sql_repository.SqlAlchemyRepository.advance` (not the request schema, so the allowlist can change
without a contract-breaking model edit): `activity_declines`, `rain_explains_decline`,
`rain_clears_activity_low`, `recovery`, `low_wear`, `consent_revoked`, `public_holiday`,
`programme_becomes_full`, `weather_turns`. An event outside that set returns 422.
`programme_becomes_full` marks `full` the listing the person has **themselves planned** -- the
soonest entry of the active run from the next simulated day onwards, skipping any entry they have
already replaced -- which is a catalogue fact genuinely changing. It never picks a listing of its
own: with nothing planned it changes no listing and says nothing. `weather_turns` changes no
listing at all: it sets the rain context, and the person is told the forecast turned. Each
produces a replan offer when the person actually has a plan it affects, and nothing at all when
they do not (see `docs/architecture.md`, "Replanning"). The offer carries an alternative only when
the plan's own day and time of day genuinely have one; "I could not find anything similar for that
day" is a complete answer, not a failure -- an evening plan on a day whose catalogue holds no
second evening session gets exactly that.

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
built and persisted. Outcome and follow-through responses include their evidence ID and the
candidate preference before and after the update (`preference_before`/`preference_after` on
`OutcomeResponse`/`FollowThroughResponse`, and `candidate_preference_score` in decision evidence).
The learner cannot modify the policy decision. Since ADR
[0005](adr/0005-engagement-and-experience-as-two-learned-signals.md), these numbers are a product
of two Beta posteriors (attend x enjoy-given-attend), not one: a candidate with no history reads
0.25, not 0.5, and every other value moved on the same scale -- see the ADR before comparing a
value recorded before that change against one recorded after it.

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
| GET    | `/v1/groups/{group_id}/appointments/{appointment_id}/notes`  | member    | The family's notes on one day of an appointment (`date`)       |
| POST   | `/v1/groups/{group_id}/appointments/{appointment_id}/notes`  | member    | Add a note to one day of an appointment                        |
| POST   | `/v1/groups/{group_id}/notes/{note_id}/delete`               | member    | Remove one of your own notes                                   |
| GET    | `/v1/people/{person_id}/wearable`                            | reader    | Simulated watch status: connected, last sync, battery          |

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

A wrong PIN counts against the account: 5 wrong PINs in 15 minutes locks PIN entry. PINs are stored
as SHA-256 hashes. With `AUTH_ENABLED=false`, `POST /v1/demo/reset` (for Mdm Lim) puts Mdm Lim's demo
family and schedule back to their starting state, relative to today, and API startup does the same
when the database is SQLite. With sign-in on, `pnpm demo:story` sets up the real logins instead (see
`docs/supabase.md`).

### The family feed

`GET /v1/groups/{group_id}/activity` returns `{entries, next_before}`, newest first. `limit` is 1-50
(default 20, else 422). `before` is a cursor: pass the previous page's `next_before` (an
`activity_id`) to get the entries after it; `next_before` is null on the last page, and a cursor that
is not one of this group's entries is a 422. Only active members read it (anyone else, or an unknown
group, is 404); the senior never does.

Entries carry structured fields only, the browser writes the sentence: `kind` (`group_created`,
`member_approved`, `member_declined`, `appointment_added`, `appointment_changed`,
`appointment_removed`, `helper_joined`, `helper_stepped_back`, `availability_updated`, `check_in`,
`note_added`, `senior_linked`, `senior_renamed`),
`actor_name`, `is_me`, `subject_name` (`member_approved` only), the appointment's title and kind as
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

## The follow-through loop (no screen)

Outreach used to end at sending a sentence: a senior tapped "Yes, tell me more", was told nothing
more, and the tap was recorded as a success. These routes cover the three beats that were missing.

| Method | Route                                          | Auth                    | Purpose                                                     |
| ------ | ---------------------------------------------- | ----------------------- | ----------------------------------------------------------- |
| GET    | `/v1/interventions/{id}/detail`                | senior                  | The content behind "tell me more" -- fixed, never generated |
| POST   | `/v1/interventions/{id}/follow-through`        | senior                  | What the person actually did afterwards                     |
| GET    | `/v1/interventions/{id}/follow-up`             | senior                  | What their activity did in the days after                   |
| GET    | `/v1/interventions/history`                    | senior                  | The senior's own completed loops                            |
| GET    | `/v1/coordinator/people/{id}/outreach-history` | coordinator             | The same shape, for a coordinator                           |
| GET    | `/v1/people/{id}/preferences`                  | senior, own person only | Per-suggestion preferences the senior owns                  |
| POST   | `/v1/people/{id}/preferences/{candidate_key}`  | senior, own person only | Turn one kind of suggestion off or back on                  |
| POST   | `/v1/people/{id}/day-dispute`                  | senior, own person only | The person's own correction to a day we read as quiet       |

Three properties of this design are load-bearing.

**Acceptance is not success.** `OutcomeKind.ACCEPTED` means only that the person asked to see more.
What happened next is `FollowThrough`, recorded separately, and the preference learner weights it
far more heavily -- a bare acceptance contributes a quarter of a unit of evidence, a completed
follow-through a full one, and the follow-through supersedes the acceptance rather than stacking on
it. Ranking on taps alone would make this an engagement optimiser, which is the failure mode the
product exists to avoid.

**`/follow-up` always returns 200.** `available` reports whether there is anything to say yet, so
"too early" is a normal answer rather than an error, and every response -- including unavailable
ones -- carries the `caveat` stating that the observation describes what happened and not why. One
person over a few days cannot establish that a suggestion caused anything; that would need a
comparison across many people.

**The two history routes are deliberately separate.** The senior's is scoped by identity, the
coordinator's by role. Collapsing them into one route with a widened scope check would mean a single
`person_id` mistake exposes one senior's record to another.

**Silence resolves itself, in the person's days.** An offer that is still unanswered
`RESPONSE_WINDOW_DAYS` (2) simulated days after it was made is closed by the next
`POST /v1/simulation/advance` as an audited `no_response` outcome with actor `system` and
`detail.resolved_by = "response_window"` -- silence recorded as silence (half a unit of evidence
against the option in the preference learner), never as a refusal, and never as a decline reason
or a step toward suppression. While an offer is open, `Intervention.awaiting_reply_until` and
`OutreachSummary.awaiting_reply_until` carry the simulated date on which that happens; both are
`null` once an outcome exists or the offer was withdrawn. `OperationalMetrics.awaiting_reply` and
`.no_reply_recorded` count the two states separately. The date is for coordinator and evaluator
surfaces: the senior surface never shows it, because a deadline on an optional suggestion is
pressure. A reply posted after the clock has closed an offer is refused with a 422 that says the
offer "was closed as unanswered", not the generic duplicate wording.

Only the senior may write a candidate preference. A coordinator cannot mute a suggestion on someone
else's behalf, which is the entire point of the control existing. A day dispute never overwrites the
recorded metric: the observation stays exactly as the device reported it and the person's account is
attached alongside, because overwriting sensor data with self-report would destroy the provenance
guarantee and ignoring the person would be worse.

`POST /v1/interventions/{id}/outcome`, `.../follow-through` and `.../enjoyment` each 422 on their
own well-defined conflicts, in addition to Pydantic body validation: an outcome of
`coordinator_resolved` submitted directly rather than through case review, an outcome already
recorded for that intervention, outreach whose owning person has since withdrawn consent,
follow-through reported before an acceptance exists or already recorded once, enjoyment reported
before an _attending_ follow-through (`completed` or `partial` -- "how was it?" after "not this
time" is a question about an outing that never happened) or already recorded once, and -- on all
three -- an `intervention_id` that belongs to a scenario run the person is no longer on (a stale
reference from a prior `/v1/demo/reset`). `FollowThroughRequest.note`, `DayDisputeRequest.note` and
`ContextAnswerRequest.note` are all optional and capped at 280 characters;
`CandidatePreferenceRequest.reason` is optional and capped at 240. Every one of these is the
person's own words and stays on its own domain row; none of it is copied into the
operator-readable audit trail (`GET /v1/simulation/events`, any `person_id`). The audit event for
each instead records that the field was present (`note_present` / `reason_present`) -- the same
rule `.../week/{plan_id}/follow-through` follows below -- except `POST
/v1/people/{person_id}/consent`, whose `reason` is required rather than optional, so its audit
event records `reason_length` instead.

## The user-initiated loop (no screen)

The proactive loop begins with a policy trigger: the wearable changed, the ladder decided. These
routes are the second entry point, where the senior starts the loop themselves. **"Find me
something to do tomorrow" is not a behavioural anomaly and is deliberately not routed through the
policy ladder** -- that ladder answers "should we contact this person?", which is the wrong
question when they contacted us.

| Method   | Route                                              | Auth                    | Purpose                                                         |
| -------- | -------------------------------------------------- | ----------------------- | --------------------------------------------------------------- |
| POST     | `/v1/activities/search`                            | senior                  | Text or chips -> typed intent -> filtered, ranked options       |
| GET      | `/v1/activities`                                   | any authenticated       | The catalogue                                                   |
| GET      | `/v1/activities/{id}`                              | any authenticated       | One listing                                                     |
| GET      | `/v1/people/{id}/activity-preferences`             | senior, own person only | What Care+ believes about the kinds of activity they like       |
| POST     | `/v1/interventions/{id}/enjoyment`                 | senior                  | Whether it was any good, after "did you get a chance?"          |
| GET      | `/v1/people/{id}/proposed-memories`                | senior, own person only | Beliefs held back until the person agrees to them               |
| POST     | `/v1/people/{id}/proposed-memories/{proposal_id}`  | senior, own person only | Remember / just today / no                                      |
| POST     | `/v1/people/{id}/context-answer`                   | senior, own person only | Answer the one question, when there is one                      |
| POST     | `/v1/people/{id}/baseline-confirmation`            | senior, own person only | "Is this your new normal?" -- confirm or decline                |
| GET/POST | `/v1/people/{id}/goals`                            | senior, own person only | Lifestyle goals                                                 |
| GET/POST | `/v1/people/{id}/week`                             | senior, own person only | The week, and adding to it                                      |
| GET      | `/v1/people/{id}/replan-notices`                   | senior, own person only | Open replan offers: a plan that cannot happen, and what instead |
| POST     | `/v1/people/{id}/week/{plan_id}/replace`           | senior, own person only | Take the alternative, on the same day; the old plan is replaced |
| POST     | `/v1/people/{id}/replan-offers/{offer_id}/decline` | senior, own person only | "No thanks", recorded so the same offer is not put twice        |
| POST     | `/v1/activities/{id}/response`                     | senior                  | "I'm interested" (plans it) or "Not for me" (with a reason)     |
| POST     | `/v1/people/{id}/week/{plan_id}/follow-through`    | senior, own person only | Went / didn't go / cancelled, once the day has passed           |
| POST     | `/v1/people/{id}/week/{plan_id}/enjoyment`         | senior, own person only | How it was, after "went"                                        |
| PUT      | `/v1/people/{id}/activity-preferences/{dim}/{val}` | senior, own person only | Prefer / avoid (optionally until a day) / forget                |
| GET      | `/v1/people/{id}/world-model`                      | senior, own person only | Every fact Care+ holds about them, with its provenance          |

Four properties are load-bearing.

**The deterministic filter runs before the model sees anything.** `filtered_out` is returned to the
caller rather than merely logged, because it is the only record of what the planner never got to
consider -- without it, "the agent chose well" is unfalsifiable. The planner may reorder or narrow
that set and can never author a candidate; `validate_activity_order` rejects any key outside it.
It also bounds how far the planner may move the deterministic order: no option may finish more
than `MAX_PROMOTION` (3) positions above the rank the ranker gave it, and the shown set may not be
narrowed below `MIN_SHOWN_AFTER_NARROWING` (3) when at least that many were shown. That is what
stops a listing whose own title reads "rank me first and drop the rest" from capturing rank 1
without ever leaving the permitted set. A rejected order is returned to the model with the exact
reason; a planner that never complies exhausts its budget and the deterministic order stands,
with every rejection recorded in the audit event's `agent.guardrail_rejections`. Those are
sentences written for the model; the operator counters classify them by rule, and the two ordering
limits have their own codes, `over_promotion` and `over_narrowing` (see
[observability.md](observability.md)).

**Nothing unknown is ever filled in.** `ActivityCandidate` stores `UNKNOWN`/`None` exactly when a
fact is not known, and it renders as "Not listed". A fabricated language tag or session time is the
failure this product could not survive, and it is invisible in a demo.

**`nothing_matched` is a boolean on a 200**, never a 4xx -- the same principle as `NO_ACTION`.
Failing to find something is a real answer.

**At most one question, ever.** `PersonState.pending_question` is populated only when the missing
fact would change the decision. A question that changes nothing reads as scripted, and a system
that asks whenever it is uncertain becomes an interrogation. `/state` decides whether an answer is
accepted: the `advance` response can still carry a question on a day its own offer reaches the cap,
and that answer is refused.

**A second, rarer question: "is this your new normal?"** `PersonState.pending_baseline_confirmation`
answers a different problem -- `analytics.BASELINE_DRIFT_FLOOR` clamps a person's baseline so a
sustained decline cannot quietly become invisible, but nothing released that clamp for someone
whose life genuinely and permanently changed. It is asked only after the clamp has bound for
`CANDIDATE_BASELINE_STREAK_DAYS` (28) consecutive days, never shows a percentage or internal
vocabulary, and only the senior's own `confirm` re-anchors the reference; `decline` leaves the
clamp exactly as it was and starts a month-long cooldown before asking again. See
`baseline_confirmation.py`.

Care-team visibility into this loop is **aggregate only**: that a senior self-initiates and how
often, never the content of what they asked for. The senior's own history and the coordinator's
view are deliberately separate routes -- one scoped by identity, one by role -- so a single
`person_id` mistake cannot expose one senior's record to another.

`ActivityQueryRequest.text` is capped at 400 characters, and so are `ActivityIntent.raw_text`
(400), `ActivityIntent.language` (40) and `unparsed_terms` (20 items of 40) -- the same schema
the LLM parser fills, so a field with no ceiling would be a field an adversarial request could use
to stuff the next prompt or the senior's own response.
`ActivityIntent.parsed_by` is set by the server from the parser that actually ran; a client-sent
value is overwritten, so the audit trail cannot be made to claim a model parsed a chip request.
`ActivityIntent.max_distance_m` is clamped to `[0, 50_000]` metres by the schema itself (422
outside that range, unlike the silent clamps above), and is a **hard filter only when
`distance_is_explicit` is true** -- the flag the parser sets when the person gave a number.
"Within 800 m" is a limit someone knows they have; "near me" is a preference, and reading the
second as a hard 1 km cut-off removed half the catalogue from people who had named no limit at
all. The phrase still yields a figure the ranker uses; it simply never hides anything.

`ActivityIntent` also carries what the request named and what it ruled out.
`activity_types` (<= 5, from `ontology.ActivityType`) is **soft**: it ranks, it never filters,
because a hard content filter over a fourteen-programme catalogue would turn most requests into
"nothing matched". `excluded_activity_types` (<= 5), `excluded_environments` (<= 3, from
`IndoorOutdoor`) and `excluded_social` (<= 2) are **hard**: an exclusion cannot on its own empty
the catalogue, and showing someone the one thing they said they could not do is the harmful
error. Each exclusion rule is silent where the catalogue is silent -- an unlabelled listing is
never excluded, and `ActivityType.OTHER` ("labelled, and none of the above") is never what an
exclusion matched.

**Negation.** A negated phrase produces an `excluded_*` entry and never a positive value on any
axis, nor its complement: "nothing outdoors" is satisfied by indoors _and_ by sheltered, so
choosing either would narrow the search to somewhere the person never named. The negated word is
still consumed, so it does not appear in `unparsed_terms`, and the confirmation lines render it
("Not outdoors"). Axes with no exclusion field -- time window, intensity -- are simply left open
by a negation. Both parsers follow the same rule; the LLM tool schema states it and builds every
enum from the `StrEnum`s at import.

`ActivityCandidate` carries `activity_type` (single-valued), `activity_families` (multi-label) and
`format`; `category` remains as the display badge and is a rendering of `ontology.FORMAT_LABEL`.
`PUT /v1/people/{id}/activity-preferences/{dimension}/{value}` closes **every** dimension's
vocabulary and refuses `either` on intensity and company -- a listing is light or moderate, never
"either", so such a row could match nothing. A value outside its dimension's vocabulary is a 422.

`PreferenceDimension` gained `activity_type`, the content axis, closed to `ontology.ActivityType`
minus `other`. `category` is **deprecated**: its values are format labels ("Group class"), so one
belief about it covered nine unrelated programmes. It is never written and never removed -- a row
recorded before the split still renders and can still be forgotten -- and a `prefer`/`avoid` on it
is a 422 while a `forget` on it still succeeds.

`DimensionPreference` gained the ordinal half: `pivot` and `direction`. DISTANCE and INTENSITY are
lines rather than labels ("closer than about 1.2 km", "gentler than moderate"), because storing a
"too far" at 1.2 km as the bucket the listing fell in taught the opposite of what was said. It
also gained `positive_evidence`/`negative_evidence` (`strength` and `confidence` are both derived
from them, separately and order-independently), `scope`, `origin_id` and `superseded_by`.
`ActivityPreferences` gained `resolved: list[ResolvedPreference]` -- the same beliefs with tiers
applied, which is the only thing the ranker reads. `ScoreBreakdown` gained `coverage` and
`matched_axes`. All additive.

`ActivityGoalRequest.target_per_week` is optional and, when given, must be `1-14`.
`POST /v1/people/{id}/week` 404s when `activity_id` does not name a catalogue listing, and
separately 422s (via the fallback `ValueError` handler below) a `day` outside the current
Monday-to-Sunday window being planned.

### The closed loop: response, follow-through, enjoyment, preference, world model

`POST /v1/activities/{id}/response` is the tap the user-initiated loop learns from. `interested`
puts the listing on the person's own week when its day is inside the Monday-to-Sunday window being
planned (`planned: true`, `plan_day`) and otherwise records the interest and says so in `note`. A
listing with a fixed time is planned on its own day only -- a client `day` that disagrees is
ignored -- never on a day already gone (which would make it reportable at once), and never when it
is `FULL`; `POST .../week` 422s the same three cases. It is also planned only when the listing was
among the results this run actually showed this person (`shown` on the audit event): a listing the
deterministic filter removed -- it encodes what the person asked for -- is recorded with
`planned: false` and the note "Noted. This one wasn't among your results." A `reason` on an
`interested` reply is dropped, and a `query_id` in any shape the server never issued is dropped.
`not_for_me` with a reason that names a kind of activity (`too_far`, `too_tiring`, `bad_timing`,
`not_for_me`) moves that dimension exactly as an outreach decline does and returns
`preferences_updated`; `bad_day` and `prefer_something_else` move nothing. Nothing moves at all
when the listing does not carry the fact the axis needs -- a "too tiring" on a listing with no
intensity records nothing rather than inventing one.

An optional `clarification` (`ClarificationScope`) says how far that reason reaches: `time_of_day` /
`weekday` / `this_slot` after `bad_timing`, `this_activity_type` / `this_format` / `this_venue` /
`this_one` after `not_for_me`. It is skippable in its own right, and without it the reason stays
**item-level**: one "bad timing" (`this_slot`) or one "not for me" (`this_one`) is about the session
in front of the person -- the 14-day cooldown already holds that listing back -- and it only
generalises once a second answer about a **different programme** agrees with it or a chip widens it
(`time_of_day`/`weekday`, or `this_activity_type`). An item-level answer about the same programme as
the belief's latest origin adds no evidence at all, whether the belief is still held back or has
already widened (a chip-widened one included): the same listing declined again on another day, a
sibling session of the same programme, or an outreach decline followed by a search decline on that
programme teaches nothing more, and `preferences_updated` stays empty. Only the latest origin is
remembered, so alternating programmes (river, park, river) still count each answer -- a bounded
approximation (ADR 0006, second-round amendment, 2026-09-15). `too_far` and `too_tiring` are the
exception: they write a ceiling at the listing's own distance or intensity immediately.
`preferences_updated` reports what the answer actually taught, never a row the ranker is still
holding back. Repeating the same answer about the same listing on the same simulated day records the
tap and infers nothing from it again (`inference_skipped: duplicate_same_day`). `query_id` (<= 64
chars) and `rank_shown` (1-50) are opaque evaluator labels, never used for ownership: the `query_id`
is checked against the searches this run issued for this person (`query_id_verified`), dropped when
it was not one of them, and `rank_shown` is clamped to that query's result count. A verified
`query_id` sent without a `rank_shown` is valid: 200, `query_id_verified: true`, `rank_shown` stays
`null` (it used to 500). None of these is ever a 4xx -- the tap is the person's either way. A
declined listing is never removed from the catalogue: it is held back in ranking for
`activity_search.DECLINE_COOLDOWN_DAYS` (14 simulated days) and then may return.

`.../week/{plan_id}/follow-through` accepts one report per plan (`went`, `did_not_go`,
`cancelled`), only once the plan's day is in the past on the simulated calendar (422 "not happened
yet" before that, 422 on a repeat); `.../enjoyment` requires a `went` report first. Both 404 for a
plan that is not the caller's. The audit event for a follow-through records `note_present`, never
the note itself. A racing double tap on the same row is a 409, not a 500.

`PUT .../activity-preferences/{dimension}/{value}` is the person's own control over what is
remembered about the kinds of activity they like. `prefer` and `avoid` write a `senior_statement`
row (strength +1.0 / -1.0, `confirmed`), optionally `until` a day (expiry is decided on the
person's simulated calendar, never the wall clock) and optionally with their `stated_text`.
`forget` **retracts** every row on that `(dimension, value)` -- theirs to forget. It stamps
`superseded_by` rather than deleting: readers skip a superseded row, so nothing is shown, the
response still carries `preference: null` and `removed_rows`, and the next
observation on that key starts a fresh belief from zero. Deleting looked identical to the person
and was worse in two ways -- it rewrote the audit trail, and under evidence counts it left nothing
to stop the very next tap resurrecting a belief they had just erased. (ADR 0006.)

`value` is a path segment bounded to 160 printable characters and must be one of that dimension's
own values (`near`/`far`, `light`/`moderate`, `morning`/`afternoon`/`evening`,
`indoor`/`outdoor`/`sheltered`, `social`/`solo`, an `ActivityType`; 422 otherwise) -- a stated
value that could never match a listing would be a confirmed belief that means nothing.

A stated DISTANCE `near` or `far` carries no number. Since 2026-09-15 (round 2) a near-leaning
statement (`prefer near` or `avoid far`, and the `less_travel` goal) narrows where distance starts
to cost to at most `preferences.NEARBY_RADIUS_M` (1000 m), after any learned ceiling or floor, and
never removes a listing. A far-leaning statement (`prefer far` or `avoid near`) changes nothing at
any tier, because words with no number in them never widen a tolerance; it resolves apart from the
near-leaning ones, so it cannot silence them either -- a `less_travel` goal beside a stated "far"
keeps the 1 km cap. The world model reports such a far-leaning belief (and a learned DISTANCE row
with no number) with `in_effect: false` (`preferences.belief_in_effect`; ADR 0006, second-round
amendment).

A change of mind (`avoid` then `prefer`) is a new statement: the count restarts and the earlier
words are dropped. Repeating the _same_ statement is one person saying it again, not a second
piece of evidence, so the count does not grow.

**Ratification.** A statement on a `(dimension, value)` an inference already held **consumes**
that inferred row: it is stamped `superseded_by` the statement, and the statement records what it
consumed in `origin_id`, which is what puts it at `SourceTier.RATIFIED`. "That's right" used to
add a second row beside the first and touch neither, so both rendered -- and on a reversed stance
the orphan became a contradiction the system had manufactured against a belief the person had just
agreed with.

**Precedence, not averaging:** the highest active tier wins an axis outright (`preferences.resolve`
-> `SourceTier`); the lower-tier beliefs are shown as `contradicted_by` rather than blended in, and
the world model reads that list rather than pairing rows itself.

**A demo reset starts the story over, but no longer deletes a person's dimension preferences**
(ADR 0004, `docs/adr/0004-run-scope-activity-dimension-preferences.md`). `POST /v1/demo/reset`
rewinds the simulated calendar to the fixture's anchor day and starts a new run; engagement
(interested / not for me / went / enjoyed per listing) is read per run, exactly as before. What
changed is `activity_dimension_preferences`, and it splits by what kind of fact a row is, not only
by `source`:

- A **standing** `senior_statement` row -- `prefer`/`avoid` with no `until` -- is a standing
  instruction about the person, like the outreach mutes under `/preferences`, and is never scoped
  to a run at all (`run_id` stays `null`); it survives a reset and keeps applying until an
  explicit `forget`.
- A **time-boxed** `senior_statement` row -- `until` a day -- is a promise about a day on the
  calendar of the run it was stated in, not an absolute fact independent of which story is being
  told, so it is stamped with that run's id. A reset rewinds the calendar back to the fixture's
  anchor day, which is _behind_ whatever day the statement was timeboxed against; without
  run-scoping this row, a promise that had already lapsed ("avoid until day 3", now well past it)
  would read as not-yet-expired again the moment the calendar falls behind its `until` date, and
  reappear. Run-scoping closes that: the row goes inactive the moment a different run becomes
  active, regardless of what the calendar says.
- A `decline_reason`/`inferred` row is stamped with the run that produced it, because that
  evidence -- a tap, an enjoyed activity -- only means something against the simulated history it
  came from.

**The world model's outreach facts are run-scoped too**
(`sql_repository._outreach_responses`), for the same reason and by the same rule the week plan and
the attendance facts (`_attended_series`) already follow: the previous operator's offers are not
this run's memory, and a fresh demo used to open with the last run's "You said no to …" already in
the senior's own `/world-model`. Nothing is deleted — the `interventions` and
`intervention_outcomes` rows stay exactly where they are, and the person-level Beta-Bernoulli
learner (`_preference_learners`) still reads every one of them, because a posterior is about the
person, not about one demo run.

**So is every listing of individual outreach events.** `list_outreach_summaries`, which backs both
the senior's own `GET /v1/interventions/history` and the coordinator's
`GET /v1/coordinator/people/{id}/outreach-history`, filters `InterventionRow.run_id` the same way
and has since it was first written -- a reset empties both history views for the new run
immediately, while the retired run's `interventions` and `intervention_outcomes` rows stay on disk
untouched. `test_a_reset_does_not_carry_the_previous_runs_outreach_into_history`
(`apps/api/tests/test_follow_through_api.py`) pins this against both routes, plus the two things a
reset must _not_ do to them: delete the rows, or move the person-level posterior that reads them.

Not every reader of `interventions`/`intervention_outcomes` is run-scoped, and the exceptions are
deliberate, not an oversight: `_preference_learners` (the per-candidate and per-decision posterior),
`_candidate_outcome_counts` (the same posterior's sample size, shown to the outreach planner and on
`GET /v1/metrics`), `_candidate_activity_counts` (the offered/accepted/declined/completed counts on
`GET /v1/people/{id}/preferences`) and the decline count behind deterministic suppression
(`_suppress_after_repeated_declines`) all read across every run a person has ever had. Each backs a fact that is documented as being about the _person_, not
one demo story -- a learned score, a durable candidate preference, or a "declined three times"
threshold -- the same way a standing `senior_statement` or a `candidate_preferences` mute is never
scoped to a run (see above and ADR 0004). `test_a_candidate_is_suppressed_after_three_declines`
already pins the suppression count surviving a reset between each decline; nothing in this change
alters that.

In every run-scoped case, once a reset makes a different run active, every reader treats that row
as absent, the same way it already treats a calendar-expired one -- but the row is not deleted, it
is reused in place, observations restarted at one, the next time the same kind of evidence is
observed. One consequence worth stating plainly: reuse overwrites the retired run's observation
count rather than preserving it, so an inferred belief's history cannot be compared across
separate runs, only read fresh within whichever run is currently active.

**The activity catalogue starts the story over with the calendar.** A reset rewinds the simulated
day; the listings under `/v1/activities/search` are anchored to that day, so they are rewound with
it (`sql_repository._reanchor_fixture_sessions`). Each fixture listing's session time and its
`availability` -- the two things a run mutates, through the weekly roll-forward that keeps a
listing from falling into the past and through the `programme_becomes_full` event -- go back to
what `fixtures.synthetic_activity_candidates` says they are on the anchor day. Without this the
calendar restarted and the catalogue did not: a run that advanced several days and then reset began
again with every listing a week or more ahead of today, and "something outdoors tomorrow" matched
nothing for the rest of that run.

This is the simulated story restarting, not a claim that a real venue moved a class. Only rows this
repository seeded are touched (`metadata_source = aac_fixture:fixtures.py`); a listing from a real
feed keeps its own session time, which is a fact about the world rather than about this story. No
listing row is deleted and no `activity_id` changes, so the week plans and offer responses that
reference them still resolve -- listings are fixture reference data, not one person's state, and a
reset has never deleted them.

The catalogue is shared by every persona while each has its own anchor day, so the rewind is
floored at the furthest-ahead active run: with a single active persona -- the demo, the offline run
and the browser suite -- that floor is that persona's own anchor day and the rewind is exact, and
with several, a persona whose calendar is behind the floor sees its listings sit further out until
it catches up. A per-run catalogue is the real answer if concurrent personas ever stop being a
demo-only concern.

**Consent pauses inference.** While consent is withdrawn a search is still answered and a tap is
still recorded, but nothing new is _inferred_ from it -- no `decline_reason` or `inferred` row is
written. What the person states through the PUT is still honoured. The rule is deterministic and
lives in the repository, not in any learner. This is one of five named consent scopes -- see
`docs/adr/0001-consent-scope-model.md` and `silverloop.consent_scopes` for which of them the one
stored consent boolean actually gates (outreach, inference) versus always permits (this search
loop, the underlying signal analysis, the ambient context fetch).

`GET .../world-model` returns `PersonWorldModel`: typed `PersonFact`s assembled read-only from
stores that already exist, each with `source_type` (`explicit` / `inferred` / `external` /
`fixture`), the concrete `source`, categorical `confidence`, `evidence_count`, first/last observed,
`expires_at`, `confirmed`, `evidence_ids`, `contradicts` (keys of facts about the same value that
lean the other way) and `stale` (an inferred fact nothing has reinforced for 90 days, measured on
the person's own simulated calendar -- `run.current_day` minus the calendar day of its last write,
never the wall-clock delta between them). Every
`statement` is written in the second person and carries no step count, tally or percentage; those
numbers live only in the fact's own `evidence_count`/`value` fields and in the coordinator's
`world_model_quality` counts. Fixture biography is labelled `fixture`, never `explicit`, and a
seeded demo consent (`ConsentEvidenceRow.source == "synthetic_fixture"`) is read the same way --
`fixture`, `MEDIUM`, unconfirmed -- since activating it was nobody's own choice; only a person's
own recorded consent is `explicit`/`HIGH`/confirmed. A stated `either` on any dimension is never
narrated as a lean towards one side. `typical_response_hour` is converted to the person's local
hour (`local_hour`, Singapore local,
never the raw UTC one) and is left out of the model entirely while the product has no real
response timestamps to read (`ADAPTER_MODE=fixture`, true of every build today): a simulated run
can advance a week of days inside a real minute, so the hour would measure the operator's
clicking, not a routine. A context-question answer is a fact about one day and carries an
`expires_at` at the end of it. `gaps` states what is not known and will not be guessed. Only the
senior may read it; the coordinator's `/v1/metrics` carries `world_model_quality` counts and never
a fact.

**An outreach fact states what the person actually did, and nothing else.** The `LEARNED_RESPONSE`
fact for a piece of outreach (`source == "intervention_outcomes"`) branches on the recorded
outcome, never on "accepted or not": they followed it through, they asked to hear more, they said
no (with their own one-tap `DeclineReason` repeated in plain words, never as its token), or they
said maybe later. A response window that closed on silence reads _"You did not reply to …"_, and an
offer with no outcome recorded at all — still open, possibly on the person's own home page — yields
no fact whatsoever, as does an outcome somebody else produced (a coordinator closing the case,
activity recovering on its own). Silence and an unanswered offer are never narrated as the person's
decision; this is the same rule the coordinator queue already states as "Closed as silence, not a
refusal" and `sql_repository._resolve_unanswered` records as its learning boundary.

**Distances are labelled.** `ActivityCandidate.distance_basis` is `listing_static` for every
distance in this build (a fixed figure on the listing, no origin, no route) and `unknown` beside a
`None`; the card says "from the listing" so a number never reads as a measurement.

**The order is explainable, and the explanation is not in the senior's payload.** The stored
`activity_search` audit event (`GET /v1/simulation/events`) records, for evaluators:

- `ranking`: one row per result with exactly `activity_id`, `rank`, `tier`, `total`,
  `matched_axes`, `coverage`, `variety_promoted`, `series_deferred`, `reasons_suppressed` and
  `factors` (factor name → weighted contribution). `tier`, `total` and `matched_axes` are the sort
  key's own numbers, so the order is checkable from the rows alone. Factor values, notes and
  per-axis detail are not repeated here; the evaluator-only Ranker Inspector (below) is where they
  are read.
- `ranking_weights`: the factor weights the contributions were multiplied by.
- `planner_agreed_with_ranker` (against the deterministic order captured _before_ the planner ran)
  and `planner_contested` (at least two permitted candidates). Both are `null` unless the planner
  actually ran (`planner_mode == "agent"`) — a fallback run kept the deterministic order by
  definition — and both are also `null` when the snapshot went stale during the call
  (`snapshot_stale: true`): the planner's order was discarded, so an agreement would be the ranker
  agreeing with itself.
- `agent`: the planner's evidence, including `provider` and `transport` (`live` | `recorded`)
  whenever a model client was requested, so a recorded run is never audited as though a live model
  had answered.

`ranking`, `ranking_weights`, `agent`, `result_ids` and `intent` are the evaluator-only keys: the
copy of the event returned inside `ActivityQueryResponse.audit_event` carries the counts and modes
but none of them. `RankedActivity` carries the candidate, its rank, its `series_key` (an opaque key
the client groups sessions by, equality only), `reasons` -- at most three positive, grounded
lines for the card face -- and `more_reasons`, every other eligible line, which the senior card
shows inside its details disclosure (labelled "More details and reasons" when `more_reasons` is
not empty). Reason lines are comma-phrased; the catalogue filler is the bare catalogue label
("Group class."), and a card whose face would hold only that filler shows no "Why this may suit
you" list. Nothing eligible is dropped: `reasons_suppressed` in the audit row equals
`len(more_reasons)` (2026-09-15, round 2; it used to count lines left off the card).

## The Activity Ranker Inspector (evaluator-only, no screen)

`POST /v1/evaluator/ranker/inspect` and `GET /v1/evaluator/ranker/presets` trace one activity
ranking. No current screen calls them. Both require `demo_operator` (a `senior` or `coordinator` token
is 403; with auth off they are open like every demo route). Checked in this order: an unknown
`person_id` is 404 (even when the body also names a preset), a person with no active run is 409,
and a body outside the allow-list is 422 -- every request model is `extra="forbid"`, and an
unknown preset, another person's preset, an unknown activity id, or a counterfactual the write
path would refuse (a past `temporary_avoid_until`, `other` as a stated kind) is also 422. Any
other failure inside the inspector is a 500, never relabelled as 404 or 422.

**Read-only, never persisted.** The route opens one read session and writes nothing: no audit
event, preference, engagement, plan, replan offer or catalogue change. Every preview edits
in-memory copies and is discarded with the response (`tests/test_ranker_inspector.py` compares
every table's rows before and after).

**One execution, the product's own.** `search_activities` and the inspector both run
`activity_search.rank_with_trace` (filter, then score and sort, then series dedupe, then the
variety swap) over the same `_ranking_inputs`. The trace's final order is exactly the search's.

Request (`RankerInspectRequest`): `person_id`, `text` or `intent` (text wins, as on search),
`history_preset`, `counterfactual`, `feedback`, `compare_preset_to_live` (default `false`),
`run_planner` (default `false`).

- `counterfactual.request`: `time_window`, `social_preference`, `environment`, `activity_types`,
  `max_distance_m`, `distance_is_explicit` (applied to a copy of the parsed intent).
- `counterfactual.world_model`: `travel_ceiling_m` (folded as a `too_far` through
  `preferences.apply_decline`; reported `no_effect` when it would not lower the tolerance),
  `temporary_avoid_activity_type` + `temporary_avoid_until` (a time-boxed avoid statement).
- `counterfactual.world`: `rain`, `mark_full` (activity ids).
- `feedback`: one `not_for_me` (+ `reason`, `clarification`), `interested`, or `enjoyment`
  (+ `enjoyment`, `liked`), folded through the production learners and engagement counter.

Response (`RankerInspectResponse`):

- `baseline` is the execution on screen: live state, with `history_preset` folded in when one is
  given (its `preview` is then `true`).
- `variant` and `changes` exist only when a `counterfactual` or `feedback` is given. The variant is
  that same baseline (preset included) with them applied, so `changes` is the preview's effect
  alone. A preset on its own produces no variant.
- `compare_preset_to_live: true` asks what the preset itself changed: `baseline` is live state
  and `variant` is live state plus the preset. It needs a preset and cannot be combined with a
  `counterfactual` or `feedback` (422).

`changes` is a list of structured `RankChange` rows (rank movement, top-three entry and exit, filter
status, factor deltas, fact changes; a `fact_changed` row names its `changed_fields`); the wording
is the web's. `scoring` also carries the ranker's own constants: `weights`, `factor_descriptions`
(one plain sentence per factor), `engagement_weights` and `top_n`. `person_context` names where
distance starts to cost for this search -- `travel_cost_starts_m`, with `travel_cost_start_basis`
(`default | learned_ceiling | learned_floor | asked_radius | stated_near`) and the soft
`asked_radius_m` a distance phrase implied (`null` when none or when it was a number) -- computed by
the same `activity_search.travel_cost_start` that scores friction. Every `unknown` request-axis or
belief outcome carries `unknown_reason`: `listing_silent` (the listing does not say) or
`mismatch_not_counted` (it says something different that the rule deliberately counts neither way,
such as another kind of activity or a listing labelled "none of the above"). Each
`ActivityRankingTrace` carries the parsed request and its axes, the person context (`TraceFact` with
provenance `person_said | learned | temporary | goal | scripted_history`, `scripted_contribution`,
whether and why it was not used -- taken from what scoring actually read -- and
`recorded_not_applied` rows the resolver held back), unknown axes with materiality measured by
re-ranking, retrieval, every filter outcome in rule order, every scored candidate (factors, tier,
typed sort key, per-axis and per-belief outcomes, engagement, reasons before composition,
`reasons_shown` and `more_reasons`, stage positions), series dedupe deferrals, the variety swap, the
LLM stage, the final top three with the stage that placed each, the senior screen's grouped cards,
and an integrity classification of every positive factor on a shown card (`grounded | on_expand |
silent_by_design | unsupported`; `on_expand`, formerly `capped`, means the factor's line is in
`more_reasons`, which the inspector labels "Under ‘More details’"). A fact the ranker did not use
says why; for DISTANCE that is `never_widens` (a far-leaning statement, at any tier),
`not_winning_tier` (an outranked near-leaning statement or line) or `no_distance_line` (a learned
row with no pivot), never `deprecated_axis`.

**The LLM stage.** Not run unless `run_planner` is true and the server has the LLM enabled;
`status` is the planner mode (`agent`, `fallback_*`), `not_run_in_preview`, or `no_candidates`
when nothing survived to be ranked (what search records as `planner_mode` then). `transport` is
`off` when the server has the planner disabled, otherwise `recorded` or `live` from
`LLM_PROVIDER` (`provider` always names what is configured); a recorded transport asked to
re-rank any state that is not live (a preset, counterfactual or feedback applied) will miss its
recording and fall back (`recording_may_miss`). The trace never carries model reasoning,
proposals, prompts, read-tool arguments, tool summaries, guardrail rejection text or exception
text: tool calls are names and permitted proposed keys, guardrail rejections are rule-code
counts, and a provider error is its exception class at most. Nothing a person stated in their own
words (`stated_text`, goal text) is included. Of the LLM intent parse, `unparsed_terms` are kept
only when they appear in the request (the rest are counted in `unparsed_terms_withheld`). The one
model-written value kept regardless is `language`, because the filter, reason lines and
`understood` used it verbatim; it is flagged `language_model_supplied_ungrounded` when the request
text does not contain it.

**Scripted histories.** No persona is seeded with activity responses, so on live state every
persona ranks alike. `lim-social-nearby` (Mdm Lim) and `ravi-knee-quiet` (Mr Ravi) are allow-listed
event scripts (declines with reasons, enjoyments, interests; keyed by programme and days ago),
folded through the same learners on top of live state with `scripted:` origin ids. They are
synthetic demo data and never saved. A belief the preset alone produced is `scripted_history`; a
live belief the preset added evidence to keeps its live provenance with `scripted_contribution:
true`.

## The review-threshold calibrator (coordinator, no screen)

A coordinator's structured false-alarm judgement can lead to a per-senior **review setting** (how far
below baseline, for how many low days, before a human is asked). The agent or fixed rule only
proposes; a coordinator approves every change. No current screen shows it, but the live setting
still feeds `policy.decide` every simulated day. Design: `docs/review-threshold-spec.md`, ADR 0008.

All routes below require `coordinator` (`senior` and `demo_operator` are 403; with auth off they are
open like every demo route). Unknown person, proposal or decision is 404; a state conflict (already
decided, stale `shown_on_day`, cooldown, weekly cap, consent withdrawn, a demo reset while waiting,
manual set not allowed) is 409; an invalid body (a mixed setting such as 35%/4 days, a two-step
jump, `cause_confirmed=false` on a loosening, a system-only rejection reason) is 422.

| Method | Path                                                        | Purpose                                                                         |
| ------ | ----------------------------------------------------------- | ------------------------------------------------------------------------------- |
| GET    | `/v1/coordinator/people/{person_id}/review-threshold`       | Live setting, bounds, open proposal, checking period, history, notice preview   |
| GET    | `…/review-threshold/replay?severity_pct=&persistence_days=` | Code-computed "how much later would cases have reached you" over stored history |
| POST   | `…/review-threshold/proposals/{proposal_id}/approve`        | Approve (records the coordinator `sub` and the replay shown)                    |
| POST   | `…/review-threshold/proposals/{proposal_id}/reject`         | Reject with a reason (may start a retry)                                        |
| POST   | `…/review-threshold/manual`                                 | Set by hand, one step, when the round allows                                    |
| POST   | `…/review-threshold/confirm-starting`                       | Confirm the starting setting (gates nothing)                                    |
| POST   | `…/review-threshold/decisions/{decision_id}/reconfirm`      | Restart a looser setting's 60-day clock                                         |

`POST /v1/cases/{case_id}/review` accepts `reached_too_late` ("this should have reached me sooner")
and the new `override_reason` `not_a_concern`. The review commits first; any calibration, tightening
or write-up runs afterwards with no database session open, and a failure there never fails the
review. `PersonState.review_threshold_notice` carries the fixed senior notice for seven simulated
days after a loosening takes effect or a setting goes back. `POST /v1/demo/reset?person_id=` resets
one persona. `GET /v1/evaluator/people/{person_id}/senior-home` (`demo_operator`) is a read-only
preview of what a senior would see; it writes nothing.

### What each review teaches (calibration trust)

Additive contract; no new routes. Design: `docs/calibration-trust-spec.md`, ADR 0009; terms in
`CONTEXT.md`.

- **`ReviewRequest.context_gap_category`** (optional): `away`, `already_in_touch`,
  `resting_or_recovering` or `other_known`. It is allowed only with `human_action=override` and
  `override_reason=known_context`; any other combination is a 422. It is stored on the review,
  returned as `ReviewAction.context_gap_category` in `action_history`, and audited only as
  `context_gap_category_present: bool`.
- **`CaseReviewResponse.lesson`** (`ReviewLesson`: `review_id`, `kind`, `reason`,
  `context_gap_category?`, `summary`). `kind` is `counts_toward_review_setting`,
  `records_context_gap` or `teaches_nothing`, and `summary` is fixed template text (never the note,
  never an activity figure). It is derived on read from the stored review.
- **`ReviewThresholdState.receipt`** (`ReviewSettingReceipt`): the `subject` (`open_proposal`,
  `live_setting` or `next_proposal`; only a looser agent or fixed-rule proposal is ever the open or
  live subject, so an asking-sooner proposal or a manual set leaves `next_proposal`), `counted` of
  `needed`, the window and `counted_from_day`, the
  fixed `rule`, and one entry per review in the run. Each entry has a `status` of
  `counted_toward_loosening`, `asked_sooner` or `excluded`, plus the `exclusion` reason, whether the
  proposal `cited` it, and what it led to. Entries carry no reviewer and no note.
- **`ReviewThresholdState.context_gaps`** (`ContextGapTally {total, by_category, disclosure}`): the
  person's known-context overrides in the active run. It changes nothing.
- **`ReviewCase.since_last_review`** (`SinceLastReview`: `anchor_kind`, `anchor_day?`,
  `anchor_recorded_at`, `nothing_new`, `items`). It says what changed since the latest human review,
  or since the case opened (`anchor_kind=case_opened`). Each item is a fixed sentence with counts, days and the
  `evidence_ids` it was read from. Nothing the senior said, no note, and no step figure is included. It
  is `None` once the case is resolved. It is populated only on `GET /v1/cases/{case_id}` and in the
  `case` of `POST /v1/cases/{case_id}/review`. `GET /v1/coordinator/queue` and the `created_case` of
  `POST /v1/simulation/advance` / `GET /v1/simulation/latest` share the `ReviewCase` shape but always
  return `since_last_review: null`, so the queue does not gather a delta for every unresolved case.
  No senior route's response schema includes it.

## Fallback error handling

Beyond the per-route `try`/`except` blocks documented above, `main.py` registers three
app-level exception handlers (`register_exception_handlers`) that catch whatever a route's own
handling did not, so a route that forgets to convert a repository error no longer surfaces as a
bare, undocumented 500:

- **`KeyError` -> 404** ("Person not found"). In practice the only `KeyError` left uncaught by a
  more specific local handler is `_active_run`'s `KeyError(person_id)` for a `person_id` that does
  not exist in the database, so this is what an unknown person on any of the
  `/v1/people/{person_id}/...` and `/v1/coordinator/people/{person_id}/...` routes returns, even
  on the ones without their own local `except KeyError`.
- **`RuntimeError` -> 409**, but only for the specific, narrowly matched "this person was never
  seeded" family: `_active_run` raising "No active scenario run" (a real person who has never been
  through `/v1/demo/reset` or the seed step for this database) or `_load_metrics` raising "Active
  scenario contains no wearable metrics". The response text tells the caller to reset or seed and
  retry. Any other `RuntimeError` is deliberately re-raised rather than mapped, and still becomes
  a plain 500 -- this handler exists to give one well-understood condition a meaningful status
  code, not to launder every internal error into "just retry".
- **`ValueError` -> 422**, with `str(exc)` as the detail, for any route whose own body does not
  already catch `ValueError` locally. This is what makes `POST /v1/cases/{id}/review` return 422
  (rather than an undocumented 500) when a case's person has withdrawn consent since it was
  opened, and what makes `POST /v1/people/{id}/week` return 422 for a `day` outside the current
  Monday-to-Sunday planning window -- neither route has a local `except ValueError`, so both rely
  on this handler.

A route's own local exception handling always takes precedence and produces its own, more specific
message (e.g. "Activity not found" instead of the generic fallback), so read the per-route notes
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
  the idempotent `event_id` replay of `POST /v1/simulation/advance` and by `GET /v1/simulation/latest`.
  `GET /v1/simulation/history` still reads such snapshots through a narrow view. Nothing is migrated or
  reset automatically; the recovery is `POST /v1/demo/reset?person_id=`, which the web offers as "Reset
  local synthetic demo". See `stored_state.py`.
- `code: "internal_error"`: a pydantic `ValidationError` raised while the server builds or re-reads a
  model, or a FastAPI `ResponseValidationError`. The first is a `ValueError` subclass and used to reach
  the `ValueError -> 422` handler above, or a route's own `except ValueError`, with raw validation
  text. Routes with a local `except ValueError` now re-raise `ValidationError` first. Request-body
  validation (`RequestValidationError`) is unchanged and still returns FastAPI's 422. The one
  deliberate 422 for a model rejection is `GET .../review-threshold/replay`, whose candidate is built
  from the caller's query parameters; its detail is a fixed sentence, never the validation text.

A 500 that none of these handlers classifies (an unexpected exception) is still Starlette's plain
`Internal Server Error` text, not a `ServerErrorBody`.

One gap remains genuinely open, because it is not an exception at all: **`GET
/v1/people/{id}/activity-preferences` never 404s.** `activity_preferences` reads
`activity_dimension_preferences` directly with no existence check on `person_id`, so an unknown
person gets 200 with an empty `dimensions` list rather than 404.

This is not a production authentication contract. Do not expose the demo API publicly without an
identity layer, durable audit storage, rate limiting and an approved retention policy.
