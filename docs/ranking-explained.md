# How Care+ ranks activities, exactly

This is the full account of how Care+ turns a senior's request into three suggestions: every
stage, every metric, and how the total is calculated. The source of truth is the code. File and
constant names are given for each rule, and both worked examples use real numbers taken from the ranker trace
(`POST /v1/evaluator/ranker/inspect`) on the offline demo.

For the presenter segment that shows this live, see `docs/demo-script.md` → **Act 2d**.

---

## 1. The pipeline at a glance

| #   | Stage                  | What it does                                                                                                         | Can it change the order?                   | Code                                                               |
| --- | ---------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------ |
| 1   | **Understand**         | Turns the words into a typed request (distance, company, time, place, pace, language, kind of activity, exclusions). | No                                         | `intent.py` (keyword parser; a model parser only when switched on) |
| 2   | **Retrieve**           | Loads the catalogue and today's context (rain from the simulated day).                                               | No                                         | `activity_search.py`                                               |
| 3   | **Hard filters**       | Removes anything the request rules out. One reason per removed listing.                                              | Removes, never reorders                    | `filter_candidates`, `_RULES`                                      |
| 4   | **Score**              | Six bounded factors, each weighted; the total is their sum.                                                          | Yes                                        | `score_candidate_detail`, `RANKING_WEIGHTS`                        |
| 5   | **Sort**               | Seven keys in a fixed order: tier, total, then tie-breaks.                                                           | Yes                                        | `SortKey.ordering()`                                               |
| 6   | **Post-process**       | Top 3 never shows two sessions of one programme; one variety swap is allowed.                                        | Only inside the top 3, within fixed limits | `_dedupe_series`, `_diversify`                                     |
| 7   | **Optional AI rerank** | A model may reorder the first 10 permitted options, bounded and checked.                                             | Only within bounds, and only when enabled  | `agent/planner.py`, `agent/guardrails.py`                          |

Offline (LLM off), stage 7 does not run (`llm_rerank.status = "fallback_disabled"`): the order is
exactly stages 3–6.

---

## 2. Stage 1: understanding the request

The request becomes an `ActivityIntent`. For **"something social, not too far"** the trace shows:

| Field                  | Value                    | Meaning                                                                           |
| ---------------------- | ------------------------ | --------------------------------------------------------------------------------- |
| `max_distance_m`       | `1000`                   | "not too far" is read as about 1 km                                               |
| `distance_is_explicit` | `false`                  | A **phrase**, not a number, so it is a _soft_ radius: it costs, it doesn't filter |
| `social_preference`    | `social`                 | "social" → with other people                                                      |
| everything else        | `any` / `either` / empty | not asked, so not constrained                                                     |
| `parsed_by`            | `keyword`                | the deterministic parser                                                          |

**The distance rule (ADR 0006 §10):** a number ("within 2 km") is a barrier, and the `too_far`
filter removes everything beyond it. A phrase ("close by", "not too far") is a preference, charged
by the friction factor. The same metres are never spent twice.

---

## 3. Stage 3: hard filters

Every listing is checked against these rules **in this order**, and removed by the first one that
applies (so each removal has exactly one reason):

1. `excluded_activity_type`: a kind of activity the person asked not to see
2. `excluded_environment`
3. `excluded_social`
4. `too_far`: beyond a distance the person gave **as a number**
5. `wrong_day`
6. `wrong_time_window`
7. `wrong_environment`
8. `wrong_company`: e.g. self-guided when they asked for other people
9. `full`: fully booked
10. `inaccessible`

**Example ("something social, not too far"): 29 found → 7 removed → 22 eligible.**

- `wrong_company` ×5: Independent Garden Stretch (×2), Quiet Reading Corner, Seated Strength Basics
  (×2), all self-guided ("you asked for something with other people")
- `full` ×2: Tai Chi in the Park (×2)

Nothing downstream, whether scoring, variety or a language model, can bring a removed listing back.

---

## 4. Stage 4: the score

### 4.1 The formula

For each eligible listing, six factors are computed. Each factor value is **bounded to [-1, 1]**
and multiplied by a fixed weight:

```text
contribution(factor) = value(factor) × weight(factor)
total                = Σ contribution  over the six factors   (rounded to 3 dp)
```

| Factor                                               | Weight  | Value range | Max it can add | Max it can take away |
| ---------------------------------------------------- | ------- | ----------- | -------------- | -------------------- |
| `intent`: what was asked today                       | **7.0** | 0 … 1       | +7.0           | 0                    |
| `preference`: kinds of activity they like or avoid   | **2.0** | -1 … 1      | +2.0           | -2.0                 |
| `engagement`: their own answers about this programme | **1.5** | -1 … 1      | +1.5           | -1.5                 |
| `repetition`: a recent "not for me" on it            | **2.0** | -1 … 0      | 0              | -2.0                 |
| `context`: today's weather                           | **1.5** | -0.5 … 1    | +1.5           | -0.75                |
| `friction`: getting there                            | **1.0** | -1 … 0      | 0              | -1.0                 |

On screen the factors are named **Matches what was asked** (`intent`), **Personal preference**
(`preference`), **Recent experience with this programme** (`engagement`), **Recently declined**
(`repetition`), **Current context** (`context`) and **Getting there** (`friction`).

**Why the weights are shaped like this:** everything learned or inferred can add at most
2.0 + 1.5 + 1.5 = **5.0**, while a full match on today's request adds **7.0**. So nothing Care+
has learned can outweigh what the person asked for today. The **tier** (§5) enforces the same thing
structurally.

### 4.2 Each factor, exactly

#### `intent` (weight 7.0): how much of today's request this listing matches

```text
value = matched / judged
```

- Only axes the request **constrained** count: distance, time window, company, environment, pace,
  language, kind of activity.
- For each constrained axis the listing is **match**, **mismatch** or **unknown** (the listing
  doesn't say).
- **Unknown is left out of both numerator and denominator.** "Not listed" is not "no".
- If the listing can answer none of what was asked, `value = 0` (no credit), but it keeps a tier of
  1.0, so it is never ranked below a listing that actually contradicts the request.
- Nothing constrained at all → `value = 0` for everyone (the factor can't separate them).

Example: "social, not too far" constrains 2 axes. A group activity 650 m away matches both →
`2/2 = 1.0` → contribution **+7.000**.

#### `preference` (weight 2.0): what's known about the kinds of activity they like

```text
value = Σ (strength_d × m_d) / Σ |strength_d|      m_d = +1 match, -1 mismatch; unknown axes skipped
```

- Each belief has a **strength** in [-1, 1]:
  - learned from behaviour: `strength = (positive − negative) / (positive + negative + 2)`
  - stated by the person ("I like…"): `strength = +1` (or `-1` for "avoid")
- An axis the **request already constrained today is not scored here** (it belongs to `intent`).
  That prevents double counting. In the scripted example, the belief "likes being with people" is
  recorded but marked `not_used_reason: constrained_by_request`, because she asked for "social".
- `coverage` = share of known beliefs this listing could be judged on (shown, not weighted).

Example (scripted history): one learned belief, "arts & crafts", from 1 positive observation →
`strength = 1/(1+0+2) = 0.333`. Afternoon Craft Circle matches it → `0.333 / 0.333 = 1.0` →
contribution **+2.000**.

> Worth knowing: because the value is normalised by total strength, one weak belief that matches
> gives the full +1.0. How much evidence stands behind it is reported separately as confidence
> ("low" here), not in the score.

#### `engagement` (weight 1.5): their own answers about this programme

```text
attended  = went − not_enjoyed        (never below 0)
positive  = 0.25 × interested + 0.35 × attended + 0.40 × enjoyed
negative  = 0.50 × durable_not_for_me + 0.50 × not_enjoyed
value     = clamp(positive − negative, −1, 1)
```

- Counted per **programme (series)**, so every session of a programme shares it.
- A "not for me" still inside its 14-day cooldown is charged to `repetition`, **not** here: one tap
  never costs twice. After 14 days it becomes a `durable_not_for_me`.
- "Did not go" is recorded but not scored (a missed plan says nothing about the activity).

Example: went once and enjoyed it → `0.35 + 0.40 = 0.75` → contribution **+1.125**.

#### `repetition` (weight 2.0): don't re-offer what they just declined

```text
value = −1   if their last "not for me" on this listing was within 14 days
        0    otherwise
```

It also lowers the **tier** (§5), so a just-declined listing drops below everything else that
matches the request equally.

#### `context` (weight 1.5): today's weather

Applies **only if rain is forecast and the person left indoors/outdoors open**:

```text
covered (indoor / sheltered) → +1.0
outdoor                      → −0.5
listing doesn't say          →  0
```

An explicit "outdoors" request is honoured regardless: this is a nudge, not an override.

#### `friction` (weight 1.0): how far beyond comfortable

```text
start  = min(comfortable_distance, soft radius from a phrase like "not too far")
value  = 0                                   if distance ≤ start
value  = −min(1, (distance − start) / 4500)  otherwise
```

- **Comfortable distance** starts at **500 m** (default). A tighter "too far" the person gave
  (with a distance) lowers it; enjoying somewhere further may raise it; a stated "somewhere near" caps
  it at 1 km. A ceiling always beats a floor.
- A phrase can only **narrow** the start point, never widen it. "Not too far" = 1 km, but this
  person's comfortable distance is 500 m, so charging starts at 500 m.
- **4 500 m** is the fixed scale: about a bus ride each way reaches the full −1.
- Unknown distance → 0 here, but it sorts last on a tie.

Example: 650 m → `(650 − 500)/4500 = 0.033` → contribution **−0.033**.

---

## 5. Stage 5: the sort (seven keys, in order)

```text
1. tier          highest first   = request tier (matched/judged; unjudged listings keep 1.0) + repetition
2. total         highest first   = the weighted sum above
3. matched_axes  most first      = request axes matched + preference beliefs matched
4. distance_m    nearest first   (unknown distance last)
5. title         A → Z
6. start_at      soonest first   (undated last)
7. activity_id   A → Z           (so the order never depends on catalogue order)
```

- **Tier first** is what makes the request dominant: a listing matching more of the ask is always
  above one matching less, whatever its total. Only the person's own recent "not for me" can drop a
  matching listing a tier.
- The total only decides the order **within** a tier.

> Known issue: `title` sits before `start_at` and `activity_id`, so display copy can break an
> exact tie. Moving it changes the committed evaluation reports, so it is scoped separately in
> `docs/ux-redesign-2026-09-17/issue-title-tiebreak.md`.

---

## 6. Stage 6: post-processing (top 3 only)

1. **Series dedupe.** The top 3 must be three different programmes. A later session of a programme
   already in the top 3 is **deferred** below it (if there aren't three distinct programmes, the best
   deferred sessions fill the gap).
2. **Variety swap (at most one).** Only if all three are the **same kind of activity**: a lower
   listing of a different kind may take 3rd place, but only if it is **in the same tier** and within
   **0.5** of the 3rd place's total. It gets a plainly worded "Something a bit different" reason.

---

## 7. Stage 7: optional AI rerank (bounded)

Only when a language model is enabled (never in the offline demo):

- It sees the **first 10** options of the stage-6 order (the trace's `deterministic_window`), never
  removed ones.
- It may move an option up **at most 3 places** (`MAX_PROMOTION`), and hiding options above counts
  as moving.
- It may narrow the list, but must keep **at least 3** (`MIN_SHOWN_AFTER_NARROWING`).
- It can't invent an activity, bring back a removed one, or change consent or hard rules.
- A deterministic **guardrail** checks the proposal. If it fails, or the model is off, unreachable
  or out of its 4-iteration budget, the deterministic order from stage 6 is used as is.

---

## 8. Worked example A: live state (what the senior saw)

Mdm Lim, **"something social, not too far"**, no history yet.

| Listing                               | Distance | intent              | preference | engagement | repetition | context | friction                 | **Total** | Tier | Axes |
| ------------------------------------- | -------- | ------------------- | ---------- | ---------- | ---------- | ------- | ------------------------ | --------- | ---- | ---- |
| Community Gardening (Mon 24 Aug)      | 650 m    | 1.0 × 7 = **7.000** | 0          | 0          | 0          | 0       | −0.033 × 1 = **−0.033**  | **6.967** | 1.0  | 2    |
| Chair Mobility & Balance (Tue 25 Aug) | 700 m    | **7.000**           | 0          | 0          | 0          | 0       | −(200/4500) = **−0.044** | **6.956** | 1.0  | 2    |
| Afternoon Craft Circle (Tue 25 Aug)   | 850 m    | **7.000**           | 0          | 0          | 0          | 0       | −(350/4500) = **−0.078** | **6.922** | 1.0  | 2    |

**How the order was reached:**

1. All three: tier 1.0 (both asks matched), so the **total** decides.
2. 6.967 > 6.956 > 6.922. The only difference is **friction**: Gardening is 650 m, Chair Mobility
   700 m.
3. Before post-processing the order was Gardening, _Gardening (another session)_, Chair Mobility,
   Chair Mobility, Chair Mobility, Craft Circle. **Series dedupe** deferred the repeat sessions, so
   Craft Circle moves up to 3rd.
4. Variety: the top 3 are already different kinds (`top_three_mixed`), so no swap.
5. AI rerank: off.

**On screen:** "Deciding factor: **getting there**. It is the only factor that scored differently for
the two."

---

## 9. Worked example B: scripted history (personalisation)

Same request, with a labelled synthetic history for Mdm Lim (preset `lim-social-nearby`, six events):
she enjoyed Evening Tea & Chat and Afternoon Craft Circle, said she was interested in Chair Mobility &
Balance, and said "not for me" to a brisk walk (too far), a pool session (too far) and a garden
stretch.

| Listing                  | Distance | intent    | preference                           | engagement                                | friction   | **Total**  | Tier | Axes |
| ------------------------ | -------- | --------- | ------------------------------------ | ----------------------------------------- | ---------- | ---------- | ---- | ---- |
| Afternoon Craft Circle   | 850 m    | **7.000** | 1.0 × 2 = **+2.000** (arts & crafts) | 0.75 × 1.5 = **+1.125** (went, enjoyed)   | **−0.078** | **10.047** | 1.0  | 3    |
| Evening Tea & Chat       | 850 m    | **7.000** | 0                                    | **+1.125** (went, enjoyed)                | **−0.078** | **8.047**  | 1.0  | 2    |
| Chair Mobility & Balance | 700 m    | **7.000** | 0                                    | 0.25 × 1.5 = **+0.375** (interested once) | **−0.044** | **7.331**  | 1.0  | 2    |

**Arithmetic for #1:** `7.000 + 2.000 + 1.125 + 0 + 0 − 0.078 = 10.047`.

**How the order was reached:**

1. Same tier (1.0) for all three, so the **total** decides.
2. Craft Circle and Tea & Chat are **identical on everything except preference**: both 850 m, both
   went-and-enjoyed. The +2.000 from "tends to prefer arts & crafts" is the whole gap (10.047 vs
   8.047).
3. Her "likes being with people" belief is **not** scored: she asked for "social" today, so it's
   already counted in `intent`.
4. Series dedupe defers the second Craft Circle session and the extra Tea & Chat sessions, so Chair
   Mobility takes 3rd.

**On screen:** "Deciding factor: **personalisation**. #1 and #2 were level on the request and today's
context. Personal preference gave #1 the edge."

---

## 10. How the page names the deciding factor (#1 vs #2)

The web computes the "Deciding factor" line from the trace only (`lib/ranker-summary.ts`,
`decidingFactor`):

- If #1 and #2 were separated **after** sorting (series dedupe, variety, AI stage), that stage is
  named.
- If the first differing sort key is **tier, matched axes, distance or start time**, that key is
  named ("more matches (3 against 2)").
- If it's the **total**: a single factor is named only if its gap alone covers #1's whole lead.
  Personalisation is named only when #1 and #2 were level on the request and context. Otherwise it
  says request and personal factors both moved the pair, or "no single deciding factor".
- A **title or id** tie-break is called "a fixed tie-break".

---

## 11. Where every number is on screen (`/ranker`)

| Depth   | Where                                                                                                 | What you can point at                                  |
| ------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Level 1 | **What Mdm Lim asked**                                                                                | the typed request and what was understood              |
| Level 1 | **From 29 activities found to 3 shown** → **7 removed: see reasons**                                  | the funnel and each removal rule                       |
| Level 1 | **Why {title} is #1**                                                                                 | grouped reasons                                        |
| Level 2 | **Why #1 beat #2** → factor table                                                                     | Ahead / Behind / Level per factor, the deciding factor |
| Level 3 | **Why #1 beat #2** → **See exact scores**                                                             | value, weight, contribution for #1 and #2              |
| Level 3 | **How ranking works** → **See exact weights and sort order**                                          | the six weights and seven sort keys                    |
| Level 4 | **Full engineering trace** → **Why listings were removed before ranking**                             | every listing's filter outcome                         |
| Level 4 | **Full engineering trace** → **How each remaining listing scored** → **How is the total calculated?** | the full scoring table for all 22 eligible listings    |
| Level 4 | **Full engineering trace** → **What personal evidence was available about Mdm Lim**                   | each belief, its strength, and whether it was used     |
| Level 4 | **Full engineering trace** → **How ties and repeats were settled**                                    | sort keys, before/after dedupe and variety             |
| Level 4 | **Full engineering trace** → **What the language model did**                                          | AI stage status and bounds                             |

---

## 12. Things to say plainly if asked

- **"Are the weights tuned?"** They are fixed and bounded by design, and chosen so today's request
  always dominates. The evaluation (`/evaluation`) tests the ordering against simpler orderings. On
  held-out personas it could **not** be shown to beat them, and the page says so first.
- **"Could a model override this?"** Only within 3 places of the first 10 permitted options, keeping
  at least 3, after a deterministic guardrail. Offline it doesn't run at all.
- **"Why is a 650 m walk penalised when she asked for within 1 km?"** A phrase narrows but never
  widens her comfortable distance, and for her that is the 500 m default. The penalty is tiny (−0.033)
  and only separates otherwise equal options.
