"""`POST /v1/assistant/chat`: the Care+ assistant (see `silverloop.assistant`).

Read-only. A senior asks about themselves; a family member about the senior they care for, and
only one whose group they belong to (the same check as every person route). The facts given to
the AI are only what that person can already see in Care+.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI, HTTPException, Request, status

from silverloop.assistant import Appointment, CareFacts, RateLimiter, answer
from silverloop.auth import PersonReader
from silverloop.config import Settings
from silverloop.family_routes import check_reader
from silverloop.local_time import local_date
from silverloop.models import AssistantChatRequest, AssistantReply, AuthRole, CurrentUser

logger = logging.getLogger("silverloop.assistant")

# The only page names passed on to the AI (anything else is dropped): see `pageName` in the web app.
KNOWN_PAGES = frozenset(
    {"Home", "My day", "Today", "Calendar", "Badges", "Family", "Walk", "Family group", "Care+"}
)

_limiter_lock = threading.Lock()


def _limiter(request: Request, settings: Settings) -> RateLimiter:
    """One fair-use limiter per app, made once even when the first questions arrive together."""
    with _limiter_lock:
        limiter: RateLimiter | None = getattr(request.app.state, "assistant_limiter", None)
        if limiter is None:
            limiter = RateLimiter(settings.assistant_rate_per_10_min)
            request.app.state.assistant_limiter = limiter
        return limiter


def _facts(request: Request, person_id: str | None, viewer: str, page: str | None) -> CareFacts:
    """What this person may see about the senior. Any part that cannot be read is left out."""
    if person_id is None:
        return CareFacts(viewer=viewer, page=page)
    repository = request.app.state.repository
    name: str | None = None
    usual: int | None = None
    week: list = []
    try:
        state = repository.person_state(person_id=person_id)
        name = state.display_name
        usual = round(state.baseline.median_steps) or None
    except Exception:  # noqa: BLE001 - a missing part never stops an answer
        pass
    try:
        week = [(m.day, m.steps) for m in repository.daily_metrics(person_id=person_id, days=7)]
    except Exception:  # noqa: BLE001
        week = []
    today = local_date(datetime.now(UTC))
    appointments: list[Appointment] = []
    store = getattr(request.app.state, "family_calendar", None)
    if store is not None:
        try:
            calendar = store.calendar(person_id, None, today, today + timedelta(days=14))
            name = name or calendar.senior_name
            appointments = [
                Appointment(title=a.title, day=a.date, start=a.start, location=a.location)
                for a in sorted(calendar.appointments, key=lambda a: (a.date, a.start))
            ]
        except Exception:  # noqa: BLE001
            appointments = []
    return CareFacts(
        viewer=viewer,
        senior_name=name,
        today=today,
        steps_today=week[-1][1] if week else None,
        usual_steps=usual,
        week_steps=week,
        appointments=appointments,
        page=page,
    )


def register_assistant_routes(application: FastAPI) -> None:
    @application.post(
        "/v1/assistant/chat",
        response_model=AssistantReply,
        tags=["assistant"],
        responses={401: {}, 403: {}, 404: {}, 422: {}, 429: {}},
    )
    def assistant_chat(
        request: Request, body: AssistantChatRequest, current_user: PersonReader
    ) -> AssistantReply:
        """One answer from the Care+ assistant. It only reads and explains: it never changes
        anything. Emergencies and questions about medicines get a fixed answer."""
        settings: Settings = request.app.state.settings
        if not _limiter(request, settings).allow(current_user.sub):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "That's a lot of questions in a short time. Please try again in a few minutes.",
            )
        person_id, viewer = _about(request, body, current_user)
        page = body.page if body.page in KNOWN_PAGES else None
        facts = _facts(request, person_id, viewer, page)
        client: httpx.Client | None = getattr(request.app.state, "assistant_http", None)
        reply = answer(body.messages, facts, settings, client)
        # What answered, never what was asked or said.
        logger.info("assistant_reply", extra={"source": reply.source, "viewer": viewer})
        return reply


def _about(
    request: Request, body: AssistantChatRequest, current_user: CurrentUser
) -> tuple[str | None, str]:
    """Which senior the question is about, and who is asking."""
    if current_user.role is AuthRole.SENIOR:
        return current_user.person_id, "senior"
    if body.person_id is None:
        return None, "family"
    check_reader(request, body.person_id, current_user)
    return body.person_id, "family"
