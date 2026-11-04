"""Optional, best-effort real-world context: Singapore weather and public holidays.

Wraps three free, keyless endpoints (data.gov.sg rainfall, data.gov.sg 2-hour
forecast, date.nager.at public holidays) and normalises each response into the
evidence-envelope shape (source, observed_at, expires_at, confidence,
evidence_id, payload) used elsewhere in Care+'s decision trail.

Any failure here (network, timeout, unexpected schema) degrades to a
low-confidence "context unavailable" evidence item rather than either raising
or silently producing no evidence: external context is always optional, and
fixture-only demo runs must keep working with these providers unreachable,
but "the lookup failed" must stay distinguishable from "we checked and it was
clear" in the decision trace.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel

from silverloop.local_time import PROJECT_TIMEZONE
from silverloop.models import ContextSignal

logger = logging.getLogger("silverloop.context")

RAINFALL_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
TWO_HR_FORECAST_URL = "https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast"
HOLIDAYS_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"

_RAIN_KEYWORDS = ("rain", "shower", "thundery")
_RAINFALL_THRESHOLD_MM = 0.2
# How long one 5-minute rain-gauge reading may stand for "now". The 2-hour forecast carries its own
# end (`valid_period.end`); without one, two hours after it was issued.
RAINFALL_FRESH_FOR = timedelta(minutes=30)
FORECAST_FRESH_FOR = timedelta(hours=2)
# A reading or forecast stamped later than now plus this (clock skew between NEA and this server)
# is not current: weather from the future is a malformed timestamp, never rain now.
CLOCK_SKEW = timedelta(minutes=5)
# The longest valid period a 2-hour forecast may claim. A longer (or backwards) period is malformed
# and the forecast is treated as unavailable rather than as rain until, say, 2099.
MAX_FORECAST_SPAN = timedelta(hours=6)

# Errors caught around each outbound call: network failures, timeouts, HTTP error statuses and
# any shape of unexpected/malformed response body. Never a bare `except Exception` -- an
# external context lookup failing must never be indistinguishable from a real bug elsewhere in
# the request.
#
# `AttributeError` belongs here for the same reason `TypeError` does: a null-valued key is one of
# the most ordinary malformed-JSON shapes an upstream can emit, and `{"data": null}` reaches
# `payload.get(...)` as `None.get(...)`. Without it that body raised straight out of `fetch()`,
# past the "degrades rather than raising" promise in this module's own docstring. An unreadable
# body is unknown context -- never rain, never a holiday, never a crash.
_LOOKUP_ERRORS = (
    httpx.HTTPError,
    AttributeError,
    KeyError,
    ValueError,
    IndexError,
    TypeError,
)


class ContextEvidence(BaseModel):
    """One externally sourced evidence envelope.

    Always emitted, including on failure. A failed lookup is `confidence: 0.0` with
    `payload["available"] is False` and a human-readable `payload["reason"]` -- never silence,
    so the decision trace can say "weather context unavailable" instead of implying the source
    was checked and found clear.
    """

    source: str
    observed_at: datetime
    expires_at: datetime
    confidence: float
    evidence_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ExternalContext:
    signal: ContextSignal
    evidence: list[ContextEvidence]


def _nea_time(value: object) -> datetime:
    """An NEA timestamp as an aware datetime. NEA publishes Singapore time with its +08:00 offset;
    one that arrives without an offset is read as Singapore time, the only zone NEA reports in.
    Anything that is not an ISO string raises (a `_LOOKUP_ERRORS` member), so the caller treats
    that part of the body as unavailable."""
    if not isinstance(value, str):
        raise TypeError(f"expected an ISO timestamp string, got {type(value).__name__}")
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=PROJECT_TIMEZONE)


def _evidence_id(prefix: str) -> str:
    return f"E-{prefix}-{uuid4().hex[:8].upper()}"


def activity_rain_bias(signal: ContextSignal) -> bool:
    """Whether current or forecast rain should favour indoor/sheltered activities over outdoor.

    `ContextSignal.rainy` already has one job: `policy.py` reads it to excuse a quiet day rather
    than escalating it. F35 ("context on the action side") gives the same fact a second, separate
    job on the user-initiated side -- when a person is choosing something to do for themselves,
    rain makes an indoor or sheltered option the one that actually satisfies "something to do
    today", not evidence of danger. Care+ makes no claim that being outside in the rain is
    unsafe; this function only names the one condition `activity_search.rank_candidates` treats
    as a reason to reorder, keeping that judgement here rather than duplicated wherever ranking
    happens to run.

    A thin wrapper today by design: it is the single place a richer forecast signal (rain
    intensity, a time-bounded 2-hour outlook rather than "is it raining right now") would plug in
    later, without `activity_search` needing to know anything changed.
    """
    return signal.rainy


class ExternalContextProvider:
    """Fetches live weather and public-holiday context for a Singapore deployment."""

    def __init__(
        self,
        *,
        country_code: str = "SG",
        timeout_seconds: float = 3.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._country_code = country_code
        self._timeout = timeout_seconds
        # Weather is judged against the real time, never the simulated day: a reading is only
        # "current" while it is current now. Tests pass their own clock.
        self._clock = clock or (lambda: datetime.now(UTC))
        self._holiday_cache: dict[int, set[date]] = {}

    def fetch(self, as_of: datetime) -> ExternalContext:
        """Live weather as of now (the real clock), and whether `as_of`'s date is a holiday."""
        now = self._clock()
        with httpx.Client(timeout=self._timeout) as client:
            rain_evidence, rainy, rain_note = self._fetch_rain(client, now)
            holiday_evidence, is_holiday = self._fetch_holiday(client, as_of.date(), as_of)

        live = bool(rain_evidence.payload.get("available"))
        return ExternalContext(
            signal=ContextSignal(
                rainy=rainy,
                holiday=is_holiday,
                note=rain_note,
                weather_source="live" if live else "unavailable",
                weather_valid_until=rain_evidence.expires_at if live else None,
            ),
            evidence=[rain_evidence, holiday_evidence],
        )

    def _fetch_rain(
        self, client: httpx.Client, as_of: datetime
    ) -> tuple[ContextEvidence, bool, str | None]:
        max_reading = 0.0
        reading_ts: datetime | None = None
        reading_error: str | None = None
        try:
            response = client.get(RAINFALL_URL)
            response.raise_for_status()
            payload = response.json()["data"]
            readings = payload.get("readings") or []
            if readings:
                latest = readings[-1]
                # Parsed whole before any of it is used: a reading half-read is no reading.
                parsed_ts = _nea_time(latest["timestamp"])
                values = [float(entry["value"]) for entry in latest.get("data", [])]
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("a rainfall value is not a finite number")
                reading_ts, max_reading = parsed_ts, (max(values) if values else 0.0)
        except _LOOKUP_ERRORS as exc:
            reading_error = f"{type(exc).__name__}: {exc}"
            logger.warning("external_context_rainfall_unavailable: %s", exc)

        forecast_rain_areas: list[str] = []
        forecast_ts: datetime | None = None
        forecast_until: datetime | None = None
        forecast_error: str | None = None
        try:
            response = client.get(TWO_HR_FORECAST_URL)
            response.raise_for_status()
            payload = response.json()["data"]
            items = payload.get("items") or []
            if items:
                latest_item = items[-1]
                # Parsed whole -- its time, its end and its areas -- before any of it is used: a
                # forecast whose end cannot be read is unavailable, never current.
                issued = _nea_time(latest_item["timestamp"])
                period = latest_item.get("valid_period")
                if period is not None and not isinstance(period, dict):
                    raise TypeError(f"valid_period is a {type(period).__name__}, not an object")
                period_end = (period or {}).get("end")
                until = _nea_time(period_end) if period_end else issued + FORECAST_FRESH_FOR
                if not issued < until <= issued + MAX_FORECAST_SPAN:
                    raise ValueError("valid_period does not end within hours of being issued")
                areas = [
                    entry["area"]
                    for entry in latest_item.get("forecasts", [])
                    if any(
                        keyword in entry.get("forecast", "").lower() for keyword in _RAIN_KEYWORDS
                    )
                ]
                forecast_ts, forecast_until, forecast_rain_areas = issued, until, areas
        except _LOOKUP_ERRORS as exc:
            forecast_error = f"{type(exc).__name__}: {exc}"
            logger.warning("external_context_forecast_unavailable: %s", exc)

        # Weather stamped in the future is a malformed timestamp, not rain now: unavailable.
        if reading_ts is not None and reading_ts > as_of + CLOCK_SKEW:
            reading_error = reading_error or "timestamped in the future"
            reading_ts, max_reading = None, 0.0
        if forecast_ts is not None and forecast_ts > as_of + CLOCK_SKEW:
            forecast_error = forecast_error or "timestamped in the future"
            forecast_ts, forecast_until, forecast_rain_areas = None, None, []

        # Only what is still current counts. A reading or a forecast already past its time is
        # recorded as stale, never used as now (the upstream can lag, or stop updating).
        stale: list[str] = []
        reading_until = reading_ts + RAINFALL_FRESH_FOR if reading_ts is not None else None
        # Current up to and including the moment it stops speaking.
        if reading_ts is not None and reading_until is not None and reading_until < as_of:
            stale.append(f"rainfall reading from {reading_ts.isoformat()}")
            reading_error = reading_error or "stale"
            reading_ts, max_reading = None, 0.0
        if forecast_ts is not None and forecast_until is not None and forecast_until < as_of:
            stale.append(f"forecast issued {forecast_ts.isoformat()}")
            forecast_error = forecast_error or "stale"
            forecast_ts, forecast_rain_areas = None, []

        if reading_ts is None and forecast_ts is None:
            # Both the rainfall gauge and the forecast lookup failed: "unavailable", not "clear".
            reasons = [
                part
                for part in (
                    reading_error and f"rainfall: {reading_error}",
                    forecast_error and f"forecast: {forecast_error}",
                )
                if part
            ]
            evidence = ContextEvidence(
                source="nea_weather_live",
                observed_at=as_of,
                expires_at=as_of + timedelta(minutes=15),
                confidence=0.0,
                evidence_id=_evidence_id("WEATHER"),
                payload={
                    "available": False,
                    "reason": "; ".join(reasons) or "weather lookup failed",
                    **({"stale": stale} if stale else {}),
                },
            )
            return evidence, False, "Weather context unavailable: no current live reading."

        notes: list[str] = []
        rainy = False
        # Until when each current part speaks: the rain it shows, or else the dry spell.
        rain_until: list[datetime] = []
        if max_reading > _RAINFALL_THRESHOLD_MM and reading_until is not None:
            rainy = True
            rain_until.append(reading_until)
            notes.append(f"Live rainfall gauge reading {max_reading:.1f}mm in the last 5 minutes.")
        if forecast_rain_areas and forecast_until is not None:
            rainy = True
            rain_until.append(forecast_until)
            notes.append(
                f"2-hour forecast shows rain/showers in {len(forecast_rain_areas)} area(s)."
            )
        current_until = [
            until
            for ts, until in ((reading_ts, reading_until), (forecast_ts, forecast_until))
            if ts is not None and until is not None
        ]
        # Never empty: at least one part is current here, and every current part has an end.
        expires_at = max(rain_until) if rain_until else min(current_until, default=as_of)

        observed_at = max(ts for ts in (reading_ts, forecast_ts) if ts is not None)
        payload: dict[str, Any] = {
            "available": True,
            "max_rainfall_reading_mm": max_reading,
            "forecast_rain_areas": forecast_rain_areas,
        }
        if reading_error is not None:
            payload["rainfall_reading_unavailable"] = reading_error
        if forecast_error is not None:
            payload["forecast_unavailable"] = forecast_error
        if stale:
            payload["stale"] = stale
        evidence = ContextEvidence(
            source="nea_weather_live",
            observed_at=observed_at,
            expires_at=expires_at,
            confidence=0.95 if (reading_ts and forecast_ts) else 0.75,
            evidence_id=_evidence_id("WEATHER"),
            payload=payload,
        )
        return evidence, rainy, ("; ".join(notes) if notes else None)

    def _fetch_holiday(
        self, client: httpx.Client, day: date, as_of: datetime
    ) -> tuple[ContextEvidence, bool]:
        year = day.year
        if year not in self._holiday_cache:
            try:
                response = client.get(HOLIDAYS_URL.format(year=year, country=self._country_code))
                response.raise_for_status()
                payload = response.json()
                self._holiday_cache[year] = {date.fromisoformat(item["date"]) for item in payload}
            except _LOOKUP_ERRORS as exc:
                logger.warning("external_context_holidays_unavailable: %s", exc)
                evidence = ContextEvidence(
                    source="nager_date_public_holidays",
                    observed_at=as_of,
                    expires_at=as_of + timedelta(minutes=15),
                    confidence=0.0,
                    evidence_id=_evidence_id("HOLIDAY"),
                    payload={
                        "available": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "date": day.isoformat(),
                    },
                )
                return evidence, False

        is_holiday = day in self._holiday_cache[year]
        observed_at = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        evidence = ContextEvidence(
            source="nager_date_public_holidays",
            observed_at=observed_at,
            expires_at=observed_at + timedelta(days=1),
            confidence=1.0,
            evidence_id=_evidence_id("HOLIDAY"),
            payload={
                "available": True,
                "date": day.isoformat(),
                "is_public_holiday": is_holiday,
                "country_code": self._country_code,
            },
        )
        return evidence, is_holiday
