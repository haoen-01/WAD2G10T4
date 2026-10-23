# Pitch-day demo runbook

> **Read this first.** The screen-by-screen sections below were written for the previous, larger
> web app (Ask Care+, goals, review timing, evaluation screens, the Care Team screens, and the
> Simulator screen -- all since removed). The current app has only Home, Senior, Calendar and Family
> screens: follow `docs/demo-script.md` for the flow, which drives day-advance events straight
> through the API's `/docs` instead of a Simulator screen. Wherever the sections below say
> Simulator, Care Team or the case page, that screen no longer exists. The numbers you can quote,
> the safety proofs and the recovery steps still apply, because they come from the API and its
> tests, not from a screen.

## Ten minutes before judging

1. Connect the laptop to power and keep the demo local.
2. Run `pnpm setup` and `pnpm verify` on the final commit.
3. Start `pnpm dev` with the server-side Supabase URL in `.env`.
4. Run `pnpm seed` once against that database. The API's own startup (`ensure_active_run`)
   deliberately seeds only the demo person (Mdm Lim), so the other four personas -- Mr Ravi, Mdm
   Siti, Mr Tan, Mdm Devi -- only exist after `pnpm seed` is run explicitly. Re-run it any time you
   need a clean multi-persona baseline; it is idempotent per person.
5. Open `/`, `/senior` and `/calendar` in separate tabs, plus the API docs at `/docs` for advancing
   simulated days (see `docs/demo-script.md`).
6. Run `pnpm demo:reset` (or send `POST /v1/demo/reset` from `/docs`) and confirm Mdm Lim's state on
   Home reads **Normal**. (Starting a guided scenario resets for you, so this is belt-and-braces.)

   **Reset is not a blank slate for preferences.** It starts a new run, which hides everything
   learned in the old one, but it deliberately keeps the person's own **standing statements** (a
   "prefer" or "avoid" with no `until` day) and their **goals** (ADR 0004): those are the person's
   instructions, not learning. A rehearsal that stated "I like mornings" still ranks mornings
   first after a reset. To start genuinely fresh:
   - **Offline demo (`pnpm demo:offline`):** stop the API, delete `.demo/silverloop.db`, and start
     it again; the database is recreated and Mdm Lim is seeded on startup (run `pnpm seed` again
     for the other personas).
   - **Shared data (Supabase):** never delete the database. On `/senior`, open **Privacy and your
     choices** and press **Forget this** on each stated preference under **Your preferences**, then,
     on `/senior` under **Your week → Your goals**, press **Stop this goal** on each goal (a stopped
     goal stays listed, greyed, with **Start again** if one is stopped by mistake). For a scripted
     reset, the API does the same: `POST /v1/people/{person_id}/goals` with `"active": false` for
     that `kind`.

## Recommended 150-second sequence

Open on the comparison, not the baseline. The single most persuasive fact this system has is that
**the same step count means opposite things for two different people** — and that a universal
threshold gets one of them wrong every single day. Lead with it.

### 0:00 — The two-person opening (the whole pitch, in fifteen seconds)

Show Mdm Lim (personal baseline ~5,850 steps) and Mr Ravi (~2,400 steps, stable, knee discomfort
disclosed) side by side. Both at roughly 2,500 steps today.

> "Same number. For Mdm Lim that is a large drop from her own normal. For Mr Ravi it is an
> ordinary day. A universal step threshold cannot tell those apart — so it contacts Mr Ravi
> **every single day**. Ours contacts him **never**, and records why each time."

Point at the per-persona table in `docs/evaluation/policy-comparison.md`: for `mr-ravi`, both
baseline policies score 5/5 unnecessary contacts; Care+ scores 0/5, with 5/5 audited no-action.
This is measured output from `pnpm evaluate`, reproducible from a frozen seed — not a slide.

### 0:25 — Restraint under context

On `/simulator`, start the guided scenario **Rain explains a quiet day** and press **Run the first
day**. Decision: **No action needed**.

> "A threshold alert would already have contacted someone. We wait, and we record the reason."

Press **Run the next day**. The skies clear, activity stays low, and the decision moves to
**Support offered** — because the explanation stopped fitting, not because the step count changed.
One more day and it reaches **Human review**.

> "Same low activity, three different answers. The step count never moved the decision on its own."

Do not claim a second rainy day would also be no-action: the rain gate is
`rainy and sustained_low_days < 2`, so once a decline spans two valid-wear days the policy proceeds
regardless of the weather. The scenario above is built around what the ladder actually does.

### 0:50 — The loop, made visible

The day's result is the whole default view: what changed, what Care+ knew, what it decided and
why, what happens next, and, only when something changed, **What changed for next time**. Relevant
facts, the full world model and the trace are one disclosure down. Open **Full decision trace** to walk
the ten engineering stages: observation, validation, reasoning, policy gate, action, response, outcome,
follow through, learning, audit. Every stage carries an evidence ID.

### 1:15 — Act, then learn

Open the senior view, choose a response, return to the simulator. Show the appended outcome evidence
and the candidate preference moving. This is the part that makes it a loop rather than a detector:
the outcome changes what gets offered next time.

If nobody answers, the loop still closes. Run **A decline that persists** to its third day, open
Care Team and expand **Follow-through, person by person**. The day-1 check-in now reads **No reply
recorded**: the system closed it two days after it was made and weighted it as silence, not a refusal.
The day-2 suggestion is still waiting for a reply until its own date. Nothing waits forever, and nothing
unanswered is scored as a "no".

### 1:30 — The senior chooses, and Care+ learns from that too

Still on the senior view, open **Ask Care+**, pick a chip or two, confirm what it understood,
and tap **I'm interested** on the first card: it lands on the person's week in plain words. Tap
**Not for me -> Too far** on a distant card: the confirmation says Care+ will lean away from
things that far, and under **Privacy -> Your preferences** the belief appears with its provenance
("picked up from what you said no to"), a **That's right** and a **Forget this**. State one
yourself with **until** a day and it expires on the demo calendar, not the wall clock. Advance past
the planned day and the home asks **How did it go?**; **I went** unlocks **how was it?**. Nothing
here touched the outreach policy, and the coordinator's view of it is counts only.

**What Care+ knows about you** (Privacy) is the honest inventory: every fact with where it
came from -- "you told us", "picked up", "from the demo profile" -- what it does not know, and,
when a learned belief and the person's own words disagree, which one wins.

### 1:40 — Escalate to a human, not to a decision

Run the guided scenario **A decline that persists** end to end: check-in, then support offered,
then **Human review**. Open Care Team. The roster is grouped as **Needs your judgement**, **Waiting for
a reply**, **Care+ is monitoring** and **No attention needed** (collapsed). Mdm Lim is under
**Needs your judgement**. Press **Review** on her row to open her case page
(`/care-team/cases/[caseId]`). It shows why you are seeing this, what changed, what Care+ already
tried, what it checked, what is still unclear, and **If you do nothing**. Under **What do you want to
do?**, choose **Go with the suggestion**, **Not now** or **Do something different** (which records a
structured reason), then under **Then the case…** choose **Stays open — Care+ keeps monitoring**
or **Closes**, add a note and press **Record decision**. **What did this review teach?** then says what
the review taught. Evidence IDs are collapsed under **Technical evidence**.

> "No call was placed. No booking was made. A person decides."

**Optional caregiver beat (+30s): the order to read the caseload.** The roster keeps the
care-priority board's reading order inside each group, with no per-person score. Open **How this order
is set** below the roster for the thresholds and their sources. Close Mdm Lim's case, and **Back to
Care Team** says which group she now sits in. Full script and likely questions:
`docs/care-priorities.md` (the board's own window labels and top-k control predate the grouped
roster).

> "It notices a 600-step dip, but it can never suggest contact the safety rules did not already
> allow."

### 2:05 — Tell a broken tracker from a quiet day

Run the guided scenario **The tracker was not worn** — one day, near-zero steps, and almost no
wear-time. Or switch to Mdm Siti (irregular sync) in Advanced controls for the same point on a
persona built for it.

> "This is not a wellbeing signal. It is a flat battery. We surface device support and we do not
> infer anything about her from data we do not have."

Note the distinction explicitly: zero steps with _good_ wear time is a real low-activity day and is
treated as one. Only zero steps with _poor_ wear time reads as a device problem.

### 2:25 — Close on the boundary

> "Care+ does not replace Singapore's existing health and community infrastructure. It is the
> coordination layer that helps decide when those resources should be used, for whom, and what
> actually worked."

## Optional: a coordinator adjusts future review timing (review setting)

Offline, with sign-in off. Run the guided scenario **A coordinator adjusts future review timing** on
**Mdm Wong**, a synthetic persona whose activity naturally swings. Before each marked day, follow the
instruction on Care Team, tick "I've done this", then run the day. Care Team calls the review setting
"review timing".

1. A normal swing asks a human. Under **Needs your judgement**, press **Review** on Mdm Wong's row, choose
   **Do something different → Not a concern for this person**, **Closes**, add a note and press
   **Record decision**. Offline, the fixed rule waits for a second such review.
2. The second swing does the same. Press **Open Mdm Wong's review timing** (shown while a proposal is
   waiting; it opens her case at its **Review timing** panel) to see the proposal (40% for 3 low days → 4 low days), the replay, and which reviews counted.
   Choose **I agree that this is the cause**, then **Approve this change**. Demo tools → **What a Senior
   Sees** shows the notice.
3. The next similar swing stays quiet.
4. A longer decline still asks on day 4. First open her review timing (her case page → **Review timing**). Then review the case: **Go with the
   suggestion**, **Closes**, tick **This should have reached me sooner**, and **Record decision**. From the next
   day the setting is back to 3 low days, the senior is told, and History shows what the earlier
   suggestion missed.

Say plainly that offline this is the fixed rule. The agent needs the shared profile with the language
model on, or the committed recording, which is synthetic and labelled as a replay. For the evidence
across imperfect coordinators, see `docs/evaluation/review-calibration.md` (regenerated by
`pnpm evaluate`). It shows synthetic sequences and three simulated coordinator profiles, not real
coordinators.

## Optional: a plan that can no longer happen (replanning)

Offline, with sign-in off. Start the guided scenario **A plan that can no longer happen** on Mdm Lim.
Before day 1, on the Senior screen, ask for "Something outdoors tomorrow", confirm with **That's
right**, and choose **I'm interested** until a result is added to her week. Run the day. The session
fills, and Care+ either proposes a similar listing it actually found or says it found none. Nothing
on her week changes until she answers on her own screen.

## Numbers you can quote, all reproducible

| Claim                                                                                                                                      | Source                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------- |
| Both baselines contact Mr Ravi 5/5; Care+ 0/5                                                                                         | `pnpm evaluate`, per-persona table      |
| Care+: **0 hard policy violations**; baselines: 33 and 20                                                                             | same run, CI-gated                      |
| Contact-cap breaches: baselines 5, Care+ 0                                                                                            | same run                                |
| A naive pipeline over-reports a real Apple Health export by **576,731 steps (6.3%)** because a watch and a phone recorded the same walking | `AppleHealthExportAdapter`, 1,411 days  |
| 5 personas, 15 core scenarios (59 decision steps) plus 5 holdout scenarios                                                                 | `docs/evaluation/policy-comparison.md`  |
| Ranking NDCG@3 against a random floor, with confidence intervals and ablations, on a synthetic labelled catalogue                          | `docs/evaluation/ranking-evaluation.md` |

**Say the sample size out loud.** Five synthetic personas over 59 decision steps is a software-policy
simulation, not clinical validation. Volunteering that is stronger than being asked. The other
rows above are read from the same artifact; if `pnpm evaluate` has been re-run since, quote the
regenerated numbers, not these.

## What to say if asked "why is this agentic?"

Persistent case state across days, a human interrupt, waiting on a real-world outcome, and
autonomous re-entry once that outcome arrives. Step 1:15 above is the proof — the loop re-enters and
changes its own future ranking. A cron job does not do that.

## Safety proof on request

- **Tracker removed:** reset, then click **Tracker not worn**; confidence falls and outreach is
  blocked.
- **Consent revoked:** reset, then click **Consent revoked**; the policy returns `suppress`.
- **Notification fatigue:** run `pnpm test:scenarios` and show `07_contact_cap.yaml` passing.
- **No cloud:** disconnect Wi-Fi. The fixture API and all policy decisions continue to work.
- **Consent pauses learning:** revoke consent, then tap **Not for me -> Too far** on a search card;
  the tap is recorded and nothing is inferred (Your preferences stays empty). Re-grant and it
  learns again. What the person states outright is honoured either way.

## Recovery

- Bad state: click **Reset** (simulator → **Advanced controls**).
- **Stored demo state is out of date**: the local demo data was saved by an older version of Care+.
  Press **Reset local synthetic demo** on the message; it resets that person's run. This is not an API
  outage.
- API not responding: restart `pnpm dev:api`, then refresh.
- UI not responding: restart `pnpm dev:web`; the API state remains available until its own restart.
- Supabase or network unavailable: stop the shared runtime and start `pnpm demo:offline`. The
  fallback creates separate SQLite fixture state and never pretends to contain the shared data.
- Both processes fail: run the API tests and scenario runner in the terminal as the evidence-first
  fallback.

Never substitute real senior data, real programme availability or a live government integration on
pitch day.
