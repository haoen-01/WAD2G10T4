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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel

from silverloop.models import ContextSignal

logger = logging.getLogger("silverloop.context")

RAINFALL_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
TWO_HR_FORECAST_URL = "https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast"
HOLIDAYS_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"

_RAIN_KEYWORDS = ("rain", "shower", "thundery")
_RAINFALL_THRESHOLD_MM = 0.2

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
    ) -> None:
        self._country_code = country_code
        self._timeout = timeout_seconds
        self._holiday_cache: dict[int, set[date]] = {}

    def fetch(self, as_of: datetime) -> ExternalContext:
        with httpx.Client(timeout=self._timeout) as client:
            rain_evidence, rainy, rain_note = self._fetch_rain(client, as_of)
            holiday_evidence, is_holiday = self._fetch_holiday(client, as_of.date(), as_of)

        return ExternalContext(
            signal=ContextSignal(rainy=rainy, holiday=is_holiday, note=rain_note),
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
                reading_ts = datetime.fromisoformat(latest["timestamp"])
                values = [float(entry["value"]) for entry in latest.get("data", [])]
                max_reading = max(values) if values else 0.0
        except _LOOKUP_ERRORS as exc:
            reading_error = f"{type(exc).__name__}: {exc}"
            logger.warning("external_context_rainfall_unavailable: %s", exc)

        forecast_rain_areas: list[str] = []
        forecast_ts: datetime | None = None
        forecast_error: str | None = None
        try:
            response = client.get(TWO_HR_FORECAST_URL)
            response.raise_for_status()
            payload = response.json()["data"]
            items = payload.get("items") or []
            if items:
                latest_item = items[-1]
                forecast_ts = datetime.fromisoformat(latest_item["timestamp"])
                forecast_rain_areas = [
                    entry["area"]
                    for entry in latest_item.get("forecasts", [])
                    if any(
                        keyword in entry.get("forecast", "").lower() for keyword in _RAIN_KEYWORDS
                    )
                ]
        except _LOOKUP_ERRORS as exc:
            forecast_error = f"{type(exc).__name__}: {exc}"
            logger.warning("external_context_forecast_unavailable: %s", exc)

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
                },
            )
            return evidence, False, "Weather context unavailable: live lookup failed."

        notes: list[str] = []
        rainy = False
        if max_reading > _RAINFALL_THRESHOLD_MM:
            rainy = True
            notes.append(f"Live rainfall gauge reading {max_reading:.1f}mm in the last 5 minutes.")
        if forecast_rain_areas:
            rainy = True
            notes.append(
                f"2-hour forecast shows rain/showers in {len(forecast_rain_areas)} area(s)."
            )

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
        evidence = ContextEvidence(
            source="nea_weather_live",
            observed_at=observed_at,
            expires_at=observed_at + timedelta(hours=2),
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
