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

**Outcome.** How the senior answered a suggestion: _accepted_ ("show me more", not proof it helped),
_declined_, _deferred_ ("maybe later") or _no response_. Outcomes adapt which permitted suggestion is
offered next; they never change what is permitted.

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

**Asked helper.** A family member another member has asked to take an appointment, who has not yet
said yes or no. They become the helper only by saying yes.

**Notification.** A message inside Care+ for one family member: they have been asked to help, or
someone has answered their ask. The senior never gets one, and none leaves the app.

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

**Task.** A one-off, daily or weekly reminder for the senior, shared by the senior and their family
group.

## Backend only (no screen)

These exist in the API and its tests but no current screen shows them.

**Review setting.** How far below a senior's own baseline, and for how many low valid-wear days,
before Care+ asks a coordinator to review. It starts at 40% for 3 days and moves only within fixed
bounds, with a coordinator's approval. A drop of 60% or more for 3 low days (the _absolute floor_)
always asks a human, whatever the setting.

**Review case.** What a `coordinator_review` decision opens for a human to look at.
