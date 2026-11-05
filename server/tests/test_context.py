"""`silverloop.context` — live weather / public-holiday context provider.

Every failure mode (network error, timeout, unexpected schema) must still produce a
`ContextEvidence` item with `confidence: 0.0` and a payload marking the source unavailable and
why. A failed lookup must never be silently indistinguishable from "we checked and it was
clear" -- that is the whole point of this module (see docs/WAYFINDER.md, Change 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from silverloop.context import ExternalContextProvider

AS_OF = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
# The real clock while the fixtures below are current: noon in Singapore, as they were issued.
LIVE_NOW = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)


def _response(url: str, payload: object, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", url))


def _rainfall_payload(readings: list[dict]) -> dict:
    return {"data": {"readings": readings}}


def _forecast_payload(items: list[dict]) -> dict:
    return {"data": {"items": items}}


CLEAR_RAINFALL = _rainfall_payload(
    [{"timestamp": "2026-08-20T11:55:00+08:00", "data": [{"station_id": "S1", "value": 0.0}]}]
)
CLEAR_FORECAST = _forecast_payload(
    [
        {
            "timestamp": "2026-08-20T12:00:00+08:00",
            "forecasts": [{"area": "Bedok", "forecast": "Fair"}],
        }
    ]
)
RAINY_RAINFALL = _rainfall_payload(
    [{"timestamp": "2026-08-20T11:55:00+08:00", "data": [{"station_id": "S1", "value": 4.2}]}]
)
RAINY_FORECAST = _forecast_payload(
    [
        {
            "timestamp": "2026-08-20T12:00:00+08:00",
            "forecasts": [{"area": "Bedok", "forecast": "Thundery Showers"}],
        }
    ]
)
NO_HOLIDAYS = []
IS_HOLIDAY = [{"date": "2026-08-20", "name": "Test Holiday"}]


def _mock_get(rainfall=None, forecast=None, holidays=None, raise_for=frozenset()):
    """Build a `side_effect` for `httpx.Client.get` keyed by URL substring.

    `raise_for` is a set of substrings ("rainfall", "two-hr-forecast", "PublicHolidays") whose
    matching call raises a connection error instead of returning a response.
    """

    def get(self: httpx.Client, url: str, *args, **kwargs) -> httpx.Response:
        if "rainfall" in url:
            if "rainfall" in raise_for:
                raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))
            return _response(url, rainfall if rainfall is not None else _rainfall_payload([]))
        if "two-hr-forecast" in url:
            if "two-hr-forecast" in raise_for:
                raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))
            return _response(url, forecast if forecast is not None else _forecast_payload([]))
        if "PublicHolidays" in url:
            if "PublicHolidays" in raise_for:
                raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))
            return _response(url, holidays if holidays is not None else NO_HOLIDAYS)
        raise AssertionError(f"unexpected URL in test: {url}")

    return get


# ── Happy path ───────────────────────────────────────────────────────────────


def test_clear_weather_and_no_holiday_produces_two_present_evidence_items() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, CLEAR_FORECAST, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)

    assert result.signal.rainy is False
    assert result.signal.holiday is False
    assert len(result.evidence) == 2
    weather, holiday = result.evidence
    assert weather.source == "nea_weather_live"
    assert weather.payload["available"] is True
    assert weather.confidence > 0
    assert holiday.source == "nager_date_public_holidays"
    assert holiday.payload["available"] is True
    assert holiday.confidence == 1.0


def test_live_rain_and_holiday_are_detected() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(RAINY_RAINFALL, RAINY_FORECAST, IS_HOLIDAY)):
        result = provider.fetch(AS_OF)

    assert result.signal.rainy is True
    assert result.signal.holiday is True
    assert result.signal.note is not None
    weather, holiday = result.evidence
    assert weather.payload["max_rainfall_reading_mm"] == 4.2
    assert weather.payload["forecast_rain_areas"] == ["Bedok"]
    assert holiday.payload["is_public_holiday"] is True


# ── The flaw: a failed lookup must never be silent ────────────────────────────


def test_weather_lookup_total_failure_still_produces_degraded_evidence_not_silence() -> None:
    """Both the rainfall gauge and the forecast lookup fail -- this must not be
    indistinguishable from "we checked and it was not raining".
    """
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client,
        "get",
        _mock_get(holidays=NO_HOLIDAYS, raise_for={"rainfall", "two-hr-forecast"}),
    ):
        result = provider.fetch(AS_OF)

    assert len(result.evidence) == 2  # never drops the evidence item on failure
    weather = next(item for item in result.evidence if item.source == "nea_weather_live")
    assert weather.confidence == 0.0
    assert weather.payload["available"] is False
    assert "reason" in weather.payload
    assert result.signal.rainy is False  # degrades to "no signal", never fabricates rain
    assert result.signal.note is not None
    assert "unavailable" in result.signal.note.lower()


def test_holiday_lookup_failure_still_produces_degraded_evidence_not_silence() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client,
        "get",
        _mock_get(CLEAR_RAINFALL, CLEAR_FORECAST, raise_for={"PublicHolidays"}),
    ):
        result = provider.fetch(AS_OF)

    assert len(result.evidence) == 2
    holiday = next(item for item in result.evidence if item.source == "nager_date_public_holidays")
    assert holiday.confidence == 0.0
    assert holiday.payload["available"] is False
    assert "reason" in holiday.payload
    assert result.signal.holiday is False


def test_partial_weather_failure_keeps_positive_confidence_and_notes_the_gap() -> None:
    """Rainfall gauge succeeds, forecast fails: still a real (if partial) reading, not a total
    failure -- confidence reflects the reduced coverage but the source stays "available".
    """
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client,
        "get",
        _mock_get(RAINY_RAINFALL, holidays=NO_HOLIDAYS, raise_for={"two-hr-forecast"}),
    ):
        result = provider.fetch(AS_OF)

    weather = next(item for item in result.evidence if item.source == "nea_weather_live")
    assert weather.payload["available"] is True
    assert 0.0 < weather.confidence < 0.95
    assert "forecast_unavailable" in weather.payload
    assert result.signal.rainy is True  # the successful rainfall reading still counts


def test_unexpected_schema_is_treated_as_a_failure_not_an_unhandled_exception() -> None:
    """A malformed/unexpected response body (e.g. upstream contract change) must degrade the
    same way a network failure does, not raise out of `fetch()`.
    """

    def get(self: httpx.Client, url: str, *args, **kwargs) -> httpx.Response:
        return _response(url, {"unexpected": "shape"})

    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", get):
        result = provider.fetch(AS_OF)  # must not raise

    assert len(result.evidence) == 2
    assert all(item.confidence == 0.0 for item in result.evidence)
    assert all(item.payload["available"] is False for item in result.evidence)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"data": None}, id="null-data"),
        pytest.param({"data": {"readings": None, "items": None}}, id="null-collections"),
        pytest.param({"data": "not-an-object"}, id="scalar-data"),
    ],
)
def test_a_null_valued_key_degrades_like_any_other_malformed_body(body: dict) -> None:
    """`{"data": null}` is one of the most ordinary malformed-JSON shapes there is, and it used
    to raise `AttributeError: 'NoneType' object has no attribute 'get'` straight out of `fetch()`
    -- past every `_LOOKUP_ERRORS` clause and into the caller. The module docstring promises that
    an unexpected schema degrades to "context unavailable"; an absent or null payload is exactly
    that, so it has to read as unknown context: never rainy, never a holiday, never a crash.
    """

    def get(self: httpx.Client, url: str, *args, **kwargs) -> httpx.Response:
        return _response(url, body)

    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", get):
        result = provider.fetch(AS_OF)  # must not raise

    assert len(result.evidence) == 2
    assert all(item.confidence == 0.0 for item in result.evidence)
    assert all(item.payload["available"] is False for item in result.evidence)
    assert result.signal.rainy is False
    assert result.signal.holiday is False
    weather = next(item for item in result.evidence if item.source == "nea_weather_live")
    assert weather.payload["reason"]


def test_a_null_payload_is_audited_as_a_provider_failure_by_class() -> None:
    """The audited reason names the exception class, the same shape a network failure records --
    "unknown context because the body was unreadable", not a silent clear sky."""

    def get(self: httpx.Client, url: str, *args, **kwargs) -> httpx.Response:
        return _response(url, {"data": None})

    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", get):
        result = provider.fetch(AS_OF)

    weather = next(item for item in result.evidence if item.source == "nea_weather_live")
    assert "AttributeError" in weather.payload["reason"]


@pytest.mark.parametrize("timeout_seconds", [3.0])
def test_provider_uses_configured_timeout(timeout_seconds: float) -> None:
    captured: dict[str, float | None] = {}
    original_init = httpx.Client.__init__

    def capturing_init(self, *args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return original_init(self, *args, **kwargs)

    provider = ExternalContextProvider(timeout_seconds=timeout_seconds, clock=lambda: LIVE_NOW)
    with (
        patch.object(httpx.Client, "__init__", capturing_init),
        patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, CLEAR_FORECAST, NO_HOLIDAYS)),
    ):
        provider.fetch(AS_OF)

    assert captured["timeout"] == timeout_seconds


# ── Freshness: only what is current now counts ───────────────────────────────


def test_a_reading_and_forecast_from_hours_ago_are_stale_not_current() -> None:
    later = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)  # 5 pm in Singapore, hours after both
    provider = ExternalContextProvider(clock=lambda: later)
    with patch.object(httpx.Client, "get", _mock_get(RAINY_RAINFALL, RAINY_FORECAST, NO_HOLIDAYS)):
        result = provider.fetch(later)

    # Old rain is never used as rain now, and it is not "checked and clear" either.
    assert result.signal.rainy is False
    assert result.signal.weather_source == "unavailable"
    assert result.signal.weather_valid_until is None
    weather = result.evidence[0]
    assert weather.payload["available"] is False
    assert weather.confidence == 0.0
    assert len(weather.payload["stale"]) == 2


def test_gauge_rain_speaks_for_half_an_hour_and_the_forecast_for_its_own_period() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(RAINY_RAINFALL, CLEAR_FORECAST, NO_HOLIDAYS)):
        gauge_only = provider.fetch(AS_OF)
    assert gauge_only.signal.rainy is True
    assert gauge_only.signal.weather_source == "live"
    # The 11:55 SGT reading, plus 30 minutes.
    assert gauge_only.signal.weather_valid_until == datetime(2026, 8, 20, 4, 25, tzinfo=UTC)

    forecast = _forecast_payload(
        [
            {
                "timestamp": "2026-08-20T12:00:00+08:00",
                "valid_period": {
                    "start": "2026-08-20T12:00:00+08:00",
                    "end": "2026-08-20T14:00:00+08:00",
                },
                "forecasts": [{"area": "Bedok", "forecast": "Showers"}],
            }
        ]
    )
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, forecast, NO_HOLIDAYS)):
        forecast_rain = provider.fetch(AS_OF)
    assert forecast_rain.signal.rainy is True
    assert forecast_rain.signal.weather_valid_until == datetime(2026, 8, 20, 6, 0, tzinfo=UTC)
    assert forecast_rain.evidence[0].expires_at == datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def test_a_stale_gauge_reading_is_ignored_while_a_current_forecast_still_counts() -> None:
    # 12:40 SGT: the 11:55 reading went stale at 12:25; the 12:00 forecast speaks until 14:00.
    now = datetime(2026, 8, 20, 4, 40, tzinfo=UTC)
    provider = ExternalContextProvider(clock=lambda: now)
    with patch.object(httpx.Client, "get", _mock_get(RAINY_RAINFALL, CLEAR_FORECAST, NO_HOLIDAYS)):
        dry = provider.fetch(now)

    # The old gauge rain is not rain now, but the forecast is a current, dry reading.
    assert dry.signal.rainy is False
    assert dry.signal.weather_source == "live"
    weather = dry.evidence[0]
    assert weather.payload["available"] is True
    assert weather.payload["max_rainfall_reading_mm"] == 0.0
    assert weather.payload["rainfall_reading_unavailable"] == "stale"
    assert weather.payload["stale"] == ["rainfall reading from 2026-08-20T11:55:00+08:00"]
    assert weather.confidence == 0.75

    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, RAINY_FORECAST, NO_HOLIDAYS)):
        forecast_rain = provider.fetch(now)
    assert forecast_rain.signal.rainy is True
    assert forecast_rain.signal.weather_source == "live"


def test_a_stale_forecast_is_ignored_while_a_current_gauge_reading_still_counts() -> None:
    forecast = _forecast_payload(
        [
            {
                "timestamp": "2026-08-20T09:00:00+08:00",
                "valid_period": {
                    "start": "2026-08-20T09:00:00+08:00",
                    "end": "2026-08-20T11:00:00+08:00",
                },
                "forecasts": [{"area": "Bedok", "forecast": "Thundery Showers"}],
            }
        ]
    )
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, forecast, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)

    # The morning forecast's showers are over: recorded as stale, never used as rain now.
    assert result.signal.rainy is False
    weather = result.evidence[0]
    assert weather.payload["forecast_rain_areas"] == []
    assert weather.payload["forecast_unavailable"] == "stale"
    assert weather.payload["stale"] == ["forecast issued 2026-08-20T09:00:00+08:00"]

    with patch.object(httpx.Client, "get", _mock_get(RAINY_RAINFALL, forecast, NO_HOLIDAYS)):
        gauge_rain = provider.fetch(AS_OF)
    assert gauge_rain.signal.rainy is True
    assert gauge_rain.signal.weather_valid_until == datetime(2026, 8, 20, 4, 25, tzinfo=UTC)


def test_a_forecast_without_a_valid_period_speaks_for_two_hours_after_it_was_issued() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, RAINY_FORECAST, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)
    # Issued 12:00 SGT with no `valid_period`: current until 14:00 SGT.
    assert result.signal.rainy is True
    assert result.signal.weather_valid_until == datetime(2026, 8, 20, 6, 0, tzinfo=UTC)

    # Just past those two hours (and the gauge reading long stale), nothing current remains.
    later = datetime(2026, 8, 20, 6, 1, tzinfo=UTC)
    stale_provider = ExternalContextProvider(clock=lambda: later)
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, RAINY_FORECAST, NO_HOLIDAYS)):
        stale = stale_provider.fetch(later)
    assert (stale.signal.rainy, stale.signal.weather_source) == (False, "unavailable")


def test_a_dry_reading_expires_when_its_first_current_part_stops_speaking() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, CLEAR_FORECAST, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)
    # Dry until the 11:55 gauge reading goes stale at 12:25 SGT, the earlier of the two.
    assert result.signal.rainy is False
    assert result.evidence[0].expires_at == datetime(2026, 8, 20, 4, 25, tzinfo=UTC)
    assert result.signal.weather_valid_until == datetime(2026, 8, 20, 4, 25, tzinfo=UTC)


def test_stale_weather_evidence_still_carries_source_timestamp_confidence_and_id() -> None:
    later = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    provider = ExternalContextProvider(clock=lambda: later)
    with patch.object(httpx.Client, "get", _mock_get(RAINY_RAINFALL, RAINY_FORECAST, NO_HOLIDAYS)):
        weather = provider.fetch(later).evidence[0]
    assert weather.source == "nea_weather_live"
    assert weather.observed_at == later
    assert weather.expires_at > weather.observed_at
    assert weather.confidence == 0.0
    assert weather.evidence_id.startswith("E-WEATHER")


# ── Malformed forecast periods and offset-less timestamps degrade, never raise ──


def _forecast_with_period(period: object, *, timestamp: str = "2026-08-20T12:00:00+08:00") -> dict:
    item: dict = {
        "timestamp": timestamp,
        "forecasts": [{"area": "Bedok", "forecast": "Showers"}],
    }
    if period is not _NO_PERIOD:
        item["valid_period"] = period
    return _forecast_payload([item])


_NO_PERIOD = object()
_BAD_PERIODS = [
    pytest.param({"start": "2026-08-20T12:00:00+08:00", "end": "garbage"}, id="bad-end-string"),
    pytest.param({"end": 1400}, id="non-string-end"),
    pytest.param("x", id="non-dict-period"),
    pytest.param(["2026-08-20T14:00:00+08:00"], id="list-period"),
]


@pytest.mark.parametrize("period", _BAD_PERIODS)
def test_an_unreadable_forecast_period_with_the_gauge_down_is_unavailable(period: object) -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client,
        "get",
        _mock_get(
            forecast=_forecast_with_period(period), holidays=NO_HOLIDAYS, raise_for={"rainfall"}
        ),
    ):
        result = provider.fetch(AS_OF)  # must not raise

    assert result.signal.rainy is False
    assert result.signal.weather_source == "unavailable"
    assert result.signal.weather_valid_until is None
    weather = result.evidence[0]
    assert weather.payload["available"] is False
    assert weather.confidence == 0.0
    assert "forecast:" in weather.payload["reason"]


@pytest.mark.parametrize("period", _BAD_PERIODS)
def test_an_unreadable_forecast_period_with_a_current_gauge_uses_the_gauge_alone(
    period: object,
) -> None:
    # A forecast from June: had its timestamp been kept despite the unreadable end, it would have
    # been taken as current. It is unavailable instead, and only the gauge speaks.
    forecast = _forecast_with_period(period, timestamp="2026-06-01T12:00:00+08:00")
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, forecast, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)

    assert result.signal.rainy is False  # the forecast's showers are not read
    assert result.signal.weather_source == "live"
    weather = result.evidence[0]
    assert weather.confidence == 0.75  # gauge only
    assert weather.observed_at == datetime(2026, 8, 20, 3, 55, tzinfo=UTC)
    assert weather.payload["forecast_rain_areas"] == []
    assert "forecast_unavailable" in weather.payload
    assert "stale" not in weather.payload


def test_a_missing_forecast_period_with_the_gauge_down_still_speaks_for_two_hours() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client,
        "get",
        _mock_get(
            forecast=_forecast_with_period(_NO_PERIOD),
            holidays=NO_HOLIDAYS,
            raise_for={"rainfall"},
        ),
    ):
        result = provider.fetch(AS_OF)

    assert (result.signal.rainy, result.signal.weather_source) == (True, "live")
    assert result.signal.weather_valid_until == datetime(2026, 8, 20, 6, 0, tzinfo=UTC)
    assert result.evidence[0].confidence == 0.75


def test_a_null_forecast_period_is_read_as_no_period() -> None:
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client,
        "get",
        _mock_get(CLEAR_RAINFALL, _forecast_with_period(None), NO_HOLIDAYS),
    ):
        result = provider.fetch(AS_OF)
    assert result.signal.rainy is True
    assert result.evidence[0].expires_at == datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def test_offset_less_nea_timestamps_are_read_as_singapore_time() -> None:
    rainfall = _rainfall_payload(
        [{"timestamp": "2026-08-20T11:55:00", "data": [{"station_id": "S1", "value": 4.2}]}]
    )
    forecast = _forecast_with_period(
        {"start": "2026-08-20T12:00:00", "end": "2026-08-20T14:00:00"},
        timestamp="2026-08-20T12:00:00",
    )
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(rainfall, forecast, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)  # must not raise comparing naive and aware times

    assert (result.signal.rainy, result.signal.weather_source) == (True, "live")
    weather = result.evidence[0]
    assert weather.confidence == 0.95
    assert weather.observed_at == datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
    assert weather.expires_at == datetime(2026, 8, 20, 6, 0, tzinfo=UTC)

    # The same offset-less reading, judged at 5 pm Singapore time, is stale rather than current.
    later = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    with patch.object(httpx.Client, "get", _mock_get(rainfall, forecast, NO_HOLIDAYS)):
        stale = ExternalContextProvider(clock=lambda: later).fetch(later)
    assert (stale.signal.rainy, stale.signal.weather_source) == (False, "unavailable")


def test_a_half_readable_gauge_reading_is_no_reading() -> None:
    rainfall = _rainfall_payload(
        [{"timestamp": "2026-08-20T11:55:00+08:00", "data": [{"station_id": "S1", "value": "x"}]}]
    )
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(rainfall, CLEAR_FORECAST, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)
    weather = result.evidence[0]
    assert "rainfall_reading_unavailable" in weather.payload
    assert weather.confidence == 0.75  # the forecast alone
    assert weather.observed_at == datetime(2026, 8, 20, 4, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "current"),
    [
        (datetime(2026, 8, 20, 4, 25, tzinfo=UTC), True),  # the exact moment it stops speaking
        (datetime(2026, 8, 20, 4, 25, 1, tzinfo=UTC), False),  # one second later
    ],
)
def test_a_gauge_reading_is_still_current_at_the_moment_it_expires(
    now: datetime, current: bool
) -> None:
    provider = ExternalContextProvider(clock=lambda: now)
    with patch.object(
        httpx.Client, "get", _mock_get(RAINY_RAINFALL, raise_for={"two-hr-forecast"})
    ):
        result = provider.fetch(now)
    assert result.signal.rainy is current
    assert result.signal.weather_source == ("live" if current else "unavailable")


@pytest.mark.parametrize(
    ("now", "current"),
    [
        (datetime(2026, 8, 20, 6, 0, tzinfo=UTC), True),
        (datetime(2026, 8, 20, 6, 0, 1, tzinfo=UTC), False),
    ],
)
def test_a_forecast_is_still_current_at_the_end_of_its_period(now: datetime, current: bool) -> None:
    forecast = _forecast_with_period(
        {"start": "2026-08-20T12:00:00+08:00", "end": "2026-08-20T14:00:00+08:00"}
    )
    provider = ExternalContextProvider(clock=lambda: now)
    with patch.object(httpx.Client, "get", _mock_get(forecast=forecast, raise_for={"rainfall"})):
        result = provider.fetch(now)
    assert result.signal.rainy is current


@pytest.mark.parametrize(
    ("rainfall", "forecast"),
    [
        # A gauge reading stamped in 2099, raining hard.
        (
            _rainfall_payload(
                [
                    {
                        "timestamp": "2099-01-01T12:00:00+08:00",
                        "data": [{"station_id": "S1", "value": 5}],
                    }
                ]
            ),
            "clear",
        ),
        # A rainy forecast issued long ago whose valid period claims to run until 2099.
        (
            None,
            {"start": "2026-06-01T12:00:00+08:00", "end": "2099-01-01T00:00:00+08:00"},
        ),
        # A rainy forecast issued in the future.
        (
            None,
            {"start": "2099-01-01T12:00:00+08:00", "end": "2099-01-01T14:00:00+08:00"},
        ),
        # A valid period that ends before it was issued.
        (
            None,
            {"start": "2026-08-20T12:00:00+08:00", "end": "2026-08-20T11:00:00+08:00"},
        ),
    ],
)
def test_weather_from_the_future_or_with_a_nonsense_period_is_never_rain_now(
    rainfall: dict | None, forecast: dict | str
) -> None:
    gauge_down = _rainfall_payload([])
    if forecast == "clear":
        forecast_body = CLEAR_FORECAST
    else:
        forecast_body = _forecast_with_period(forecast, timestamp=forecast["start"])
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(
        httpx.Client, "get", _mock_get(rainfall or gauge_down, forecast_body, NO_HOLIDAYS)
    ):
        result = provider.fetch(AS_OF)
    assert result.signal.rainy is False
    weather = result.evidence[0]
    assert weather.expires_at is None or weather.expires_at.year < 2099


@pytest.mark.parametrize("value", ["inf", "nan", "-inf"])
def test_a_rainfall_value_that_is_not_a_finite_number_is_no_reading(value: str) -> None:
    rainfall = _rainfall_payload(
        [{"timestamp": "2026-08-20T11:55:00+08:00", "data": [{"station_id": "S1", "value": value}]}]
    )
    provider = ExternalContextProvider(clock=lambda: LIVE_NOW)
    with patch.object(httpx.Client, "get", _mock_get(rainfall, CLEAR_FORECAST, NO_HOLIDAYS)):
        result = provider.fetch(AS_OF)
    assert result.signal.rainy is False
    assert "rainfall_reading_unavailable" in result.evidence[0].payload
