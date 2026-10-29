# 0010. A family group can exist before its senior is linked

Status: Accepted (2026-10-26). Implemented in the API (migration f3a9c1e7b254); screens pending.

A family member now creates the family group on their own and invites the rest of the family with a
Join PIN; the senior is linked later, when they show their Senior-link PIN to an active member. We
chose this over the old flow (the senior signs up first and the group is created with their PIN)
because family members are the ones who sign up first in practice, and over a group created with no
senior agreement at all, because the product boundary forbids caregiver contact without consent.
Showing the Senior-link PIN stays the senior's agreement to be linked; until then the group sees
nothing about the senior.

## Consequences

- A family group can have no senior. Every screen and route that reads the senior has to handle
  that: members, the Join PIN, appointments, availability, tasks and check-ins work; steps, the
  watch, suggestions and the senior's own view show a "Link {senior}'s account" card instead. The
  name the creator typed is replaced by the senior's own account name once linked.
- A senior belongs to exactly one family group. Entering an already-linked senior's PIN is refused
  and points the family member to that group's Join PIN, so a senior's tasks and appointments are
  never split across groups that cannot see each other.
- A family member can belong to several family groups and switches between them.
- With AAC coordinators removed, a `coordinator_review` decision still opens a review case that no
  screen shows. Telling the family group instead is the natural next step, but it shares the
  senior's activity with family and needs its own senior agreement first, so it is deferred rather
  than decided.
