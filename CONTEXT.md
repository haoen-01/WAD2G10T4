# Care+ glossary

Terms used across the product, the API and the docs. Definitions only; design lives in `docs/adr/` and
`docs/architecture.md`.

## The daily loop

**Baseline.** A senior's own usual activity, worked out from their recent daily metrics (median and
spread over a 28-day window). Care+ compares each day against this person's baseline, never a
population average.

**Valid-wear day.** A day the wearable was worn for at least 8 hours. Days below that are treated as
unusable data, not as a quiet day.

**Decision.** What Care+ chose to do about a day, from a fixed, deterministic ladder in `policy.py`:
`suppress`, `no_action`, `gentle_nudge`, `programme_suggestion` or `coordinator_review`. The least
intrusive permitted action wins. `no_action` is a recorded result, not a skipped step.

**Gate.** One rule in that ladder, checked in order: consent, data quality, confidence, rain context,
severity and persistence, then the weekly contact cap. A gate can only hold Care+ back; no learner or
language model can open one.

**Suggestion (intervention).** The message a senior sees on the Senior screen when the decision is a
nudge or a programme suggestion.

**Outcome.** How the senior answered a suggestion: _accepted_ ("Yes, I'd like that", not proof it
helped), _declined_ ("Not for me"), _deferred_ ("Maybe later") or _no response_. Accepted, declined
and no response change how permitted suggestions are ranked; deferred does not. Three declines of one
suggestion mute it until the senior lifts the mute. A decline given as a bad day or already being
active counts towards neither, unless that reason was added later to a plain decline, which still
counts towards the mute. A mute only removes that suggestion from the options; no outcome can open a
gate or add to what is permitted.

**Contact cap.** The limit on how many suggestions a senior is sent in a week. After a senior accepts
one, they also get 3 days of quiet.

**Rain context.** Live weather that can explain a quiet day, so Care+ waits instead of nudging.

**Synthetic data.** Generated activity figures for the sample seniors, labelled _Sample_. They are
never mixed with live data.
_Avoid_: demo data, fake data

**Live data.** Daily steps read from a senior's own Google Health account with their agreement,
labelled _Live_. Only steps, plus wear time where it exists, are read.

## Family

**Family group.** The family members caring for one senior. A family member creates it, and it can
exist before its senior is linked; until then it sees nothing about the senior. A senior belongs to
one family group; a family member can belong to several.
_Avoid_: care group

**Senior-link PIN.** A 6-digit PIN the senior shows on their own screen. It lasts 10 minutes and works
once. An active member who enters it links the senior to their family group; showing it is the
senior's agreement to be linked.

**Join PIN.** A 6-digit PIN any active member can show. It lasts 7 days and can be reused. Someone who
enters it waits as _pending_ until an active member approves them.

**Appointment.** An entry on the senior's shared calendar, saved by the API.

**Availability.** When a family member can help, saved by the API.

**Helper.** A family member who has taken an appointment. An appointment with nobody taking it
_needs a helper_.

**Ask.** One family member asking another, by name, to take one day of an appointment that needs a
helper. A family group has at most one _open_ ask per appointment day. An open ask ends in exactly
one way: _accepted_ (the asked member said yes and became the helper), _declined_ (they said no; the
day needs a helper again), _withdrawn_ (the asker took it back), _lapsed_ (the appointment started
with no answer) or _closed_ (someone pressed "I'll go" instead). An ended ask never reopens; a new
ask can follow.
_Avoid_: request, invite

**Asked helper.** A family member another member has asked to take an appointment, who has not yet
said yes or no. They become the helper only by saying yes. Until then the day still _needs a
helper_.

**Notification.** A message inside Care+ for one family member: they have been asked to help, or
someone has answered their ask. The senior never gets one, and none leaves the app. It is _unread_
until its recipient opens the bell.

**Activity feed.** What family members did in the family group, newest first: appointments added or
changed, who took one, free times shared, check-ins. Only active group members see it; the senior
does not.

**Appointment note.** A family member's note on one day of an appointment. Only active group members
see it; the senior does not.

**Check-in.** A family member telling the group they called, visited or messaged the senior, with an
optional note. Care+ sends nothing and contacts no one.

**Location share.** The senior's walk as their family group sees it on a map: where they are now and
the trail walked so far today. The senior turns it on and off themselves, and turning it off forgets
what was shared.
_Avoid_: tracking

**Still for a while check-in.** A prompt to the family group when the senior, sharing their walk, has
stayed in one spot away from home longer than the family's limit. The senior is always asked "Are you
OK?" first, and only the senior can allow it. It asks a person to get in touch; it is not a safety
alert.
_Avoid_: fall alert, emergency alert

**Task.** A one-off, daily or weekly reminder for the senior, kept by their family group. The family
adds and changes tasks; the senior and the family tick each day done. A medicine task is a label
the family writes, never advice.

**Catch-up.** The family Home card that says, on a first visit, where things stand and, on a
return, what changed since the member last looked: family updates, visits that still need someone,
and today's tasks. It only repeats what the member can already see.
_Avoid_: digest, summary report

**Read my day (My day script).** A short script of the senior's day (today's appointments and
reminders, and tomorrow's first appointment) that the senior can have read aloud, by the Kokoro
voice on the Care+ server or an on-device browser voice, never an online one.

**Appointment draft.** The appointment form filled in from a sentence a family member typed
("lunch with Ma tmr 12pm"). It saves nothing; the member checks it and adds it themselves.

**Agent step.** One thing an agent did on its way to an answer: a read tool it called, or its
submission and whether the deterministic check approved it. Shown under "How Care+ wrote this".

## Backend only (no screen)

These exist in the API and its tests but no current screen shows them.

**Review setting.** How far below a senior's own baseline, and for how many low valid-wear days,
before Care+ asks a coordinator to review. It starts at 40% for 3 days and moves only within fixed
bounds, with a coordinator's approval. A drop of 60% or more for 3 low days (the _absolute floor_)
always asks a human, whatever the setting.

**Review case.** What a `coordinator_review` decision opens for a human to look at.
