# 0014. Asks lapse when they are read or written, not on a schedule

Status: Accepted (2026-11-02). Implemented in the API (migration e6b2d9a4c718); screens pending.

An open **ask** (one family member asking another to take one appointment day) has to end when
that appointment starts, and the asker has to be told it went unanswered. Care+ has no scheduler or
background worker, and the offline demo must keep running as a single SQLite process.

## Decision

Every ask read and write (`/v1/groups/{group_id}/asks...`), "I'll go" (`POST .../helpers`),
editing or deleting an appointment, and `GET /v1/me/notifications` first ends the caller's groups'
open asks whose start has passed (`family_asks.lapse_due`). An edit or delete therefore never
withdraws an ask that should already have lapsed. The start is the appointment's **current** start time on that day, in
Singapore time (`local_time.at_local`), so an ask whose appointment moved to a later time on the
same day lapses at the new start. An ask whose appointment or day is gone is withdrawn instead.

Asking, accepting, declining, withdrawing, "I'll go", editing and deleting first lock the
appointment row (`FOR UPDATE` on
PostgreSQL; SQLite runs one writer at a time anyway), then lapse. They therefore run one at a time
per appointment, and an ask cannot open on a day that has just been taken or removed. Taking the
lock before lapsing, which updates asks in `ask_id` order, keeps the lock order the same on every
path.

Each ending is a compare-and-set on `state = 'open'`, and the `ask_lapsed` notification to the
asker is written in the same transaction only when that row changed.

## Consequences

- Some GET routes write, so they open a write transaction.
- A lapse is recorded when someone in the group next looks, not at the exact start time. Nobody can
  see an open ask whose day has started, because every read lapses it first.
- No infrastructure is added; the offline demo and the tests run as before.
- Concurrent readers cannot notify the asker twice: only the request whose update changed the row
  writes the notification.
- A scheduler would be needed only for delivery outside the app (email or push), which is out of
  scope.
