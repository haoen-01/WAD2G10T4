# Demo script: the loop in three minutes

One story in three parts: a simulated day reaches the **senior**, a persistent decline is handed to
a person, and the **family** shares the care.

## Before you start

```bash
pnpm demo:offline
```

Open <http://127.0.0.1:3000>. Sign-in is off in the offline demo: choose senior or family, then
**Continue as the senior** or **Continue as family**. Everything runs on synthetic data for one
demo senior, Mdm Lim, and her sample family (Sarah, John and Emily). To start again at any point,
run `pnpm demo:reset` in a terminal (or send `POST /v1/demo/reset` from the API docs used below);
with sign-in off this also puts the demo family and its schedule back.

Each reset moves Mdm Lim's sample readings so her latest day is today in Singapore. The readings are
the same every time; only their dates move, and the sample programmes and activity listings move
with them. A run started on an earlier day keeps that day after a restart, so reset on the morning
of the demo. Advancing a day moves past today into simulated days, which keep their simulated
weather: live weather only ever speaks for today. To see the fixture's own dates (latest reading
Tue 18 Aug 2026), start the demo with `DEMO_DATES_FOLLOW_TODAY=false`; the browser tests always do.

### The signed-in demo on shared Supabase

For the signed-in app, run this on the morning of the demo and before each rehearsal, because
appointments are dated from the day it runs:

```bash
pnpm demo:story
```

Mdm Lim then has one community programme suggestion waiting, with the earlier nudge answered
**Maybe later**. The command prints the suggestion's title; check it each time, because it can
change between runs. `sarah` lands on Mdm Lim's group with `john` and `emily`, and also has Mr Tan's
made-up group with `weiming` and `aisha`. It needs the logins from `setup_demo_accounts`; see
[Demo story](supabase.md#demo-story) for what it does and when it refuses to finish.

Her answers stay across runs. **Yes, I'd like that** and **Not for me** shape future ranking, and so
does a suggestion nobody answers, which closes as `no_response` once its reply window passes.
**Maybe later** is recorded but moves the ranking by nothing. So a rehearsal can change which
suggestion the next run offers, and three **Not for me** answers to one suggestion stop it being
offered at all. The command stops with an error if no programme suggestion is left to offer.

## Act 1: a day goes by (about 60 s)

A day is advanced straight through the API, as the browser tests do.

1. Open <http://127.0.0.1:8000/docs>, find **POST /v1/simulation/advance**, press **Try it out**,
   and send `{"event": "activity_declines", "event_id": "demo-1", "person_id": "mdm-lim"}`.
2. The response's `state.last_decision` reads **gentle_nudge**, with the reasons. `loop_trace` in
   the same response carries all ten decision stages, each with its own evidence ID.
   > "It chose the gentlest action it is allowed to take, and it says why. Every step is recorded:
   > what it observed, whether the data was good enough, the rule it applied, and what it is now
   > waiting for."
3. Refresh Home as family: it reflects the new day.

Restraint, if asked: send `rain_explains_decline` and `state.last_decision` reads **no_action**;
send `low_wear` and it treats the gap as a device problem, not a wellbeing signal.

Handing over, if asked: send `activity_declines` again (a fresh `event_id` each time) until
`state.last_decision` reads **coordinator_review**. It takes three declining days: a nudge, then a
programme suggestion, then a case. The response's `created_case` is populated and no suggestion is
created, meaning a person would be asked to review it.

> "It stopped and asked a person. It has no further step of its own."

## Act 2: the senior replies (about 45 s)

1. Continue as the senior. **My day** shows her steps and the suggestion in plain words, with three
   answers: **Yes, I'd like that**, **Maybe later**, **Not for me**. Press one.
   > "Nothing is booked until she chooses, and she can say no."
2. Consent has no switch on the senior screen; it is stored by the API. To show the gate, send
   `POST /v1/people/mdm-lim/consent` from the API docs with
   `{"active": false, "reason": "demo"}`. Home shows **Consent withdrawn**, and the next
   `activity_declines` reads **suppress**: nothing is sent.
   > "Consent is a hard gate. No suggestion can get past it."
3. Send the same request with `"active": true` to turn it back on.

## Act 3: the family shares the care (about 75 s)

1. Continue as family and open **Calendar**. **Coming up** lists Mdm Lim's appointments and
   activities.
2. Choose **Doctor's appointment**. The details show when and where. **Who is helping?** lists
   Sarah and John as **Available** and Emily as **Not available**; nobody is helping yet.
3. **Viewing as** is Sarah. Press **I'll help**. Sarah now shows as **Helping**.
   > "Everyone in the family group can see who has taken it."
4. Change **Viewing as** to **John**. He sees that Sarah is helping, and can press **I'll help**
   too: more than one person can help.
5. Asking instead: open **Eye check-up**, press **Ask someone** and ask Emily. The card shows
   **Asked Emily · waiting**. Change **Viewing as** to **Emily**: the bell shows one unread; open it
   and press **Yes, I'll go**. Emily is now going.
6. Open **Family**. Under **When can you help?**, paint a few free hours. They appear under
   **Family availability**, and on the calendar that person shows as **Available** for any
   appointment in those hours. Every change is saved by the API.

## If something goes wrong

- **The page says "Can’t connect to Care+ right now":** the API is not running. Start it with
  `pnpm demo:offline`, then refresh.
- **The decision never reaches `coordinator_review`:** run `pnpm demo:reset`, then send three
  `activity_declines` events in a row.
- **The calendar or family looks different than expected, or a different suggestion appears:**
  Care+ keeps earlier changes and learns from earlier replies. `pnpm demo:reset` starts a fresh run
  and puts the sample family back.
