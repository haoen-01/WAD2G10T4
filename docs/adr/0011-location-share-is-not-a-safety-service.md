# 0011. Location share is the senior's choice and not a safety service

Status: Accepted (2026-10-26). Amended 2026-10-29: the live walk map and the "Still for a while"
check-in are allowed, each behind its own switch on the senior's page. Implemented in the web app
on a simulated demo walk only.

The senior decides, on their own screen, what their family group sees, with two switches that are
both off by default:

- **Share my walk with my family.** The family sees the senior's walk on a map: where they are now,
  the trail walked so far today, and a replay of it. Turning it off hides the walk from the family at
  once and forgets the trail, the stops and any check-in.
- **Tell my family if I stay in one place.** Only available while the walk is shared. If the senior
  stays in one spot away from home for longer than a limit the family chooses (30 minutes to 4
  hours), the senior's own page first asks "Are you OK?". Only if nobody answers by the limit does
  the family see a check-in asking them to get in touch. "I'm OK" from the senior, or "She's fine"
  from the family, ends it. There is no check-in at home, at a usual place marked as never alerting,
  or during a calendar appointment.

Care+ still contacts no one by itself and dispatches nothing: a check-in is a prompt for a family
member to decide what to do. It is a timer on location, not fall detection, and it never says the
senior has fallen or is unwell. The screen still says plainly that Care+ is not a safety or
missing-person service.

## Why this changed

The first version (26 Oct) allowed only the latest rough area and time, with no history and no
alerts, to keep Care+ clear of emergency monitoring. The team has since built the walk map and the
check-in and chose to keep them: families wanted to see the walk itself, and a check-in that asks
the senior first and leaves the decision to a person is still not emergency monitoring. What did not
change is that the senior opts in. Sharing turned on by a caregiver on someone's behalf stays out of
scope, because switching it on for someone who may lack the capacity to agree is a legal decision a
screen cannot make, and the feature still will not help a senior who goes missing without having
turned sharing on.

## Consequences

- The walk today is a simulated route kept in the browser (`localStorage`), like Tasks: no real
  positions reach the API and none are stored server-side. Using real positions means moving the
  walk and both switches into the API first, so FastAPI owns that state as it owns every other
  domain write, and recording the senior's choice there.
- The family's check-in limit and "usual places" sit with the family, but the switch that allows any
  check-in at all sits only with the senior.
- Issue #19 (turning a position into an area name) is no longer needed for the map itself. It only
  matters if an area name is shown beside the walk.
