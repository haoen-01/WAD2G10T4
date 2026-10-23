from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

# The wall clock this product reasons about.
#
# Everything is stored in UTC and that does not change. What changes is that "morning" is a claim
# about the clock on a person's kitchen wall, not about UTC -- and the two are eight hours apart
# here, which is enough to call an evening class a morning one.
#
# The bug this exists to fix: a session stored as 09:30Z was bucketed MORNING by the search filter
# and simultaneously rendered to the senior as "5:30 pm". The card asserted "Runs in the morning,
# as you asked" directly above a time that plainly was not morning.
#
# A fixed offset rather than `zoneinfo.ZoneInfo("Asia/Singapore")` on purpose: Singapore has had no
# daylight saving since 1982 and a permanent +08:00 offset, so the two are identical here -- and a
# fixed offset needs no `tzdata` package, which is not guaranteed present on Windows, where this
# demo is developed and run. If this product ever serves a zone that observes DST, this must
# become a real `ZoneInfo` and the fixed offset is wrong.
PROJECT_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Singapore")


def to_local(moment: datetime) -> datetime:
    """The same instant, expressed on the clock the person actually reads."""
    if moment.tzinfo is None:
        # A naive timestamp is UTC by convention everywhere in this codebase.
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(PROJECT_TIMEZONE)


def local_hour(moment: datetime) -> int:
    """Hour of the local day. Use this, never `moment.hour`, to decide a time window."""
    return to_local(moment).hour


def local_date(moment: datetime) -> date:
    """Calendar day as the person would name it.

    Distinct from `moment.date()` for any local time before 08:00, which in UTC still belongs to
    the previous day -- so an early-morning class compared with `.date()` is filtered against
    yesterday.
    """
    return to_local(moment).date()


def at_local(day: date, hour: int, minute: int = 0) -> datetime:
    """Build the UTC instant for a local wall-clock time on `day`.

    Fixtures are authored in local time because that is how a person would describe a class --
    "half nine on Wednesday" -- and storing that literal as UTC is what produced the original
    off-by-eight-hours defect.
    """
    local = datetime.combine(day, datetime.min.time(), tzinfo=PROJECT_TIMEZONE).replace(
        hour=hour, minute=minute
    )
    # Converted, not merely tagged. Persistence stores naive UTC and treats a naive value as UTC on
    # read, so returning an offset-aware local datetime would have its +08:00 silently discarded --
    # storing 09:30 as though it were 09:30Z, which is the original defect with extra steps.
    return local.astimezone(UTC)
