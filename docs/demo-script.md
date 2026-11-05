# Demo script: the loop in three minutes

One story across three parts: a simulated day reaches the **senior**, a persistent decline is
handed to a person, and the **family** shares the care.

## Before you start

```bash
pnpm demo:offline
```

Open <http://127.0.0.1:3000>. The home page should say **Backend connected**. Everything runs on
synthetic data for one demo person, Mdm Lim. To start again at any point, run `pnpm demo:reset` in
a terminal (or send `POST /v1/demo/reset` from the API docs used below).

Each reset moves Mdm Lim's sample readings so her latest day is today in Singapore, and Home says
**Today** rather than a date in August. The readings are the same every time; only their dates
move, and the sample programmes and activity listings move with them. A run started on an earlier
day keeps that day after a restart, so reset on the morning of the demo. Advancing a day moves past
today into simulated days, which keep their simulated weather: live weather only ever speaks for
today. To see the fixture's own dates (latest reading Tue, 18 Aug 2026), start the demo with
`DEMO_DATES_FOLLOW_TODAY=false`; the browser tests always do.

### The signed-in demo on shared Supabase

The offline demo above needs nothing else. For the signed-in app, run this on the morning of the
demo and before each rehearsal, because appointments are dated from the day it runs:

```bash
pnpm demo:story
```

Mdm Lim then has one programme suggestion waiting, with the earlier nudge answered **Maybe later**.
The command prints the suggestion's title; check it each time, because it can change between runs.
`sarah` lands on Mdm Lim's group with `john` and `emily`, and also has Mr Tan's made-up group with
`weiming` and `aisha`. It needs the logins from `setup_demo_accounts`; see
[Demo story](supabase.md#demo-story) for what it does and when it refuses to finish.

Her answers stay across runs. **Yes, I'd like that** and **Not for me** shape future ranking, and so
does a suggestion nobody answers, which closes as `no_response` once its reply window passes.
**Maybe later** is recorded but moves the ranking by nothing. So a rehearsal can change which
suggestion the next run offers, and three **Not for me** answers to one suggestion stop it being
offered at all. Nothing is wrong when that happens. The command stops with an error if no programme
suggestion is left to offer.

## Act 1: a day goes by (about 60 s)

There is no Simulator screen any more; a day is advanced straight through the API, which is exactly
what the browser tests do too.

1. Open <http://127.0.0.1:8000/docs>, find **POST /v1/simulation/advance**, press **Try it out**,
   and send `{"event": "activity_declines", "event_id": "demo-1", "person_id": "mdm-lim"}`.
2. The response's `state.last_decision` reads **gentle_nudge**, with the reasons. `loop_trace` in
   the same response carries all ten decision stages, each with its own evidence id.
   > "It chose the gentlest action it is allowed to take, and it says why. Every step is recorded:
   > what it observed, whether the data was good enough, the rule it applied, and what it is now
   > waiting for."
3. Refresh <http://127.0.0.1:3000>. **Today's overview** on Home now reflects the new decision.

Restraint, if asked: send `rain_explains_decline` and `state.last_decision` reads **no_action**;
send `low_wear` and it treats the gap as a device problem, not a wellbeing signal.

Handing over, if asked: send `activity_declines` again (a fresh `event_id` each time) until
`state.last_decision` reads **coordinator_review**. It takes three declining days: a check-in, then
a programme suggestion, then a case. The response's `created_case` is populated, meaning a person
would be asked to review it.

> "It stopped and asked a person. It has no further step of its own."

## Act 2: the senior replies (Senior, about 45 s)

1. Press **Open the senior screen** (or choose **Senior** in the menu).
2. Mdm Lim sees one low-pressure suggestion in plain words, and three answers: **Yes**, **Maybe
   later**, **Not for me**. Press one.
   > "Nothing is booked until she chooses, and she can say no."
3. Under **Your privacy**, turn the switch off.
4. Send `activity_declines` again from the API docs (step 1 of Act 1): `state.last_decision` reads
   **suppress** -- nothing is sent.
   > "Consent is a hard gate. No suggestion can get past it."
5. Turn the switch back on.

## Act 3: the family shares the care (Calendar and Family, about 75 s)

The calendar and family screens run on sample data kept in the browser. No API is behind them yet.

1. Open **Calendar**. It shows Mdm Lim's upcoming activities and appointments, with a coloured
   dot or label for each kind (medical visit, therapy, activity, errand).
2. Under **Coming up**, choose **Doctor's appointment**. The details show when, where and any
   notes. **Who is helping?** lists Sarah and John as **Available** and Emily as **Not available**.
   Nobody is helping yet.
3. **Viewing as** is Sarah. Press **I'll help**. Sarah now shows as **Helping**.
   > "Everyone in the family group can see who has taken it."
4. Change **Viewing as** to **John** and open the same appointment. He sees that Sarah is helping,
   and can press **I'll help** too: more than one person can help.
   Asking instead: open **Eye check-up** (a week out, nobody going), press **Ask someone** and
   **Ask** next to Emily. The day shows **Asked Emily · waiting**. Change **Viewing as** to
   **Emily**: the bell in the header shows 1 unread; open it and press **Yes, I'll go**. Emily is
   now going.
5. Open **Family**. Under **Join the group**, add a new member (a name and how they are related).
   Under **When can you help?**, pick a date and **Afternoon**, and save. It appears under
   **Family availability**, and on the calendar that person shows as **Available** for any
   appointment that afternoon.

## If something goes wrong

- **The home page says the backend is not reachable:** the API is not running. Start it with
  `pnpm demo:offline`, then refresh.
- **The decision never reaches `coordinator_review`:** run `pnpm demo:reset`, then send three
  `activity_declines` events in a row.
- **The calendar or the family group looks different than expected:** its changes are saved in this
  browser. Open **Family** and press **Reset the sample family data**.
- **A different suggestion than expected:** Care+ learns from earlier replies. `pnpm
demo:reset` starts a fresh run.
