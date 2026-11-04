"""The senior's watch: whether it is connected, when it last synced, and its battery.

**Simulated.** No real device is connected yet (a future, authorised adapter such as Google Health
would replace this), so the status is worked out from the clock, the same way for the same person
and time, and every answer says `source: "synthetic"`. The rhythm is a typical smartwatch day:
charging on the bedside table overnight (22:00 to 06:00, Singapore time), full in the morning, and
running down through the day, so the battery is low by the evening. That is when the family is
asked to remind the senior to charge it.

Not a health signal: the battery and the sync time say nothing about the senior.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

from silverloop.local_time import to_local
from silverloop.models import WearableStatus

CHARGE_START_HOUR = 22
CHARGE_END_HOUR = 6
DRAIN_PER_HOUR = 5.2
CHARGE_PER_HOUR = 15.0
OVERNIGHT_START_PERCENT = 25.0
FLOOR_PERCENT = 3


def _person_offset(person_id: str) -> int:
    """0 to 11: some watches run down a little faster than others, the same each day."""
    return int(hashlib.sha256(person_id.encode()).hexdigest(), 16) % 12


def simulated_wearable(
    person_id: str,
    has_readings: bool,
    now: datetime,
    latest_day: date | None = None,
    readings_synthetic: bool = False,
) -> WearableStatus:
    """The watch as it would be at `now`. Not connected when no reading has ever come from it.

    No sync time is given when it would claim a freshness the data does not have:
    * `latest_day` (the newest daily reading) is before today (Singapore time) -- a watch that had
      synced minutes ago would have sent today's steps;
    * `readings_synthetic` -- the readings are sample data that no watch ever sent, so there was no
      sync to time, whatever day they are dated.
    """
    if not has_readings:
        return WearableStatus(
            connected=False,
            last_synced_at=None,
            battery_percent=None,
            charging=False,
            source="synthetic",
        )
    local = to_local(now)
    hour = local.hour + local.minute / 60
    offset = _person_offset(person_id)
    charging = hour >= CHARGE_START_HOUR or hour < CHARGE_END_HOUR
    if charging:
        since = hour - CHARGE_START_HOUR if hour >= CHARGE_START_HOUR else hour + 24 - 22
        battery = OVERNIGHT_START_PERCENT + since * CHARGE_PER_HOUR
    else:
        battery = 100 - (hour - CHARGE_END_HOUR) * DRAIN_PER_HOUR - offset
    percent = max(FLOOR_PERCENT, min(100, round(battery)))
    synced_minutes_ago = (offset * 7 + local.minute) % 25
    stale = latest_day is not None and latest_day < local.date()
    return WearableStatus(
        connected=True,
        last_synced_at=(
            None if stale or readings_synthetic else now - timedelta(minutes=synced_minutes_ago)
        ),
        battery_percent=percent,
        charging=charging,
        source="synthetic",
    )
