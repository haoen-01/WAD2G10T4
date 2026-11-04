"""The senior's watch status: simulated, labelled so, and readable only by the senior and family."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from silverloop.local_time import PROJECT_TIMEZONE
from silverloop.wearable_status import simulated_wearable
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _onboard,
    client,  # noqa: F401 - pytest fixture
    repo,  # noqa: F401 - pytest fixture
)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 14, hour, minute, tzinfo=PROJECT_TIMEZONE).astimezone(UTC)


def test_the_battery_runs_down_through_the_day_and_charges_overnight() -> None:
    morning = simulated_wearable("p1", True, _at(7))
    evening = simulated_wearable("p1", True, _at(21, 30))
    night = simulated_wearable("p1", True, _at(2))
    assert not morning.charging and not evening.charging and night.charging
    assert morning.battery_percent is not None and evening.battery_percent is not None
    assert morning.battery_percent > 80
    # Low enough by the evening for the family to be asked to remind her.
    assert evening.battery_percent < 20
    assert morning.battery_percent > evening.battery_percent


def test_the_status_is_labelled_synthetic_and_stays_in_range() -> None:
    for hour in range(24):
        for minute in (0, 30, 59):
            now = _at(hour, minute)
            status = simulated_wearable("mdm-lim", True, now)
            assert status.source == "synthetic"
            assert status.connected
            assert status.battery_percent is not None and 0 <= status.battery_percent <= 100
            assert status.last_synced_at is not None
            assert timedelta(0) <= now - status.last_synced_at < timedelta(minutes=25)


def test_the_same_person_and_time_give_the_same_answer() -> None:
    assert simulated_wearable("p1", True, _at(15)) == simulated_wearable("p1", True, _at(15))


def test_an_older_latest_reading_gives_no_made_up_sync_time() -> None:
    """A watch that synced minutes ago would have sent today's steps; with only an older reading,
    no sync time is claimed. The battery and connection stay as simulated."""
    now = _at(15)
    old = simulated_wearable("mdm-lim", True, now, date(2026, 8, 18))
    assert old.last_synced_at is None
    assert old.connected and old.battery_percent is not None and old.source == "synthetic"
    today = simulated_wearable("mdm-lim", True, now, date(2026, 10, 14))
    assert today.last_synced_at is not None


def test_sample_readings_never_get_a_sync_time_even_dated_today() -> None:
    """Sample readings were never sent by a watch, so no live sync is claimed for them."""
    now = _at(15)
    status = simulated_wearable("mdm-lim", True, now, date(2026, 10, 14), readings_synthetic=True)
    assert status.last_synced_at is None
    assert status.connected and status.source == "synthetic"


def test_no_readings_means_no_watch_connected() -> None:
    status = simulated_wearable("p1", False, _at(12))
    assert not status.connected
    assert status.battery_percent is None and status.last_synced_at is None


def test_the_senior_and_their_family_can_read_it_and_nobody_else(
    client: TestClient,  # noqa: F811
) -> None:
    _group_with_owner(client)
    person_id = client.get("/v1/me", headers=_headers("senior-1")).json()["person_id"]
    path = f"/v1/people/{person_id}/wearable"
    for sub in ("senior-1", "family-a"):
        response = client.get(path, headers=_headers(sub))
        assert response.status_code == 200, response.text
        assert response.json()["source"] == "synthetic"
        assert response.json()["connected"] is True
    _onboard(client, "outsider", "family", "Stranger")
    assert client.get(path, headers=_headers("outsider")).status_code == 404
