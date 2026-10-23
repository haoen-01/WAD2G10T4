# Audit C — Intent / natural language / ontology

Worktree: `/Users/ianpong/Projects/ismoggers-v2` @ `010aa96`. Read-only. All commands run with
`LLM_ENABLED=false ADAPTER_MODE=fixture` from `apps/api`. Probe scripts:
`scratchpad/audits/c_parse_probe.py`, `c_ontology_demo.py`, `c_ontology_demo3.py`.

## 0. Parser probe — 35 phrasings through `parse_intent`

Command: `uv run python .../c_parse_probe.py` (today = Sunday 2026-09-06). Output verbatim:

| input                                        | parsed                        | unparsed_terms              | note                                               |
| -------------------------------------------- | ----------------------------- | --------------------------- | -------------------------------------------------- |
| a morning sheltered walk                     | time=morning, env=sheltered   | `['walk']`                  | content dropped                                    |
| something social nearby tomorrow morning     | date, morning, 1000 m, social | `[]`                        | good                                               |
| I want to do tai chi                         | —                             | `['tai']`                   | "chi" silently dropped (len<=2)                    |
| craft                                        | —                             | `['craft']`                 | honest, but nothing found                          |
| cooking class in Mandarin                    | lang=Mandarin                 | `['cooking','class']`       |                                                    |
| **nothing outdoors today**                   | date, **env=outdoor**         | `[]`                        | **negation inverted; hard filter**                 |
| somewhere quiet by myself                    | social=solo                   | `[]`                        | good                                               |
| not too far, under 1 km                      | 1000 m                        | `[]`                        | good                                               |
| **sit down exercise**                        | **intensity=moderate**        | `['down']`                  | "exercise" ∈ `_MODERATE`; "sit" ∉ `_LIGHT`         |
| gardening                                    | env=outdoor                   | `[]`                        | "garden" prefix → environment, content lost        |
| learn something                              | —                             | `['learn']`                 |                                                    |
| karaoke                                      | —                             | `['karaoke']`               |                                                    |
| walk                                         | —                             | `['walk']`                  | confirmed lead flaw                                |
| I want to go for a walk this evening         | time=evening                  | `['walk']`                  |                                                    |
| can go swimming or not                       | —                             | `['swimming']`              |                                                    |
| anything got tai chi in the park             | env=outdoor                   | `['got','tai']`             |                                                    |
| I dont want group class, want to be alone    | social=solo                   | `['class']`                 | correct only because SOLO is tested before SOCIAL  |
| something with my friends after lunch        | social                        | `['lunch']`                 | "after lunch" not a window                         |
| singing, in Hokkien                          | lang=Hokkien                  | `['singing']`               |                                                    |
| reading corner                               | —                             | `['reading','corner']`      |                                                    |
| no walking, my knee pain                     | —                             | `['walking','knee','pain']` |                                                    |
| don't want anything tiring                   | —                             | `["don't",'tiring']`        | "dont" is a stopword, "don't" is not               |
| chair exercise near my block                 | 1000 m, light                 | `['block']`                 |                                                    |
| want to jalan jalan tomorrow                 | date                          | `['jalan']`                 |                                                    |
| 早上 想去 散步                               | time=morning                  | `[]`                        | **散步 (walk) silently dropped** — `_WORD=[a-z']+` |
| 晚上 唱歌                                    | time=evening                  | `[]`                        | **唱歌 (sing) silently dropped**                   |
| something in Chinese this afternoon, not far | afternoon, Mandarin           | `[]`                        | "not far" not a distance (only "not too far")      |
| mahjong with kakis                           | —                             | `['mahjong','kakis']`       |                                                    |
| exercise but indoor because raining          | indoor, **moderate**          | `['because']`               |                                                    |
| volunteering                                 | —                             | `['volunteering']`          |                                                    |
| art and craft on Saturday                    | date                          | `['art','craft']`           |                                                    |
| stretching class 3km                         | 3000 m                        | `['stretching','class']`    |                                                    |
| I am free this evening, nothing much         | evening                       | `['free','much']`           |                                                    |
| **not outdoor**                              | **env=outdoor**               | `[]`                        | negation inverted                                  |
| no need to walk far                          | —                             | `['need','walk']`           |                                                    |

Summary: of 35 phrasings, 22 named an activity kind (walk, tai chi, craft, cooking, karaoke,
gardening, swimming, singing, reading, mahjong, volunteering, stretching, exercise, jalan, 散步,
唱歌). Zero of those reached the intent; 20 were handed back as "I did not understand", 2 (CJK)
vanished silently, and 3 were _misread as a different axis_ (gardening→outdoor, exercise→moderate
×2). Three negated sentences were inverted.

---

## Findings

### C1. Negation is not parsed, and the inverted reading becomes a HARD filter — P0

**Evidence.** `intent.py:120-131` `_contains` finds the first needle anywhere in the sentence with
no look-behind. `intent.py:250-256` sets `environment` from the first needle found. No negation
logic exists anywhere in the module (`grep -i negat intent.py` → only comments). Live run
(`c_ontology_demo.py`):

```
== search 'nothing outdoors today': parsed_by=keyword understood=['Tuesday 18 August', 'Outdoors']
  #1 Independent Garden Stretch  cat='Self-guided'
  filtered_out: ['wrong_day', 'wrong_environment'] 28
```

`activity_search.py:221-233` `_wrong_environment` is in `_RULES` (`:278-286`), so the misread is a
hard exclusion: the person asked for _nothing outdoors_ and was shown _only_ the one outdoor
option. The confirmation screen (`ask-silverloop.tsx:299-316`) shows "Outdoors" with no
`unparsed_terms`, so the honesty valve reports full understanding. The same holds for
`_SOCIAL`/`_SOLO`, `_INDOOR`, `_LIGHT`/`_MODERATE` and `_NEARBY` ("not far" → nothing; "no
walking" → nothing, by luck).

**Root cause.** Bag-of-needles matching with no scope; the module docstring's rule 1 ("an
unrecognised term narrows nothing") is satisfied, but a _recognised_ term under negation narrows
the wrong way. The unit suite (`test_intent.py`) contains no negated sentence.

**Severity.** P0 — a stated request is hard-filtered to its opposite, with a confirmation screen
that claims it was understood.

**Substrate.** `_contains` already returns the matched needle and its position is recoverable via
`re.search(...).start()`. `_STOPWORDS` already lists `not`.

**Design.**

- `_NEGATORS = ("not", "no", "nothing", "nowhere", "never", "don't", "dont", "without", "cannot",
"can't", "rather not", "不要", "不想", "别")`. In `_contains`, after a match at index `i`, look
  back over the ≤3 preceding word tokens; if a negator is present, return
  `Match(needle, negated=True)`.
- Negated matches do **not** set the positive value. For binary axes they may set the complement
  only when the complement is a single member: `not outdoors` → `environment=INDOOR`?
  No — SHELTERED also satisfies "not outdoors". Safer: add `excluded_environments: list[...]`
  / `excluded_activity_types` (see C3) rather than inventing a positive. For `social`/`intensity`
  the complement is unambiguous (`not alone` → SOCIAL, `nothing tiring` → LIGHT).
- A negated needle is still "consumed" so it never lands in `unparsed_terms`, and
  `describe_intent` renders it ("Not outdoors").
- Same rule in the LLM tool description: "`nothing outdoors` must not set `environment=outdoor`."

**Files.** `intent.py`, `models.py` (ActivityIntent: `excluded_environments` or reuse C3's
`excluded_activity_types`), `activity_search.py` (`_wrong_environment` honours exclusions),
`agent/intent_planner.py` (schema + prompt), `test_intent.py`.
**Effort.** S for social/intensity complements + exclusion list; M with UI copy.
**Test.** `parse("nothing outdoors today").environment is not OUTDOOR`; `parse("not alone") is
SOCIAL`; `parse("don't want anything tiring").intensity is LIGHT`; property test: for every needle
`n` in every table, `parse(f"not {n}")` never yields the value `n` maps to.

### C2. Activity content is the axis the person names most and the only one the intent cannot carry — P1 (the ontology gap)

**Evidence.** `models.py:612-638` `ActivityIntent` has no activity-kind field (by design, `:24`
"has no field that could name an activity" — that was written to stop the LLM _recommending_, but
it also stops it _translating_ "tai chi"). Probe: 22/35 phrasings named a kind; none reached the
search. The fixture catalogue is 14 programmes with `category ∈ {"Group class"×9, "Social
group"×3, "Self-guided"×2, "Drop-in, self-guided"×1}` (`fixtures.py:391-838`), i.e. **format, not
content**. Content lives only in `title` and `description` free text. The web starter chips
(`view-models.ts:961-966`) are distance/social/environment/intensity — no content chip either.
So a senior who types "walk" gets "I did not understand 'walk'", and a senior who taps chips can
never ask for a walk at all.

**Root cause.** The schema was designed around _constraints on a search_ (where/when/how far/how
hard) and never around _what_. Category was added to the catalogue as a rendering badge
(`activity-card.tsx:130`) and then borrowed by the learner (C4) and the diversity pass.

**Severity.** P1.

**Substrate.** `ActivityCandidate.category` column exists (`db_models.py:304`, Supabase
`202609060007_activity_catalogue.sql:26`); `_RECOGNISED`/`_is_recognised` machinery for keeping
understood words out of `unparsed_terms`; `describe_intent` line builder; the intent-planner tool
schema with `strict` enforcement (`intent_planner.py:52-104`); `_INTENT_AXES` (`activity_search.py:578-589`).

**Design.** See §Taxonomy below for the enums and alias table. Contract change:

```python
class ActivityIntent(BaseModel):
    ...
    activity_types: list[ActivityType] = Field(default_factory=list, max_length=5)
    excluded_activity_types: list[ActivityType] = Field(default_factory=list, max_length=5)
```

_Hard or soft?_ **Soft fit by default, hard only when it would still leave results.** Reasoning:
the catalogue is tiny and the honest failure mode is "show more, never silently exclude"
(`intent.py:28-30`). Concretely:

- `filter_candidates`: `activity_types` is _not_ a `_RULES` entry. `excluded_activity_types`
  **is** a rule (`"excluded_kind"`), because "no walking, my knee" is a statement about the
  person's body and must be honoured deterministically.
- `score_candidate`: add `activity_types` to `_INTENT_AXES` so a match counts in the `intent`
  factor (weight 7 — already dominant) with the reason line "A walk, as you asked." A non-match
  scores 0 on that axis; with one constrained axis and no match, `intent_fit=0`, so anything that
  _is_ a walk goes top and everything else stays visible beneath.
- If ≥1 candidate matches `activity_types`, `search_activities` may additionally pass
  `filtered_out` entries with rule `"other_kind"` for the non-matches _only when the caller asked
  for a strict reading_ (a "Only walks" refinement chip). Never on the first search.
- `nothing_matched` stays first-class: "Nothing listed is a cooking class this week" with the
  rest shown under "Other things nearby".

_Unknown stays unknown._ A word not in the alias table stays in `unparsed_terms` exactly as now.
`ActivityType.OTHER` is never assigned by the parser — it exists only for catalogue rows whose
normalisation yields nothing, and OTHER never matches an intent. This keeps the "never guess"
rule: "mahjong" remains unparsed until someone adds the alias.

_Clarification without interrogation._ Reuse the existing confirm step: `understood` gains one
line per type ("Walking"). For an unparsed content word that fuzzy-matches an alias
(Levenshtein ≤2 or prefix, e.g. "taichi", "gardenning"), return a _new_ optional field
`suggested_types: list[{term, activity_type, label}]` and render each as a single chip on the
confirm card: "Did you mean _Tai chi_?" [Yes] — one tap, skippable, and the default (no tap) is
the current behaviour. No multi-question dialogue. The LLM parser may fill `activity_types` but
never `suggested_types` (server-side only).

_LLM constraint._ `_tool_definition` gets `"activity_types": {"type":"array","items":{"type":
"string","enum":[m.value for m in ActivityType if m is not ActivityType.OTHER]}, "maxItems":5}`
built **from the enum at import time**, not typed by hand (C8). System prompt adds: "Name only
kinds the person literally asked for; a kind you infer from a mood ('something nice') is a guess."
Pydantic validation (`intent_planner.py:189-198`) already rejects an out-of-enum value → fallback.

**Files.** `models.py` (+2 enums, +2 fields; `pnpm client:generate`), `intent.py` (alias table
import, `activity_types` parse, `describe_intent` lines), `agent/intent_planner.py`,
`activity_search.py` (`_INTENT_AXES`, `_intent_reasons`, `excluded_kind` rule), `fixtures.py`
(per-programme `activity_type`/`families`/`format`), `db_models.py` + Alembic + Supabase mirror
(3 nullable columns or one JSON), `view-models.ts` (content starter chips: "A walk", "Tai chi",
"Crafts", "Gardening", "Singing"), `ask-silverloop.tsx` (suggested-type chip),
`docs/api.md`.
**Effort.** M (L with UI chips + migration).
**Test.** `parse("a morning sheltered walk").activity_types == [WALKING]` and `unparsed_terms ==
[]`; `parse("mahjong").activity_types == []` and `"mahjong" in unparsed_terms`; API test posting
`{"text": "walk"}` and asserting the top result's `activity_type == "walking"` and that
non-walks are still in `results` (soft); `{"text": "no walking"}` asserts every walk is in
`filtered_out` with rule `excluded_kind`.

### C3. `category` is format, so one "not for me" on a walk demotes 9 of 14 programmes — P1 (confirms lead's flaw, with numbers)

**Evidence.** `preferences.py:65` `NOT_FOR_ME → CATEGORY`; `:193-198` `_declined_value(CATEGORY)
= candidate.category`; `:241-242` read side identical. Live run (`c_ontology_demo3.py`) after
declining _Sheltered Morning Walk_ once:

```
prefs: [('category', 'Group class', -0.333, 'decline_reason')]
#13 Community Gardening        cat='Group class'  pref=-0.666
#15 Chair Mobility & Balance   cat='Group class'  pref=-0.666
#18 Gentle Evening Stretch     cat='Group class'  pref=-0.666
#24 Warm Water Exercise        cat='Group class'  pref=-0.666
#26 Brisk Neighbourhood Walk   cat='Group class'  pref=-0.666
#11 Karaoke & Social Hour      cat='Social group' pref=+0.000   (3.4 km away, now ABOVE gardening at 650 m)
```

Tai Chi is `availability=FULL` in the fixture (`fixtures.py:568`) so it is filtered before
scoring; every other Group class shows the −0.666 (weight 2.0 × −0.333). The senior's Privacy
screen then says "You lean away from **group class activities**" (`view-models.ts:1254`
`${value.toLowerCase()} activities`) — a sentence the person never said and would not recognise
(it is presented as learned, not as their statement, so it does not breach the "inference is
never the person's words" invariant, but it is unintelligible).

Also: `apply_enjoyment` `LikedAspect.ACTIVITY → CATEGORY` (`preferences.py:330`, `:386-387`)
has the mirror problem — enjoying gardening endorses pool exercise. And `_diversify`
(`activity_search.py:837-877`) uses the same field, so "variety" means "a different _format_",
never "a different _kind of thing_": three Group-class walks/stretch/pool count as identical and a
walk + a tai chi + a gardening session count as identical.

**Root cause.** One free-text column serving three masters (badge, learner axis, diversity key)
with no agreed semantics. `STATED_VALUE_VOCABULARY` deliberately leaves CATEGORY open
(`preferences.py:205-207`), and `state_preference` accepts any 160-char string for it
(`main.py:1015-1019`), so the stated-preference path can store values no candidate will ever
match.

**Severity.** P1.

**Substrate.** Everything is already routed through `_candidate_dimension_value` /
`_declined_value` / `_enjoyed_value`, so the fix is three one-line reads plus the catalogue
columns.

**Design.**

- Add `PreferenceDimension.ACTIVITY_TYPE = "activity_type"` and `ACTIVITY_FAMILY =
"activity_family"`; **retire CATEGORY as a learner axis** (keep the enum member for the
  run-scope migration rows, mark deprecated, never written).
- `NOT_FOR_ME` → `ACTIVITY_TYPE` (value `candidate.activity_type.value`, `None` if OTHER — no
  fallback, same discipline as today). Optionally _also_ a half-strength `ACTIVITY_FAMILY`
  observation so "not for me" on a brisk walk transfers weakly to other MOVEMENT (this is the
  generalisation the lead wants, made explicit and bounded).
- `LikedAspect.ACTIVITY` → `ACTIVITY_TYPE` (+ family at half strength).
- `_diversify` keys on `activity_type`, tie-break on `format`.
- `STATED_VALUE_VOCABULARY[ACTIVITY_TYPE] = {m.value for m in ActivityType} - {"other"}`; web
  Privacy phrasing uses `ACTIVITY_TYPE_LABELS["walking"] = "walks"`.
- Keep `category` string column as the **format badge** only, populated from `Format` enum label.

**Files.** `models.py`, `preferences.py`, `activity_search.py`, `sql_repository.py`
(`_activity_candidate_for_key` programme branch should map `Programme` → type too),
`view-models.ts:1152-1260`, tests listed in `test_activity_responses.py:385-403, 415, 969, 1044`,
`test_activity_search.py:726-762`, `test_persistence.py:167`.
**Effort.** M.
**Test.** Decline a walk as `not_for_me`; assert Chair Mobility's `preference` factor is `0.0`
and Brisk Walk's is negative; assert the Privacy screen phrase equals "walks".

### C4. The confirmation screen silently loses non-Latin and short tokens — P1

**Evidence.** `intent.py:117` `_WORD = re.compile(r"[a-z']+")`; `:271-275` `unparsed` is built
from `_WORD.findall` with `len(word) > 2`. Probe: `早上 想去 散步` → `unparsed=[]`; `晚上 唱歌` →
`unparsed=[]`; `tai chi` → `['tai']`. The parser _does_ know three CJK time words
(`_MORNING/_AFTERNOON/_EVENING`), which is what makes this a trap: a Mandarin-typing senior gets
"In the morning" with no admission that 散步 was dropped, so the card claims full understanding.

**Root cause.** Tokeniser and filter written for English only; the CJK needles were added to the
match tables but not to the tokeniser.

**Severity.** P1 — violates the module's own rule 2 (`intent.py:31-32`) for the languages the
product names (`_LANGUAGES` lists Mandarin/Malay/Tamil/Hokkien/Cantonese).

**Design.** `_WORD = re.compile(r"[a-z']+|[一-鿿]+")`; drop the `len > 2` filter for CJK
runs; keep a 2-letter allowlist for English content bigrams ("tai chi", "qi gong") via the alias
table's multi-word entries being matched _before_ tokenising (consume whole phrase). Also add
`"don't"`/`"can't"` to `_STOPWORDS` (or strip apostrophes before lookup).
**Files.** `intent.py`, `test_intent.py`.
**Effort.** S.
**Test.** `"散步" in parse("早上 想去 散步").unparsed_terms` (until C2 lands, after which it maps to
WALKING); `parse("tai chi").unparsed_terms == []` after C2, `== ["tai chi"]` before.

### C5. Content words are mis-typed as environment/intensity — P1

**Evidence.** `_OUTDOOR` contains `"garden"` and `"park"` (`intent.py:59`); `_MODERATE` contains
`"exercise"` and `"active"` (`:62`); `_LIGHT` contains `"chair"`, `"seated"`, `"sitting"` (`:61`).
Probe: `gardening` → `env=outdoor` (hard filter, no content); `sit down exercise` →
`intensity=moderate` (opposite of what a seated class is); `exercise but indoor because raining`
→ `moderate`. `_LIGHT` is tested before `_MODERATE` so `chair exercise` → light, but only by table
order.

**Root cause.** Activity nouns are being used as proxies for the axes the schema _does_ have,
because there is no content axis (C2).

**Severity.** P1 (a hard filter for gardening; a wrong soft signal for exercise).

**Design.** Move `garden`, `park`, `exercise`, `chair`, `seated`, `sitting`, `active`, `workout`
out of the axis tables into the alias table as `ActivityType` aliases (`garden*→GARDENING`,
`chair/seated/sit down/sitting exercise→CHAIR_EXERCISE`, `exercise/workout→` family MOVEMENT,
type unset). Keep `park`/`fresh air` as _weak_ environment hints only when no type was found.
**Files.** `intent.py`, alias table, `test_intent.py`.
**Effort.** S.
**Test.** `parse("sit down exercise").intensity is EITHER` and `activity_types == [CHAIR_EXERCISE]`;
`parse("gardening").environment is EITHER` and `activity_types == [GARDENING]`.

### C6. The LLM intent parser is never exercised end-to-end, offline or otherwise — P2

**Evidence.** Unit tests use `SimpleNamespace` fake clients only (`test_intent_planner.py:50-62`,
`test_prompt_injection.py:43-54`). No API test posts `text` at all (`grep '"text":'
test_activity_responses.py test_api.py` → no hits); the only API-level search tests use `intent`
chips (`test_activity_responses.py:698-702`). E2E clicks the "Somewhere nearby" chip
(`product-loop.spec.ts:435,495`) and never types. The ranking evaluation builds intents directly
(`evaluation/ranking/dataset.py:1334-1362`), so neither parser is measured. Offline profile forbids
the LLM (`runtime.py:40-42`; `test_intent_planner.py:44`). There is no recorded-response fixture
and no "golden phrasing" corpus, so a prompt regression in `SYSTEM_PROMPT` would be invisible.

**Root cause.** Coverage stops at the seam by design (offline invariant) with nothing substituted
for the live half.

**Severity.** P2.

**Design.** (a) A phrasing corpus `apps/api/tests/fixtures/intent_phrasings.yaml` (the 35 above
plus more Singlish/Mandarin) with expected `ActivityIntent` for the keyword parser — run in CI. (b)
The same corpus run through `plan_intent` with a recorded-response fake (`client_factory`
returning stored tool inputs) so the _schema/validation/fallback_ path is exercised on realistic
payloads. (c) One API test posting `{"text": "..."}` asserting `parsed_by == "keyword"` and the
filter outcome. (d) An opt-in `pytest -m live_llm` that runs the corpus against a real provider
and reports agreement with the keyword parser — never in `pnpm verify`.
**Effort.** M.

### C7. Enum/label misalignments across parser, model, catalogue and web — P2

| where                                                                | issue                                                                                                                                                                                                                                                                                                                  |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `intent_planner.py:66-79`                                            | tool enums are hand-typed literals; `c_parse_probe` shows they _currently_ match the StrEnums, but nothing pins it. Build from `[m.value for m in TimeWindow]` and add a test.                                                                                                                                         |
| `models.py:585-596` vs `:661-666`                                    | `ActivityEnvironment` (has EITHER, no UNKNOWN) vs `IndoorOutdoor` (has UNKNOWN, no EITHER) — intentional, but `_ENVIRONMENT_COMPATIBLE` (`activity_search.py:78-82`) is the only bridge and it makes SHELTERED satisfy both INDOOR and OUTDOOR requests while a SHELTERED request rejects INDOOR. Document; not wrong. |
| `preferences.py:208-216`                                             | `STATED_VALUE_VOCABULARY[INTENSITY]` and `[SOCIAL]` include `"either"`; a stated "prefer either" can never match (`_candidate_dimension_value` never returns it). Exclude EITHER.                                                                                                                                      |
| `view-models.ts:1250-1251`                                           | `case 'social': return 'activities with other people'` regardless of value; a stated `social=solo` (allowed by the vocabulary) renders as its opposite on the Privacy screen.                                                                                                                                          |
| `view-models.ts:1254`                                                | `category` phrase = raw catalogue string; will show "drop-in, self-guided activities".                                                                                                                                                                                                                                 |
| `context_question.py:91` `_ALONE_KEYWORDS` vs `intent.py:55` `_SOLO` | two alias lists for the same concept, already drifted (`quiet`, `solo`, `myself` in one; not the other). Fold into the shared alias table.                                                                                                                                                                             |
| `fixtures.py` `synthetic_programmes()` (`:309-329`) vs `_PROGRAMMES` | the outreach `Programme` catalogue (2 items, `programme:` keys) has no category/type at all; `_activity_candidate_for_key` (`sql_repository.py:2769-2790`) resolves them with `category=None`, so a programme decline can never teach a kind. Map both to `ActivityType` in one place.                                 |
| `outreach_content.py:32-68` nudge keys                               | `gentle_nudge:indoor_walk` / `companion_walk` / `chair_mobility` are walks and chair exercise by name but carry no type; a decline there teaches nothing about walking.                                                                                                                                                |
| `apps/web` chips (`view-models.ts:961-1018`)                         | no content chips; "Something relaxing" maps to `intensity=light`, which the catalogue leaves `None` on 2/14 programmes (`_intent_reasons` then cannot match them).                                                                                                                                                     |

### C8. "walk" hard-filter vs soft-fit already partly answered by the weights — P3 (research note)

`RANKING_WEIGHTS["intent"]=7.0` and `intent_fit = matched/constrained`
(`activity_search.py:711-718`). With `activity_types` as one more axis, a single-axis request
("walk") gives walks `+7.0` and everything else `0`, which is already a near-hard ordering without
excluding anything — this is why C2 recommends soft-by-default. Whether that redundancy with the
hard filter is desirable is Subagent-ranking's territory; flagging only that the content axis
should follow the _same_ pattern as the other six axes, not a special one.

---

## Proposed taxonomy (single alias table shared by parser, catalogue normalisation and tests)

```python
# silverloop/ontology.py  — the one file that knows what "walk" means.
class ActivityType(StrEnum):
    WALKING = "walking"; TAI_CHI = "tai_chi"; CHAIR_EXERCISE = "chair_exercise"; DANCE = "dance"
    GARDENING = "gardening"; ARTS_CRAFTS = "arts_crafts"; COOKING = "cooking"; GAMES = "games"
    LEARNING = "learning"; VOLUNTEERING = "volunteering"; SOCIAL_MEETUP = "social_meetup"
    MINDFULNESS = "mindfulness"
    # Additions justified by the fixture: two programmes are none of the above.
    STRETCH = "stretch"; WATER_EXERCISE = "water_exercise"; SINGING = "singing"; READING = "reading"
    OTHER = "other"   # catalogue-only; parser never emits; never matches an intent

class ActivityFamily(StrEnum):
    MOVEMENT = "movement"; MIND_BODY = "mind_body"; CREATIVE = "creative"; SOCIAL = "social"
    LEARNING = "learning"; NATURE = "nature"; VOLUNTEERING = "volunteering"

class Format(StrEnum):
    GROUP_CLASS = "group_class"; GROUP_ACTIVITY = "group_activity"; DROP_IN_GROUP = "drop_in_group"
    SELF_GUIDED = "self_guided"; ONE_TO_ONE = "one_to_one"

TYPE_FAMILIES: dict[ActivityType, frozenset[ActivityFamily]]   # multi-label
ALIASES: dict[str, ActivityType]  # lower-cased phrase -> type; longest phrase matched first
```

Alias table (initial; every entry is a phrase the probe or the fixture actually contains):

| ActivityType   | aliases (EN / Singlish / 中文)                                                                        | families                     |
| -------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------- |
| WALKING        | walk, walking, walks, stroll, jalan, jalan jalan, 散步, 走走                                          | MOVEMENT, NATURE(if outdoor) |
| TAI_CHI        | tai chi, taichi, taiji, qigong, qi gong, 太极, 气功                                                   | MIND_BODY, MOVEMENT          |
| CHAIR_EXERCISE | chair exercise, seated exercise, sit down exercise, sitting exercise, chair mobility, seated strength | MOVEMENT                     |
| STRETCH        | stretch, stretching, 拉筋                                                                             | MOVEMENT, MIND_BODY          |
| WATER_EXERCISE | water exercise, pool, aqua, swimming, 游泳                                                            | MOVEMENT                     |
| DANCE          | dance, dancing, line dance, zumba, 跳舞                                                               | MOVEMENT, SOCIAL             |
| GARDENING      | garden, gardening, plants, 种花, 园艺                                                                 | NATURE, CREATIVE             |
| ARTS_CRAFTS    | craft, crafts, art, art and craft, handicraft, beading, sewing, painting, 手工                        | CREATIVE                     |
| COOKING        | cook, cooking, baking, 煮饭, 烹饪                                                                     | CREATIVE, LEARNING           |
| GAMES          | games, mahjong, chess, bingo, cards, 麻将                                                             | SOCIAL                       |
| SINGING        | sing, singing, karaoke, choir, 唱歌                                                                   | SOCIAL, CREATIVE             |
| READING        | read, reading, books, library, newspaper, 看书                                                        | LEARNING                     |
| LEARNING       | learn, learning, class (only when no other type), course, talk, workshop, 学                          | LEARNING                     |
| VOLUNTEERING   | volunteer, volunteering, help out, 义工                                                               | VOLUNTEERING, SOCIAL         |
| SOCIAL_MEETUP  | tea, chat, kopi, makan, meet up, kakis, befriending, 聊天, 喝茶                                       | SOCIAL                       |
| MINDFULNESS    | meditation, breathing, mindfulness, relaxation, 冥想                                                  | MIND_BODY                    |

Generic words that name a _family_ but no type: `exercise`, `workout`, `move`, `活动` → family
MOVEMENT (soft, ranks any MOVEMENT type up; never a filter).

### Fixture mapping (all 14 `_PROGRAMMES`)

| slug            | title                          | current `category`   | ActivityType   | families                    | Format         |
| --------------- | ------------------------------ | -------------------- | -------------- | --------------------------- | -------------- |
| chair-mobility  | Chair Mobility & Balance       | Group class          | CHAIR_EXERCISE | MOVEMENT                    | GROUP_CLASS    |
| sheltered-walk  | Sheltered Morning Walk         | Group class          | WALKING        | MOVEMENT, SOCIAL            | GROUP_ACTIVITY |
| evening-social  | Evening Tea & Chat             | Social group         | SOCIAL_MEETUP  | SOCIAL                      | DROP_IN_GROUP  |
| evening-stretch | Gentle Evening Stretch         | Group class          | STRETCH        | MOVEMENT, MIND_BODY         | GROUP_CLASS    |
| evening-walk    | Cool-of-Day Park Walk          | Group class          | WALKING        | MOVEMENT, NATURE, SOCIAL    | GROUP_ACTIVITY |
| tai-chi         | Tai Chi in the Park            | Group class          | TAI_CHI        | MIND_BODY, MOVEMENT, NATURE | GROUP_CLASS    |
| karaoke         | Karaoke & Social Hour          | Social group         | SINGING        | SOCIAL, CREATIVE            | DROP_IN_GROUP  |
| gardening       | Community Gardening            | Group class          | GARDENING      | NATURE, CREATIVE, SOCIAL    | GROUP_ACTIVITY |
| brisk-walk      | Brisk Neighbourhood Walk Group | Group class          | WALKING        | MOVEMENT, SOCIAL            | GROUP_ACTIVITY |
| seated-strength | Seated Strength Basics         | Self-guided          | CHAIR_EXERCISE | MOVEMENT                    | SELF_GUIDED    |
| garden-stretch  | Independent Garden Stretch     | Self-guided          | STRETCH        | MOVEMENT, NATURE            | SELF_GUIDED    |
| craft-circle    | Afternoon Craft Circle         | Social group         | ARTS_CRAFTS    | CREATIVE, SOCIAL            | DROP_IN_GROUP  |
| pool-exercise   | Warm Water Exercise            | Group class          | WATER_EXERCISE | MOVEMENT                    | GROUP_CLASS    |
| reading-corner  | Quiet Reading Corner           | Drop-in, self-guided | READING        | LEARNING                    | SELF_GUIDED    |

Outreach candidates: `gentle_nudge:indoor_walk` → WALKING/SELF_GUIDED; `companion_walk` →
WALKING/ONE_TO_ONE(social); `chair_mobility` → CHAIR_EXERCISE/SELF_GUIDED; `programme:
aac-chair-mobility` → CHAIR_EXERCISE/GROUP_CLASS; `programme:aac-sheltered-walk` →
WALKING/GROUP_ACTIVITY.

Note the current `category` strings are _not even consistent as formats_: "Sheltered Morning
Walk" and "Tai Chi" are both "Group class" though one is a class and one is a led activity;
"Quiet Reading Corner" is "Drop-in, self-guided" while "Evening Tea & Chat" (also drop-in) is
"Social group". A `Format` enum fixes that too.

Coverage check of the requested seed enums against the fixture: DANCE, COOKING, GAMES,
LEARNING(course), VOLUNTEERING, MINDFULNESS have **no fixture listing**, so a request for them
will always be `nothing_matched` — which is the correct honest answer, but the demo should
contain at least one of each family or the chips will advertise things the catalogue cannot
deliver. STRETCH/WATER_EXERCISE/SINGING/READING were needed to avoid forcing 4 fixtures into
OTHER.

### Normalisation & migration

- `ActivityCandidateRow` gains `activity_type: str | None`, `activity_families_json: list[str]`,
  `format: str | None` (Alembic + Supabase mirror `202609xx_activity_ontology.sql`, idempotent).
- `fixtures._Programme` gains the three fields explicitly (no inference from title in prod code);
  a **test** asserts `normalise(title, description) == programme.activity_type` for every fixture so
  the alias table and the hand-labelled catalogue cannot drift.
- `category` column kept, populated with `FORMAT_LABEL[format]` for the badge.

---

## Docs vs code

- `intent.py:31-32` and `models.py:622-625` promise that "anything the parser did not understand
  is carried [in `unparsed_terms`]"; `intent.py:117,274` drop CJK and ≤2-char tokens (C4).
- `docs/architecture.md:123` calls `intent.py` "the deterministic … parser" with no mention that
  content words are unsupported; `docs/api.md:250-256` documents field bounds only. Neither
  claims content parsing, so no contradiction — but nothing warns integrators that "walk" is a
  no-op.
- `test_intent.py:62-77` pins that "bird watching with my grandson" parses to nothing; under C2
  "bird watching" still yields nothing (no alias) — test stays valid.

## What NOT to build

- **Do not** make `activity_types` a hard `_RULES` filter on first search. The catalogue is 14
  programmes; a hard content filter turns most requests into `nothing_matched`.
- **Do not** let the parser emit `ActivityType.OTHER` or infer a type from mood words
  ("something nice" → MINDFULNESS). Unknown stays in `unparsed_terms`.
- **Do not** free-text-match `title`/`description` at query time as a substitute for the enum
  ("walk" in title). It looks cheap and re-creates the current problem with a fuzzier surface,
  and it makes the LLM parser and keyword parser disagree again.
- **Do not** add a multi-turn clarification dialogue. One optional "Did you mean …?" chip on the
  existing confirm card is the ceiling.
- **Do not** learn a `Format` preference from `not_for_me`. "Not for me" on a class is about the
  activity, not the format; format is at most a stated preference ("I don't like classes").
- **Do not** put the alias table in the LLM prompt. The enum in the tool schema is the constraint;
  the aliases are for the deterministic path and tests.
- **Do not** rename or delete `PreferenceDimension.CATEGORY` rows (run-scope migration
  `test_dimension_preference_run_scope_migration.py:107` relies on them); deprecate the writer.
- **Do not** try to fix negation with a general NLP dependency; a 3-token look-back over a fixed
  negator list covers every phrasing in the probe.
