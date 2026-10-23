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
    provider = ExternalContextProvider()
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
    provider = ExternalContextProvider()
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
    provider = ExternalContextProvider()
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
    provider = ExternalContextProvider()
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
    provider = ExternalContextProvider()
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

    provider = ExternalContextProvider()
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

    provider = ExternalContextProvider()
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

    provider = ExternalContextProvider()
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

    provider = ExternalContextProvider(timeout_seconds=timeout_seconds)
    with (
        patch.object(httpx.Client, "__init__", capturing_init),
        patch.object(httpx.Client, "get", _mock_get(CLEAR_RAINFALL, CLEAR_FORECAST, NO_HOLIDAYS)),
    ):
        provider.fetch(AS_OF)

    assert captured["timeout"] == timeout_seconds
