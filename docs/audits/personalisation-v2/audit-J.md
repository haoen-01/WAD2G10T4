# Audit J — External ecosystem / context sources + catalogue metadata quality

Worktree: `/Users/ianpong/Projects/ismoggers-v2` @ `010aa96` (== origin/main). Read-only. No API or
network calls were added or made; the only thing executed was a pure validation script over the
fixture catalogue (`J_validate.py` beside this file; command and output quoted in Part 2).

Conventions: every path is relative to `apps/api/src/silverloop/` unless stated. Severity per the
brief: P0 correctness/safety, P1 high-value, P2 enhancement, P3 research.

---

## PART 1 — External context sources: what each would actually change

### 1.0 What exists today (the substrate every verdict below is measured against)

**Two live sources, one switch, off by default.**
`context.py:31-33` wraps data.gov.sg rainfall, data.gov.sg 2-hour forecast and `date.nager.at`
public holidays. `config.py:97-99` (`external_context_enabled=False`, 3 s timeout, `SG`).
`main.py:100-107` builds the provider only when enabled _and_ the runtime profile is not
`offline`. `.env.example:121-124` documents it. Failure is an explicit
`confidence=0.0 / available: False` evidence item, never silence (`context.py:159-176`,
`223-237`), pinned by `tests/test_context.py:122,144,180`.

**Where the signal is consumed — three call sites, one boolean.**
`ContextSignal` (`models.py:115-119`) is `rainy: bool, air_quality: str = "normal",
holiday: bool, note`. It reaches:

1. `policy.py:78-86` — the proactive ladder's rain gate: `rainy and sustained_low_days < 2 →
NO_ACTION`. Holiday is **not** read by the ladder (confirmed: no `holiday` in `policy.py`;
   WAYFINDER:1048-1049 says so deliberately).
2. `activity_search.score_candidate` (`activity_search.py:734-746`) via
   `sql_repository.search_activities:3971` (`rain_forecast=state.signal.context.rainy`) — the
   `context` factor (weight 1.5, `activity_search.py:123-130`): +1.0 indoor/sheltered, −0.5
   outdoor, 0 unknown, only when the person left environment open.
3. `replanning.notices_for` via `sql_repository.py:5638-5643` — an outdoor plan **for today** on
   a rainy day gets a notice (`replanning.py:163-166`).

**How it is merged.** `sql_repository.advance:1624-1656`: the live signal can only OR a `True`
into the scripted event's context, gated by `expires_at >= evaluation_instant`; expired items are
recorded under `expired_context_evidence` (`:1757-1758`). Consent never gates the fetch
(`consent_scopes.py:19-20`; ADR 0001 line 182: "Carries no person identifier").

**Resolution of the weather signal is the whole island.** `context.py:126-129` takes
`max(values)` over every rainfall station in Singapore; `:145-152` flags rain if _any_ area's
2-hour forecast mentions rain/shower/thundery. WAYFINDER:253 already records this. There is no
per-person location field anywhere: `PersonRow` (`db_models.py:26-32`) is `person_id,
display_name, preferred_language, created_at`; `PersonaProfile` (`fixtures.py:29-60`) carries
no area. `world_model._gaps` (`world_model.py:517`) states it honestly: "No home area or usual
travel distance is recorded; distances are from a fixed listing."

**Distance today.** `ActivityCandidate.distance_m` + `distance_basis` (`models.py:743-744`,
`DistanceBasis` `:682-693`: only `LISTING_STATIC` and `UNKNOWN`). The DB row has **no
`distance_basis` column** (`db_models.py:278-333`); the reader _infers_ it at
`sql_repository.py:3678-3684` (`LISTING_STATIC if row.distance_m is not None else UNKNOWN`).
Row does carry `location_latitude/longitude` (`:309-310`) and `location_postal_code` (`:308`),
all seeded `None` for lat/lon (`fixtures.py:895-899` sets name/address/postal only). The web
labels it "(from the listing)" (`apps/web/lib/view-models.ts:1079-1100`).

Distance is read in four places, three of which disagree about what "near" means:

| Reader                         | Threshold                             | File:line                                                     |
| ------------------------------ | ------------------------------------- | ------------------------------------------------------------- |
| Intent parser "nearby" default | 1 000 m                               | `intent.py:75`                                                |
| Filter `_too_far`              | whatever the intent said              | `activity_search.py:184-192`                                  |
| Friction factor                | free ≤ 500 m, linear to −1 at 5 000 m | `activity_search.py:136-137, 596-603`                         |
| Preference bucket near/far     | 2 000 m                               | `preferences.py:102, 131-134`                                 |
| `_NEAR_THRESHOLD_M = 1000`     | **defined, never used**               | `activity_search.py:95-98` (grep: sole hit is its definition) |

That dead constant carries a comment claiming it "matches the near/too far default in
`intent.py`" while the learner actually buckets at 2 km — the mechanism behind the lead's "too
far at 1.2 km learns dislikes near" flaw. Confirmed: `_declined_value` (`preferences.py:179-180`)
records `_distance_bucket(1200) == "near"` with a negative strength; and when distance is `None`
it fabricates `"far"`.

---

### 1.1 OneMap — route distance / time, barrier-free routing

**Decision it would change.**

- `activity_search._too_far` (`:184-192`): today compares `candidate.distance_m` (a typed
  fixture figure with no origin) against `intent.max_distance_m`. With a routed distance from a
  coarse origin the same branch works unchanged; only the input's provenance changes.
- `activity_search._friction` (`:596-603`): the linear 500 m → 5 km penalty would be over a real
  walking/transit figure instead of an authored one.
- `preferences._distance_bucket` (`:131-134`) and therefore what `TOO_FAR` teaches
  (`_declined_value:179-180`) and what `LikedAspect.LOCATION` reinforces (`:327-332, 382-383`).
- Sort tiebreak `rank_candidates_with_breakdown:906-925` (distance_key).
- Outreach: `ProgrammeOption.distance_km` in the planner brief (`sql_repository.py:2318-2327`)
  and `_programme_models` ordering by `distance_km` (`:3631`) — but note the policy
  `programme_suggestion` rung (`policy.py:122-126`) says "A nearby low-barrier programme is
  permitted" without ever reading a distance: **nearness is asserted by the copy, not checked**.

**What the real thing would change for the senior — and what it exposes.** The fixture figures
are internally inconsistent in ways only a real origin could resolve (Part 2, F-J10): the same
building (postal 730676) is 700 m for one class and 900 m for another; the rooftop garden at
730512 is 500 m and 650 m; Toa Payoh AAC (≈15 km from the Woodlands venues every other listing
implies) is listed at 3 400 m. Today `_too_far` for "within 1 km" would keep karaoke's Toa Payoh
session on a 3.4 km listing figure only because the origin is fictional. A routed figure would
(a) make "too far" mean the same thing across listings, (b) let `_friction` express "a bus each
way" honestly, (c) give the DISTANCE learner a bucket that is about _this person's_ trip, and
(d) let "barrier-free" become a filter axis (OneMap's routing API exposes a `barrierFree`-style
option) so `accessibility_tags` such as "step-free" / "lift access" stop being free text the
guardrail merely echoes (`agent/guardrails.py:251, 447`).

**Minimal origin data it requires.** One coarse origin per person — a 6-digit postal code or,
coarser still, an HDB block / planning-area centroid — stored once, consented, never a GPS trace.
Concretely: `PersonRow.home_area_postal_code: str | None` (or `home_area_centroid_lat/lon`),
plus `ActivityCandidateRow.location_latitude/longitude` actually populated (columns exist,
`db_models.py:309-310`). With both present a straight-line haversine is computable **offline
with no OneMap call at all**, and is already a better basis than `LISTING_STATIC`. ADR 0001
lines 389-390 anticipate exactly this: if `EXTERNAL_CONTEXT` ever carries a home postcode it
"must move into" the consented scopes. That is a consent-_gate_ consequence to report, not a
consent-design task.

**Provenance / freshness / failure handling needed.**

- New `DistanceBasis` members: `HAVERSINE_FROM_HOME_AREA` (offline, from stored centroids) and
  `ROUTED_WALK_FROM_HOME_AREA` / `ROUTED_TRANSIT_FROM_HOME_AREA` (OneMap). The docstring at
  `models.py:686-690` already reserves this.
- `distance_basis` must become a **stored column** (today it is inferred from nullness at
  `sql_repository.py:3678-3684`; the moment two bases coexist that inference is wrong).
- Per-candidate `distance_evidence_id`, `distance_computed_at`, `distance_expires_at` (routes
  do not change often; a 30-day TTL is fine; haversine never expires).
- Failure: fall back to haversine, then to `LISTING_STATIC`, then `UNKNOWN`, each labelled; the
  card suffix in `view-models.ts:1090` already keys off the basis.
- OneMap needs an API token (WAYFINDER:582 "OneMap needs a token"); routing calls must never
  run inside a write transaction (the same discipline `search_activities` docstring at
  `sql_repository.py:3903-3916` enforces for the planner).

**Privacy cost.** One coarse origin at rest. No continuous GPS, no per-query location. Routing
requests would send the origin postal code to OneMap; that is person-identifying to a
neighbourhood, which is why it must sit behind the consented scope rather than the always-on
`EXTERNAL_CONTEXT` one (ADR 0001:389-390).

**Fixture fallback.** Exists partially: `LISTING_STATIC` distances. Needed: authored venue
lat/lon for the 14 venues (real public coordinates of public buildings — not senior data) and a
fixture origin centroid per persona. A recorded `routes.json` fixture keyed by
`(origin_postal, venue_postal)` would let the offline demo show a routed basis without network.

**Verdict: ADOPT LATER — but ADOPT NOW the offline half.** Two steps: (1) _now_ — store
`distance_basis`, add venue lat/lon, add a coarse per-person origin, compute haversine offline,
and unify the three near thresholds (F-J1); this changes `_too_far`, `_friction` and the DISTANCE
learner with zero network. (2) _later_ — OneMap routing behind a token, as one more basis. The
routing call itself changes no decision that haversine does not already change; it only sharpens
the number. Rejecting it outright would leave the fixture's geometric contradictions in place.

---

### 1.2 Official weather — NEA / data.gov.sg (rain, 2-hour forecast); PSI / UV

**Rain: already adopted (`context.py`), off by default.** Decision branches: `policy.py:78`,
`activity_search.py:734-746`, `replanning.py:163-166`. Three defects to fix before enabling:

1. **Whole-island max** (`context.py:129, 145-152`): one shower in Changi excuses a quiet day
   in Woodlands and demotes every outdoor listing island-wide. Region-scoping needs the same
   coarse origin as 1.1 (the 2-hour forecast is already per-area — "Woodlands", "Admiralty" —
   so a planning-area name is enough; no coordinates needed). This is the one place the origin
   pays for itself twice.
2. **Simulated day vs wall clock** (WAYFINDER:2035-2041, still true at
   `sql_repository.py:1628-1629`): the provider is asked for `next_day` noon and answers with
   live conditions. `expires_at` (2 h, `context.py:203`) is compared to a simulated instant, so
   for any simulated day ≠ today the evidence is _always_ expired and is dropped — which is the
   correct outcome by accident. Freeze context per simulated day or refuse to fetch for a day
   that is not today.
3. **`air_quality` has no producer** (`models.py:117`; sole writer `sql_repository.py:1654`
   copies the default). WAYFINDER:2025 flagged it; still unfixed.

**PSI / UV.** Decision it would change: none today. `policy.py` has no air-quality gate;
`activity_search` has no factor; `replanning` none. Could it? A PSI ≥ 100 "unhealthy" day is a
legitimate reason to prefer indoor over outdoor for _anyone_ (it is a public advisory, not a
medical judgement about the person), so it could feed the same `context` factor as rain through
`activity_rain_bias` (`context.py:84-104` is explicitly "the single place a richer forecast
signal … would plug in"). But the product boundary forbids "interpreting … as a medical signal"
and a per-person PSI sensitivity would be exactly that. **Verdict: REJECT for now** — no branch
reads it, and the honest first step is to delete or label the dead `air_quality` field.
Revisit only as a second boolean into the _existing_ context factor, never as a gate.

**Provenance / freshness.** Present and good: source, observed_at, expires_at, confidence,
evidence_id (`context.py:49-63`). Freshness gate in `advance:1631-1647`. Holiday cache is
process-lifetime and never invalidated (`context.py:219`, WAYFINDER:2046-2050).

**Privacy.** None today. Region-scoping adds the coarse area (same cost as 1.1, shared).

**Fixture fallback.** The simulator events `rain_explains_decline`, `rain_clears_activity_low`,
`weather_turns` (`sql_repository.py:1439-1449`) are the fixture. There is **no recorded-replay
fixture** of the live payloads (docs/data-and-privacy.md line 6 explicitly allows "Cached public
context fixtures with provenance" — none exist). Needed before enabling: one recorded rainfall +
forecast JSON pair under `apps/api/tests/fixtures/` and a `ReplayContextProvider` so the
freshness gate and region scoping are testable offline.

**Verdict: ADOPT NOW (already in tree) with the three fixes; region-scope LATER with 1.1's
origin.**

---

### 1.3 Public holidays — MOM (official) vs `date.nager.at` (current)

**Decision it changes: none.** `policy.py` never reads `holiday` (verified; WAYFINDER:1048).
`activity_search` never reads it. It is explanatory copy only (`replanning`, planner brief
`_tool_context:2359`). Switching source therefore changes no decision; it changes only the
honesty of the label (WAYFINDER:334-336 and :2028 already record the `nager.at` problem).

**What it needs.** MOM publishes the list as a data.gov.sg dataset (CSV, annual). A once-a-year
fetch with `source="mom_public_holidays_via_datagovsg"`, or — better for the offline
invariant — a **committed fixture** of the year's dates with the dataset id and retrieval date as
provenance. That removes the runtime call entirely.

**Verdict: ADOPT NOW as a committed fixture (no network), and delete the nager.at call.** If a
later change makes holiday a ranking input (e.g. AAC closed on public holidays → `availability`),
that is a catalogue fact, not a context fact.

---

### 1.4 AAC directories (AIC / MOH AAC list) — programme _availability_

**Decision it would change.** `activity_search._full` (`:255-258`) and `_wrong_day` (`:195-207`)
already act on `availability` and `start_at`. `ActivitySource.AAC_FIXTURE` is the only real
source (`models.py:641-652`); `ONEPA`, `ACTIVESG`, `HEALTHY365_HANDOFF` are reserved and must
not be claimed (`IntegrationStatus.FUTURE_AUTHORISED`, `:655-658`). A real AAC directory feed
would replace `fixtures._PROGRAMMES` (`fixtures.py:390-853`) as the catalogue writer.

**What changes for the senior.** Real programmes, real times, and — crucially — real
`availability`. Today `FULL` is authored on one listing (tai-chi) and set by two simulator events
(`sql_repository.py:1601, 1618`).

**Provenance needed (this is the Part 2 gap).** Per listing: `metadata_source` (which directory,
which page), `last_verified_at`, `verified_by` (`directory_feed | centre_staff | fixture_author`),
and a completeness score. None exist (`J_validate.py` output: every provenance field `False`).
`retrieved_at` exists but is one stamp for the whole seed (`fixtures.py:870`).

**Failure handling.** A stale directory row must age into `availability=UNKNOWN`, not stay
`AVAILABLE` forever. `_refresh_stale_activities` (`sql_repository.py:562-585`) rolls sessions
forward _weekly forever_ — right for a fixture, wrong for a real feed (a cancelled programme
would be resurrected every week). It must be gated on `source == AAC_FIXTURE`.

**Privacy.** None (public directory).
**Fixture fallback.** Exists (`_PROGRAMMES`).
**Verdict: ADOPT LATER (needs authorised access); ADOPT NOW the provenance columns**, because
they are also what makes the fixture auditable (Part 2).

---

### 1.5 ActiveSG / onePA — programme catalogues with booking

**Decision it would change.** Same branches as 1.4 (`_full`, `_wrong_day`, `_inaccessible`
`:261-277`, plus `booking` copy). onePA in particular carries **price, capacity, vacancies and
registration**, which would turn the free-text `price` (`models.py:739`) and the orphan
`capacity` (`:737`, never compared to anything — grep shows no reader of `capacity` in
`activity_search.py` or `preferences.py`) into decision inputs (`vacancies == 0 → FULL`).

**Provenance / failure.** As 1.4, plus `source_url` populated (`models.py:740`, currently
`None` on every fixture, `fixtures.py:906`).
**Privacy.** Browsing is public. _Booking_ on the person's behalf is out of scope by invariant
("Nothing has been booked", `sql_repository.py:2273-2276`).
**Fixture.** Exists.
**Verdict: ADOPT LATER.** The enum members already exist; do not populate them until the feed is
real (WAYFINDER:581 — "fabricated provenance is the one dishonesty this project cannot survive").

---

### 1.6 Transport (LTA DataMall: bus arrivals, MRT status)

**Decision it would change: none.** `getting_there` (`models.py:757`) is display-only free text;
no filter or factor reads it. Live bus arrival is minute-scale information for a product that
decides once a day; MRT line disruption _could_ matter to `replanning`, but only once transit
routing (1.1 step 2) exists to know which line a trip uses.
**Verdict: REJECT.** WAYFINDER:313-314 reached the same conclusion; still correct.

---

### 1.7 Accessibility routing (barrier-free)

Folded into 1.1: it is OneMap's routing option plus a per-person "step-free needed" fact. The
substrate for the fact exists (`accessibility_tags`, `CandidateOption.accessibility_terms`,
guardrail `_missing_accessibility_terms`), but no _person-side_ accessibility need is stored
anywhere (no field on `PersonRow`, `PersonaProfile`, or `PersonFact` categories
`models.py:1297-1305`). Without it there is nothing to route _for_.
**Verdict: ADOPT LATER, after 1.1 step 1 and after a person-side need field exists** (which is a
stated-preference question, same shape as `state_preference`).

---

### 1.8 Programme availability (live capacity)

Covered by 1.4/1.5. One code-level finding that is independent of any feed:

**F-J-A. `weather_turns` fabricates "fully booked".** `advance` handles `weather_turns` by
setting the first upcoming outdoor plan's row to `availability=FULL`
(`sql_repository.py:1603-1621`), then `replanning._reason` (`replanning.py:123-138`) checks
`FULL` **before** `weather_turned`, so the senior's notice reads `"… is now fully booked."` when
the truth is "the forecast turned". `tests/test_replanning.py:144` pins the precedence for the
pure function, which is fine; the defect is the simulator mutating a catalogue fact
(availability) to represent a context fact (weather). Severity **P1** (a fabricated listing
fact reaches the senior surface; the audit trail records `replan_affected_activity_id` but not
the _reason_ it was flipped). Fix: `weather_turns` should not touch `availability`; `notices_for`
already handles `rainy and entry.day == today and OUTDOOR` on its own (`:163-166`). Test: run
`weather_turns` against a planned outdoor activity and assert the notice contains "forecast" and
the row's availability is unchanged.

---

### 1.9 Healthy 365 handoff

**Decision it would change: none in this codebase.** `HEALTHY365_HANDOFF` exists as a reserved
`ActivitySource` (`models.py:652`) and `docs/data-adapters.md` ("Healthy 365: future adapter
only") is explicit that it is a _sensing_ source, not an action target, and only after authorised
API access. A "handoff" (deep-linking a senior into the H365 app to join a challenge) would be a
new outreach candidate _class_, which touches `policy.py`'s action classes — out of scope by the
brief.
**Verdict: REJECT for this pass; keep the label honest** ("Healthy 365-compatible future
adapter", never "integrated").

---

### 1.10 Summary table

| Source                  | Branch it changes                                          | Verdict                                                                             |
| ----------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| OneMap routing          | `_too_far`, `_friction`, `_distance_bucket`, sort tiebreak | ADOPT LATER; **ADOPT NOW** stored basis + venue lat/lon + coarse origin + haversine |
| NEA rain / 2 h forecast | `policy.py:78`, `score_candidate` context, `notices_for`   | ADOPT NOW (in tree) after 3 fixes; region-scope LATER                               |
| PSI / UV                | none                                                       | REJECT; delete/label `air_quality`                                                  |
| Public holidays (MOM)   | none (explanatory)                                         | ADOPT NOW as committed fixture; drop nager.at                                       |
| AAC directory           | `_full`, `_wrong_day`, catalogue writer                    | ADOPT LATER; provenance columns NOW                                                 |
| ActiveSG / onePA        | as above + `capacity`/`price` become real                  | ADOPT LATER                                                                         |
| LTA transport           | none                                                       | REJECT                                                                              |
| Barrier-free routing    | `_too_far`/filter, needs person-side need                  | ADOPT LATER                                                                         |
| Live availability       | `_full`, replanning                                        | with 1.4/1.5; fix F-J-A NOW                                                         |
| Healthy 365 handoff     | none                                                       | REJECT this pass                                                                    |

---

## PART 2 — Catalogue metadata quality

### 2.0 Method

```
cd apps/api && LLM_ENABLED=false ADAPTER_MODE=fixture \
  uv run python .../scratchpad/audits/J_validate.py
```

Output (abridged; full run reproduces on demand):

```
programmes=14 candidates=29
price values: {'Free': 9 slugs, None: ['evening-walk','brisk-walk','garden-stretch'], '$2': ['karaoke'], '$3': ['pool-exercise']}
category vocab: ['Drop-in, self-guided', 'Group class', 'Self-guided', 'Social group']
accessibility vocab (28 distinct): [... 'seated option for every movement', 'seated throughout', 'seating', 'seating throughout', 'shade', 'shaded area', 'step-free', 'step-free entrance' ...]
distance buckets: chair-mobility 700 near, sheltered-walk 1200 near, ... tai-chi 2100 far, karaoke 3400 far, brisk-walk 4600 far, pool-exercise 2800 far, reading-corner 1800 near
Programme aac-chair-mobility: next_session=2026-08-24T09:30:00+00:00 local_hour=17
Programme aac-sheltered-walk: next_session=2026-08-25T08:00:00+00:00 local_hour=16
synthetic history last day: 2026-08-18 first: 2026-07-21
retrieved_at stamp: 2026-09-14T06:00:00+00:00 local hour 14
field 'metadata_source' on ActivityCandidate: False   (same for last_verified_at, completeness, provenance, verified_by, origin, distance_origin)
=== 30 findings ===
```

Checks that **passed** (no hits): social_shape solo with a group format; negative/zero distance;
session before `retrieved_at`; session before today at seed; FULL without capacity; FULL with
drop-in booking; `indoor_outdoor=UNKNOWN` with contradicting text (no fixture row is UNKNOWN);
title "Sheltered" vs field; title time-of-day vs session bucket ("Sheltered **Morning** Walk"
08:00, "**Evening** Tea & Chat" 18:30, "Gentle **Evening** Stretch" 19:00, "**Afternoon** Craft
Circle" 14:00 all consistent); "Gentle"/"Brisk"/"Independent"/"Quiet"/"Seated" vs fields;
duplicate titles; identical `(postal_code, start_at)` slots; money in `what_to_bring` vs `price`.

One **false positive** to discard: `[brisk-walk] text mentions shelter … but outdoor` — the hit
is `good_to_know` "the sheltered morning walk is gentler", a cross-reference, not a claim.

### 2.1 Controlled vs free-text fields (row model `db_models.py:278-333`)

| Field                                                                       | Kind                                   | Note                                                                                                                                                                                              |
| --------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `source`, `integration_status`, `indoor_outdoor`, `availability`, `booking` | enum stored as string, **no DB CHECK** | reader casts with `Enum(row.x)` (`sql_repository.py:3658-3673`) so an off-vocabulary row raises at read time and takes the _whole listing_ down (the exact failure WAYFINDER:2243-2251 describes) |
| `intensity`, `social_shape`                                                 | enum-or-null                           | ok                                                                                                                                                                                                |
| `category`                                                                  | **free text**                          | 4 values, two of which mean the same thing (F-J4)                                                                                                                                                 |
| `accessibility_tags_json`                                                   | **free text list**                     | 28 distinct strings for ~12 concepts (F-J5)                                                                                                                                                       |
| `language_tags_json`                                                        | free text list                         | 5 values, consistent; parser vocabulary at `intent.py:84-92` includes `Cantonese`, absent from catalogue — harmless                                                                               |
| `price`                                                                     | **free text**                          | "Free" / "$2" / "$3" / None (F-J6)                                                                                                                                                                |
| `provider`                                                                  | free text                              | conflated with `venue` in 8 of 14 (F-J7)                                                                                                                                                          |
| `capacity`                                                                  | int-or-null                            | **never read** by any filter/factor; no `enrolled`/`vacancies`                                                                                                                                    |
| `distance_m`                                                                | int                                    | no origin; basis inferred, not stored (F-J2)                                                                                                                                                      |
| `retrieved_at`                                                              | datetime                               | one stamp for the whole seed, 14:00 SGT (`fixtures.py:870`)                                                                                                                                       |
| `metadata_source`, `last_verified_at`, `verified_by`, `completeness`        | **absent**                             |                                                                                                                                                                                                   |

### 2.2 Findings

**F-J1 — Three definitions of "near" and a dead constant that claims to unify them. P1.**
Evidence: table in 1.0. `activity_search.py:95-98` defines `_NEAR_THRESHOLD_M = 1000` with a
comment "Matches the near/too far default in intent.py", and nothing reads it; the learner
buckets at 2 000 m (`preferences.py:102`), friction at 500/5 000 (`activity_search.py:136-137`).
Root cause: three modules each grew their own threshold. Consequence: `TOO_FAR` on
sheltered-walk (1 200 m) or evening-walk (1 600 m) records `DISTANCE=near` negative
(`preferences.py:179-180`), and `_declined_value` fabricates `"far"` when distance is `None`.
Proposed design: a single `distance.py` (or constants in `models.py`) exporting
`NEAR_M = 1000`, `FAR_M = 2000`, `FRICTION_FREE_M`, `FRICTION_MAX_M`, and a
`distance_band(distance_m) -> Literal["walkable","near","far"] | None` used by intent, filter,
friction and learner; the learner records the band of the _declined_ listing **and**
`max_distance_m` of the intent when present, and on `None` records nothing (mirror the TIMING
rule at `preferences.py:183-186`). Files: `activity_search.py`, `preferences.py`, `intent.py`,
`tests/test_preferences.py`, `tests/test_activity_search.py`. Effort S. Test: decline
`TOO_FAR` at 1 200 m must not produce a negative "near"; `_NEAR_THRESHOLD_M` deleted or used.

**F-J2 — `distance_basis` is inferred from nullness, not stored; venue lat/lon columns exist
but are never populated. P1.**
Evidence: `db_models.py:278-333` has no `distance_basis`; `sql_repository.py:3678-3684`
infers `LISTING_STATIC` for any non-null distance; `location_latitude/longitude` columns
(`:309-310`) are `None` for every fixture (`fixtures.py:895-899`). The moment any second basis
exists the reader lies. Design: add `distance_basis` (String(40), server_default
`'listing_static'`), `distance_computed_at`, `distance_evidence_id` to `ActivityCandidateRow` +
Alembic + Supabase mirror; populate venue lat/lon for the 14 fixture venues; add
`DistanceBasis.HAVERSINE_FROM_HOME_AREA`. Effort M (schema). Test: a row written with basis
`haversine…` reads back as that basis, and a legacy NULL reads `listing_static`.

**F-J3 — Fixture geometry is self-contradictory (only a real origin could make it checkable). P2.**
Evidence (script): postal 730676 → 700 m (chair-mobility) vs 900 m (seated-strength), same
building `676 Woodlands Drive 71`; 730512 → 500 m (garden-stretch) vs 650 m (gardening), same
rooftop; 738344 → 1 600 m vs 2 100 m (park entrance vs lawn, plausible but unlabelled); karaoke
at `Blk 177 Toa Payoh Central` listed at **3 400 m** while every other venue implies a
Woodlands/Admiralty origin (~15 km away). Root cause: `distance_m` was authored per programme
with no origin. Fix now: make same-postal-code distances equal (validation rule V4 below) and
move karaoke to ≥ 12 000 m or relocate it; fix properly with F-J2. Effort S.

**F-J4 — `category` is free text and encodes _format_, and two spellings mean one thing. P1.**
Evidence: vocab `['Drop-in, self-guided', 'Group class', 'Self-guided', 'Social group']`
(`fixtures.py:770` vs `:660`). `CATEGORY` preference matches by string equality
(`preferences.py:243`), so a `NOT_FOR_ME` on the reading corner never touches seated-strength and
vice-versa; and "Drop-in" duplicates `booking=DROP_IN` (`:838-839`). This is also the mechanism of
the lead's "walk decline penalises tai chi" flaw: both are `"Group class"`. Design: two fields —
`format: ActivityFormat` enum (`GROUP_CLASS | SOCIAL_GROUP | SELF_GUIDED | DROP_IN_SPACE`) and
`activity_kind: ActivityKind` enum (`WALK | TAI_CHI | STRETCH | STRENGTH | WATER | GARDEN |
CRAFT | MUSIC | CONVERSATION | READING`), with `CATEGORY` preference learning on `activity_kind`
and `_diversify` keying on it. Files: `models.py` (contract change → `pnpm client:generate`),
`db_models.py`, migration, `fixtures.py`, `preferences.py`, `activity_search.py:779-780`,
`evaluation/ranking/dataset.py`. Effort M. Test: decline a walk `NOT_FOR_ME`; tai-chi's
`dimension_score` unchanged.

**F-J5 — `accessibility_tags` is 28 free strings for ~12 concepts. P2.**
Evidence: `'seated throughout' / 'seated option for every movement' / 'seating' / 'seating
throughout'`, `'step-free' / 'step-free entrance'`, `'shade' / 'shaded area'`, `'lift access' /
'lift access to roof'`, `'rest benches' / 'rest benches every 100m'`, `'paved route' / 'paved
path throughout'`. Nothing filters on them; the guardrail checks only the literal `"seated"`
(`sql_repository.py:2248`). Design: `accessibility_features: list[AccessibilityFeature]` enum
(`SEATED, STEP_FREE, LIFT, ACCESSIBLE_TOILET, HEARING_LOOP, SHADE, REST_BENCHES, QUIET,
LARGE_PRINT, POOL_HOIST, CHANGING_ASSISTANCE`) beside the free `accessibility_notes` for display;
this is the axis 1.7 needs. Effort M. Test: every fixture tag maps to exactly one feature.

**F-J6 — `price` mixes "Free", "$2", "$3" and `None` where `None` is not "unknown". P2.**
Evidence: `evening-walk`, `brisk-walk`, `garden-stretch` have `price=None` while their copy is
"Nothing to book"/volunteer-led and siblings say "Free" (`fixtures.py:565,750,780`). `None`
renders "Not listed" (`models.py:718-721` rule), so three genuinely free activities read as
price-unknown. Design: `price_cents: int | None` + `price_note: str | None`, 0 = free; the
validation rule V7 rejects `price_note` containing `$` when `price_cents is None`. Effort S.

**F-J7 — `provider == venue` for 8 of 14; series key is `(provider, title)`. P2.**
Evidence: script output; `_series_key` (`activity_search.py:779-780`) and `_dedupe_series`.
Two providers at the same rooftop (`Woodlands Green Fingers` vs `Block 512 rooftop garden`). It
works today because titles are unique, but a real feed with "Tai Chi" from two centres would
dedupe wrongly on title alone or fail to on provider. Design: `programme_id` on the candidate
(F-J12) becomes the series key. Effort S once F-J12 exists.

**F-J8 — The undated listing survives every date/time filter. P2.**
Evidence: `activity-reading-corner` (`start_at=None`, `fixtures.py:850`) passes
`on_date=today, time_window=EVENING` (script: `kept=True`); `_wrong_day:196-197` and
`_wrong_time_window:214` return `None` on `None`. Correct by the "UNKNOWN never excludes" rule,
but it means an open-all-day space appears in _every_ query including "tomorrow evening", and it
sits at `float("inf")` only on exact score ties. Design: an `opening_hours` field (or
`always_open: bool`) so the reason line can say "open all day" (currently the filler line) and
the time filter can _positively_ match. Effort S. Test: "tomorrow evening" keeps the reading
corner with an "open all day" intent reason, not a catalogue filler.

**F-J9 — `gardening` is OUTDOOR with an indoor rain fallback; rain logic treats it as cancelled. P2.**
Evidence: `fixtures.py:646-648` "Moves indoors to the void deck if it rains";
`indoor_outdoor=OUTDOOR` (`:632`); `score_candidate:741-743` gives −0.5 in rain,
`weather_turns:1613-1619` flips it FULL, `replanning:163-166` notices it. Design: add
`IndoorOutdoor.OUTDOOR_WITH_COVER_FALLBACK` (or `rain_plan: RainPlan = CANCELLED | MOVES_INDOORS
| RUNS_ANYWAY | UNKNOWN`); `sheltered-walk` "Runs in light rain" and `evening-walk` "Cancelled in
heavy rain" would populate it too. Effort S. Test: rain does not demote a `MOVES_INDOORS` listing.

**F-J10 — `pool-exercise` claims SHELTERED with no evidence in the listing. P3.**
Evidence: `fixtures.py:790` `SHELTERED`; no text says covered. Real Woodlands Swimming Complex
pools are open-air. Either add "under a roof" to `good_to_know` or set UNKNOWN. Effort XS.

**F-J11 — Outreach `Programme` twins disagree with the catalogue on time zone and venue. P1.**
Evidence: `synthetic_programmes` (`fixtures.py:309-329`) authors `09:30 UTC` = **17:30 SGT** and
`08:00 UTC` = 16:00 SGT, while the catalogue twins run 09:30 / 08:00 _local_ (`:423`, `:463`);
venue `"Kampung Admiralty AAC"` vs `"Kampung Admiralty Active Ageing Centre"`. The programme →
candidate bridge (`sql_repository.py:2773-2789`) then reports `start_at` 17:30 local and
`retrieved_at = next_session`. Also: `ProgrammeRow.next_session` is seeded once
(`:545-559`, skip-if-exists) at 2026-08-24, `valid_until = +7 d`, and is **never rolled
forward** like `_refresh_stale_activities` does for the catalogue; with a run starting
2026-08-18 (script: history last day) the programme freshness gate (`:1394-1398`) downgrades every
`programme_suggestion` to `NO_ACTION` from 2026-09-01 — scenario 14 (18 days) reaches 09-05.
That is the _intended_ stale-programme invariant firing on a fixture that was never re-anchored,
so the outreach loop's programme beat silently disappears late in long runs. Design: retire
`Programme`/`ProgrammeRow` as a second catalogue and make outreach's `programme_suggestion` read
`ActivityCandidate` rows (`_programme_models` → catalogue query with `source`/`format` filter),
keeping `/v1/programmes` as a projection for the e2e suite. Effort M–L (touches outreach). Test:
`synthetic_programmes()[i].next_session` local hour equals the catalogue twin's; an 18-day run
still yields at least one `programme_suggestion` after day 14.

**F-J12 — Programme vs Session split: supported _implicitly_ by the row model; not modelled.**
Evidence: `_Programme` + `_Session` exist only in `fixtures.py:332-387`; each occurrence becomes
its own `ActivityCandidateRow` with id `activity-{slug}-{n}` (`:875-885`) and the programme
identity survives only as `(provider, title)` (`_series_key`). `WeekPlanEntryRow.activity_id`
(`db_models.py:636+`) and `ActivityOfferResponseRow` key on the occurrence id, so engagement
("not for me" cooldown, `activity_search.py:606-657`) is per _occurrence_ — a decline of
Tuesday's chair mobility does not hold back Thursday's, except via `_dedupe_series`. What it
would take (Effort M): (1) `ProgrammeRow`-like `activity_programmes` table (`programme_id, title,
provider, venue, address, postal, lat/lon, format, activity_kind, description, accessibility,
languages, booking, contact, price, metadata_source, last_verified_at, verified_by`); (2)
`activity_candidates` keeps per-occurrence fields only (`start_at, duration_minutes, capacity,
vacancies, availability, retrieved_at`) plus `programme_id` FK; (3) `ActivityCandidate` gains
`programme_id: str` (contract change, regenerate client); (4) `_series_key` → `programme_id`;
engagement/cooldown keyed on `programme_id` with the occurrence id kept for plans; (5)
`_refresh_stale_activities` rolls occurrences only for `source == AAC_FIXTURE`. Ranking a
specific occurrence stays exactly as today — the split changes _identity_, not scoring. The
current row model does **not** block this: no reader depends on `activity_id` shape except the
fixture generator and `_series_key`.

**F-J13 — No provenance beyond `retrieved_at`; `source_url` is `None` everywhere. P1.**
Minimal fields to add to `ActivityCandidate` and the row (all nullable, honest-unknown):
`metadata_source: str | None` (e.g. `"aac_fixture:fixtures.py"`, later a directory id),
`last_verified_at: datetime | None`, `verified_by: Literal["fixture_author","directory_feed",
"centre_staff"] | None`, `completeness: float` (computed, not stored — fraction of decision-relevant
fields populated: `start_at, indoor_outdoor, intensity, social_shape, language_tags, distance_m,
availability, booking`), and `distance_basis` stored (F-J2). Effort M (schema + contract).

### 2.3 Proposed validation rules — pure, testable

Signature: `validate_listing(candidate: ActivityCandidate) -> list[ListingIssue]` and
`validate_catalogue(candidates: list[ActivityCandidate]) -> list[ListingIssue]` where
`ListingIssue(activity_id, rule, severity: Literal["error","warning"], detail)`. Module
`silverloop/catalogue_validation.py`; run in `_seed_activity_candidates` (log warnings, refuse
errors) and in a test over `synthetic_activity_candidates(today)` that asserts zero errors.

Per-listing (errors unless noted):

- V1 `distance_positive`: `distance_m is None or distance_m > 0`.
- V2 `basis_matches_distance`: `(distance_m is None) == (distance_basis is UNKNOWN)`.
- V3 `session_after_retrieval`: `start_at is None or start_at >= retrieved_at`.
- V4 `full_needs_capacity` (warning): `availability is FULL → capacity is not None`; and
  `booking is DROP_IN → availability is not FULL`.
- V5 `format_vs_social`: category/format `SELF_GUIDED` ⇒ `social_shape is SOLO`; `GROUP_CLASS |
SOCIAL_GROUP` ⇒ `SOCIAL`.
- V6 `title_tokens_vs_fields`: "morning|afternoon|evening" in title ⇒ `_timing_bucket(start_at)`
  equals it; "sheltered" ⇒ SHELTERED; "park|garden|lawn" ⇒ OUTDOOR; "gentle" ⇒ LIGHT; "brisk" ⇒
  MODERATE; "independent|quiet corner" ⇒ SOLO; "group|circle" ⇒ SOCIAL.
- V7 `text_vs_environment` (warning): "covered|sheltered|under cover" in
  description/accessibility (not `good_to_know` cross-references) ⇒ SHELTERED or INDOOR;
  "moves indoors" ⇒ rain-plan field set once F-J9 exists.
- V8 `price_shape`: `price` matches `^(Free|\$\d+(\.\d{2})?)$` or is None; `$` in
  `what_to_bring` ⇒ `price` not None.
- V9 `languages_or_unknown` (warning): empty `language_tags` allowed but counted in
  `completeness`.
- V10 `intensity_present` (warning) — same.
- V11 `provider_not_venue` (warning): `provider != location.name` unless format is
  `DROP_IN_SPACE`.
- V12 `postal_code_shape`: 6 digits.
- V13 `contact_present`: `contact_phone or contact_note`.

Catalogue-level:

- C1 `same_postal_same_distance`: rows sharing `location.postal_code` share `distance_m` (±0).
- C2 `no_duplicate_series`: `(provider, title)` (later `programme_id`) maps to one
  `indoor_outdoor / intensity / social_shape / format` tuple.
- C3 `no_slot_collision`: `(postal_code, start_at)` unique unless different rooms in `address`.
- C4 `series_timing_consistency` (warning): one programme spanning two timing buckets
  (gardening: Tue 09:00 + Fri 16:30) — legal, but the TIMING learner will treat a "bad timing"
  on one as evidence about the bucket, not the programme.
- C5 `geography_plausible` (warning): `distance_m` monotone-ish with straight-line distance from
  the fixture origin once venue lat/lon exist (would have caught karaoke).

Test that pins it: `tests/test_catalogue_validation.py::test_fixture_catalogue_has_no_errors`
plus one negative case per rule.

### 2.4 Data-honesty observations that are _not_ defects

- The two empty `language_tags`, two `intensity=None`, one no-phone, one no-session listing are
  deliberate and documented (`fixtures.py:383-388`); they render "Not listed". Keep.
- `retrieved_at` at 06:00 UTC (14:00 SGT) is fine, but it is one stamp per seed, not per row —
  it will be wrong the moment a real feed lands (F-J13).

---

## What NOT to build

1. **A live OneMap call before the offline half exists.** Store the basis, add venue
   coordinates and a coarse origin, compute haversine. Routing is a sharper number for the same
   branches; it is not a new decision.
2. **Any per-person weather/PSI sensitivity** (WAYFINDER §16). Needs per-person location,
   time-of-day metrics and stored context history; none exist; and per-person PSI sensitivity
   crosses into medical interpretation.
3. **A ContextRegistry / aggregator of 11 sources.** Two sources exist and neither is fully
   honest yet (whole-island max, wall-clock vs simulated day, nager.at). Fix those first.
4. **LTA DataMall.** No branch reads transport; minute-scale data for a once-a-day decision.
5. **Populating `ONEPA` / `ACTIVESG` / `HEALTHY365_HANDOFF` sources with fixture rows** to
   "show the shape". The enum already shows the shape; a row claiming a source it did not come
   from is the one dishonesty the project cannot survive.
6. **Booking on the senior's behalf** via onePA/ActiveSG. Out of scope by invariant.
7. **A holiday _gate_ in `policy.py`.** Holiday stays explanatory (WAYFINDER:1048); switching to
   an official/committed source is a labelling fix, not a policy change.
8. **Keeping `Programme`/`ProgrammeRow` as a second, hand-synced catalogue.** It already
   disagrees with the real catalogue on time zone and venue and silently expires mid-run
   (F-J11); fold it into `ActivityCandidate` rather than adding provenance to both.
9. **Free-text NLP over `description` to infer `indoor_outdoor` / `intensity` at read time.**
   That is exactly the "plausible guess" the schema forbids; put the fact in a controlled
   field or leave it UNKNOWN.
