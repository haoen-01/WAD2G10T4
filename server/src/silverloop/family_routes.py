"""HTTP routes for accounts, family groups, the family calendar, asks and notifications, and
tasks. The rules live in `silverloop.family_groups`, `silverloop.family_calendar`,
`silverloop.family_asks` and `silverloop.family_tasks`."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from silverloop.assistant import RateLimiter
from silverloop.auth import Family, PersonReader, Senior, SignedIn
from silverloop.config import Settings
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_catchup import build_context as build_catch_up_context
from silverloop.family_catchup import catch_up
from silverloop.family_drafts import build_context as build_draft_context
from silverloop.family_drafts import draft as draft_appointment
from silverloop.family_groups import DEMO_FAMILY, FamilyGroupError, FamilyGroups
from silverloop.family_tasks import FamilyTaskStore
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import (
    Appointment,
    AppointmentDraft,
    AppointmentDraftRequest,
    AppointmentNote,
    AppointmentNoteRequest,
    AppointmentRequest,
    AuthRole,
    AvailabilityEntryOut,
    AvailabilityRequest,
    CareGroup,
    CatchUp,
    CheckInRequest,
    CreateGroupRequest,
    CurrentUser,
    FamilyActivityEntry,
    FamilyActivityPage,
    FamilyCalendar,
    HelperAsk,
    HelperAskList,
    HelperAskRequest,
    JoinGroupRequest,
    LinkSeniorRequest,
    MeResponse,
    MyDay,
    MyGroup,
    NotificationPage,
    NotificationReadRequest,
    OccurrenceAnswerRequest,
    OccurrenceRequest,
    OnboardRequest,
    PinResponse,
    SeniorNameRequest,
    SpeechRequest,
    SpeechVoice,
    SpeechVoiceOption,
    Task,
    TaskDayRequest,
    TaskList,
    TaskRequest,
    WearableStatus,
)
from silverloop.senior_day import build_context as build_my_day_context
from silverloop.senior_day import my_day
from silverloop.tts import (
    SPEECH_BUSY_CODE,
    VOICES,
    SpeechBusy,
    SpeechUnavailable,
    speak,
    unavailable_reason,
    voice_label,
)
from silverloop.wearable_status import simulated_wearable


def _family(request: Request) -> FamilyGroups:
    family: FamilyGroups | None = getattr(request.app.state, "family", None)
    if family is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Family groups are unavailable")
    return family


def _calendar(request: Request) -> FamilyCalendarStore:
    store: FamilyCalendarStore | None = getattr(request.app.state, "family_calendar", None)
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The calendar is unavailable")
    return store


def _tasks(request: Request) -> FamilyTaskStore:
    store: FamilyTaskStore | None = getattr(request.app.state, "family_tasks", None)
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Tasks are unavailable")
    return store


def _call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except FamilyGroupError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def _today() -> date:
    return local_date(datetime.now(UTC))


logger = logging.getLogger("silverloop.family")

_limiters_lock = threading.Lock()


def _limiter(request: Request, name: str, limit: int) -> RateLimiter:
    """One fair-use limiter per app and purpose, made once even when the first requests race."""
    with _limiters_lock:
        limiters: dict[str, RateLimiter] | None = getattr(request.app.state, "route_limiters", None)
        if limiters is None:
            limiters = {}
            request.app.state.route_limiters = limiters
        if name not in limiters:
            limiters[name] = RateLimiter(limit)
        return limiters[name]


def _agent_settings(request: Request, who: str) -> Settings:
    """The settings an agent route runs with. Over the per-person limit (`agent_rate_per_10_min`)
    the model is not called and the answer is assembled without one, exactly as with the agent
    off (`fallback_disabled`): there is always an answer, and a loop cannot run up a bill."""
    settings: Settings = request.app.state.settings
    if not settings.llm_enabled:
        return settings
    if _limiter(request, "agent", settings.agent_rate_per_10_min).allow(who):
        return settings
    logger.info("agent_rate_limited")
    return settings.model_copy(update={"llm_enabled": False})


def check_reader(request: Request, person_id: str, current_user: CurrentUser) -> None:
    """A senior reads only themselves; a family member only the senior whose group they are an
    active member of. 404, not 403, so the answer does not say whether the person exists. Nothing
    is checked when sign-in is off, as for every other route."""
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return
    if current_user.role is AuthRole.SENIOR:
        allowed = current_user.person_id == person_id
    else:
        allowed = _calendar(request).is_active_member_for_person(current_user.sub, person_id)
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")


def reset_demo_family(application: FastAPI) -> None:
    """Sign-in off only: Mdm Lim's demo family and schedule as they start, relative to today."""
    store: FamilyCalendarStore | None = getattr(application.state, "family_calendar", None)
    family: FamilyGroups | None = getattr(application.state, "family", None)
    if store is None or family is None:
        return
    family.ensure_demo_group()
    store.reset_demo(
        DEMO_PERSON_ID,
        _today(),
        {sub: relationship for sub, (_, relationship) in DEMO_FAMILY.items()},
    )


def register_family_routes(application: FastAPI) -> None:
    @application.get("/v1/me", response_model=MeResponse, tags=["family"], responses={401: {}})
    def me(request: Request, identity: SignedIn) -> MeResponse:
        """Who is signed in, which seniors they care for, and whether they still have to choose
        `senior` or `family`."""
        family = _family(request)
        person_id = (
            request.app.state.repository.lookup_person_for_sub(identity.sub)
            if identity.role is AuthRole.SENIOR
            else None
        )
        return family.me(identity.sub, identity.role, person_id)

    @application.post(
        "/v1/me/onboard",
        response_model=MeResponse,
        tags=["family"],
        responses={401: {}, 409: {}},
    )
    def onboard(request: Request, body: OnboardRequest, identity: SignedIn) -> MeResponse:
        """Choose once, right after signing up: `senior` (gets their own record, with synthetic
        activity data until a real device is connected) or `family`."""
        family = _family(request)
        return _call(
            lambda: family.onboard(identity.sub, identity.token_role, body.role, body.display_name)
        )

    @application.post(
        "/v1/me/link-pin",
        response_model=PinResponse,
        tags=["family"],
        responses={401: {}, 403: {}},
    )
    def link_pin(request: Request, current_user: Senior) -> PinResponse:
        """A senior's 10-minute, single-use PIN. Giving it to a family member lets them link the
        senior to their family group; asking again replaces the previous one."""
        family = _family(request)
        person_id = current_user.person_id or ""
        return _call(lambda: family.create_link_pin(current_user.sub, person_id))

    @application.post(
        "/v1/groups",
        response_model=CareGroup,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={400: {}, 401: {}, 403: {}, 409: {}, 429: {}},
    )
    def create_group(request: Request, body: CreateGroupRequest, current_user: Family) -> CareGroup:
        """Create a family group; the caller becomes its owner. With only `senior_name` the group
        starts with no senior linked (`person_id` is null) until an active member enters the
        senior's PIN (`link-senior`). With `senior_pin` the senior is linked at once and their own
        account name is shown. A senior can only have one group."""
        family = _family(request)
        return _call(
            lambda: family.create_group(
                current_user.sub,
                body.relationship,
                senior_name=body.senior_name,
                senior_pin=body.senior_pin,
            )
        )

    @application.post(
        "/v1/groups/join",
        response_model=MyGroup,
        tags=["family"],
        responses={400: {}, 401: {}, 403: {}, 409: {}, 429: {}},
    )
    def join_group(request: Request, body: JoinGroupRequest, current_user: Family) -> MyGroup:
        """Ask to join with a group's join PIN. The caller waits as `pending` until an active
        member approves them."""
        family = _family(request)
        return _call(lambda: family.join_group(current_user.sub, body.pin, body.relationship))

    @application.get(
        "/v1/groups/{group_id}",
        response_model=CareGroup,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def get_group(request: Request, group_id: str, current_user: Family) -> CareGroup:
        """The group and its members, including people waiting for approval. Active members only."""
        family = _family(request)
        return _call(lambda: family.group(current_user.sub, group_id))

    @application.post(
        "/v1/groups/{group_id}/open",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 404: {}},
    )
    def open_group(request: Request, group_id: str, identity: SignedIn) -> Response:
        """Make this the caller's current group, as `last_opened` on `GET /v1/me` reports. Active
        members only: anyone else, a senior included, gets 404, so `SignedIn` rather than
        `Family`, whose 403 would answer a senior differently. Adds nothing to the family feed."""
        if identity.role is AuthRole.SENIOR:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
        family = _family(request)
        _call(lambda: family.open_group(identity.sub, group_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/link-senior",
        response_model=CareGroup,
        tags=["family"],
        responses={400: {}, 401: {}, 403: {}, 404: {}, 409: {}, 429: {}},
    )
    def link_senior(
        request: Request, group_id: str, body: LinkSeniorRequest, current_user: Family
    ) -> CareGroup:
        """Link the senior to this group with the PIN on their screen; showing it is their
        agreement. Active members only. Refused (409) when the group already has a senior or the
        senior already has a group; a refusal leaves the PIN usable."""
        family = _family(request)
        return _call(lambda: family.link_senior(current_user.sub, group_id, body.senior_pin))

    @application.put(
        "/v1/groups/{group_id}/senior-name",
        response_model=CareGroup,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def rename_senior(
        request: Request, group_id: str, body: SeniorNameRequest, current_user: Family
    ) -> CareGroup:
        """Fix the senior's name while no senior is linked. Once linked the name comes from the
        senior's own account (409). Active members only."""
        family = _family(request)
        return _call(lambda: family.rename_senior(current_user.sub, group_id, body.senior_name))

    @application.post(
        "/v1/groups/{group_id}/join-pin",
        response_model=PinResponse,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def join_pin(request: Request, group_id: str, current_user: Family) -> PinResponse:
        """A new 7-day join PIN for this group, replacing the previous one. Active members only."""
        family = _family(request)
        return _call(lambda: family.create_join_pin(current_user.sub, group_id))

    @application.post(
        "/v1/groups/{group_id}/members/{member_id}/approve",
        response_model=CareGroup,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def approve_member(
        request: Request, group_id: str, member_id: str, current_user: Family
    ) -> CareGroup:
        """Let a pending member in. Any active member can approve."""
        family = _family(request)
        return _call(lambda: family.approve(current_user.sub, group_id, member_id))

    @application.post(
        "/v1/groups/{group_id}/members/{member_id}/decline",
        response_model=CareGroup,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def decline_member(
        request: Request, group_id: str, member_id: str, current_user: Family
    ) -> CareGroup:
        """Turn a pending request down. They can ask again with a valid join PIN."""
        family = _family(request)
        return _call(lambda: family.decline(current_user.sub, group_id, member_id))

    # ── Family calendar ───────────────────────────────────────────────────────

    @application.get(
        "/v1/people/{person_id}/calendar",
        response_model=FamilyCalendar,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def person_calendar(
        request: Request,
        person_id: str,
        current_user: PersonReader,
        from_date: Annotated[date | None, Query()] = None,
        to_date: Annotated[date | None, Query()] = None,
    ) -> FamilyCalendar:
        """The senior's appointments (repeating ones as each day), the family's availability and
        who is going along, from `from_date` to `to_date` (default: two months back, six ahead)."""
        check_reader(request, person_id, current_user)
        today = _today()
        lo = from_date or today - timedelta(days=60)
        hi = to_date or today + timedelta(days=183)
        store = _calendar(request)
        return _call(lambda: store.calendar(person_id, current_user.sub, lo, hi))

    @application.get(
        "/v1/groups/{group_id}/calendar",
        response_model=FamilyCalendar,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def group_calendar(
        request: Request,
        group_id: str,
        current_user: Family,
        from_date: Annotated[date | None, Query()] = None,
        to_date: Annotated[date | None, Query()] = None,
    ) -> FamilyCalendar:
        """The family group's calendar, as the senior's calendar above, also before its senior is
        linked (then `person_id` is null). Active members only; the senior reads their own."""
        today = _today()
        lo = from_date or today - timedelta(days=60)
        hi = to_date or today + timedelta(days=183)
        store = _calendar(request)
        return _call(lambda: store.group_calendar(current_user.sub, group_id, lo, hi))

    @application.post(
        "/v1/groups/{group_id}/appointments/draft",
        response_model=AppointmentDraft,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def draft_group_appointment(
        request: Request, group_id: str, body: AppointmentDraftRequest, current_user: Family
    ) -> AppointmentDraft:
        """Fill in the appointment form from what the member typed. Saves nothing: the member
        checks the form and adds it with `POST /appointments`. Written by the typed-appointment
        agent when it is on and approved by a deterministic check, else by a plain parser. Active
        members only."""
        context = _call(
            lambda: build_draft_context(
                _calendar(request), current_user.sub, group_id, body.text, _today()
            )
        )
        return draft_appointment(context, _agent_settings(request, current_user.sub))

    @application.post(
        "/v1/groups/{group_id}/appointments",
        response_model=Appointment,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def create_appointment(
        request: Request, group_id: str, body: AppointmentRequest, current_user: Family
    ) -> Appointment:
        """Add an appointment, once or repeating. Any active member can."""
        store = _calendar(request)
        return _call(lambda: store.create_appointment(current_user.sub, group_id, body))

    @application.put(
        "/v1/groups/{group_id}/appointments/{appointment_id}",
        response_model=Appointment,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def update_appointment(
        request: Request,
        group_id: str,
        appointment_id: str,
        body: AppointmentRequest,
        current_user: Family,
    ) -> Appointment:
        """Change an appointment (every day of it, if it repeats)."""
        store = _calendar(request)
        return _call(
            lambda: store.update_appointment(current_user.sub, group_id, appointment_id, body)
        )

    @application.post(
        "/v1/groups/{group_id}/appointments/{appointment_id}/delete",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def delete_appointment(
        request: Request, group_id: str, appointment_id: str, current_user: Family
    ) -> Response:
        """Remove an appointment (every day of it), with its answers and helpers."""
        store = _calendar(request)
        _call(lambda: store.delete_appointment(current_user.sub, group_id, appointment_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/availability",
        response_model=AvailabilityEntryOut,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def add_availability(
        request: Request, group_id: str, body: AvailabilityRequest, current_user: Family
    ) -> AvailabilityEntryOut:
        """Share a time you are free (or busy), whatever is on the calendar."""
        store = _calendar(request)
        return _call(lambda: store.add_window(current_user.sub, group_id, body))

    @application.post(
        "/v1/groups/{group_id}/availability/{entry_id}/delete",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def remove_availability(
        request: Request, group_id: str, entry_id: str, current_user: Family
    ) -> Response:
        """Take back one of your own shared times."""
        store = _calendar(request)
        _call(lambda: store.remove_entry(current_user.sub, group_id, entry_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/answers",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def answer_occurrence(
        request: Request, group_id: str, body: OccurrenceAnswerRequest, current_user: Family
    ) -> Response:
        """Available or not for one day of an appointment. Not available also steps you back."""
        store = _calendar(request)
        _call(lambda: store.answer(current_user.sub, group_id, body.occurrence_id, body.status))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/helpers",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def volunteer(
        request: Request, group_id: str, body: OccurrenceRequest, current_user: Family
    ) -> Response:
        """Help with one day of an appointment (and so also be available for it)."""
        store = _calendar(request)
        _call(lambda: store.volunteer(current_user.sub, group_id, body.occurrence_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/helpers/step-back",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def step_back(
        request: Request, group_id: str, body: OccurrenceRequest, current_user: Family
    ) -> Response:
        """Stop helping with one day of an appointment. Your availability answer is kept."""
        store = _calendar(request)
        _call(lambda: store.step_back(current_user.sub, group_id, body.occurrence_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ── Family activity feed and check-ins ────────────────────────────────────

    @application.get(
        "/v1/groups/{group_id}/activity",
        response_model=FamilyActivityPage,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def group_activity(
        request: Request,
        group_id: str,
        current_user: Family,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        before: Annotated[str | None, Query(max_length=64)] = None,
    ) -> FamilyActivityPage:
        """What the family has done in the group, newest first. `before` is the `next_before` of
        the previous page. Active members only; the senior never reads it."""
        store = _calendar(request)
        return _call(lambda: store.activity(current_user.sub, group_id, limit, before))

    @application.get(
        "/v1/groups/{group_id}/catch-up",
        response_model=CatchUp,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def group_catch_up(
        request: Request,
        group_id: str,
        current_user: Family,
        since: Annotated[datetime | None, Query()] = None,
    ) -> CatchUp:
        """ "Since you last visited": what changed in the group after `since`, what still needs
        someone, and today's tasks, written by the catch-up agent when it is on and approved by a
        deterministic check, else assembled without a model. Reads only what the feed, calendar
        and task list already show this member. Active members only; the senior never reads it."""
        context = _call(
            lambda: build_catch_up_context(
                _calendar(request), _tasks(request), current_user.sub, group_id, since, _today()
            )
        )
        return catch_up(context, _agent_settings(request, current_user.sub))

    @application.post(
        "/v1/groups/{group_id}/check-ins",
        response_model=FamilyActivityEntry,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def create_check_in(
        request: Request, group_id: str, body: CheckInRequest, current_user: Family
    ) -> FamilyActivityEntry:
        """Tell the group you called, visited or messaged the senior, with an optional note for the
        group. Nothing is sent to the senior."""
        store = _calendar(request)
        return _call(lambda: store.check_in(current_user.sub, group_id, body))

    # ── Asks and notifications ────────────────────────────────────────────────

    @application.post(
        "/v1/groups/{group_id}/asks",
        response_model=HelperAsk,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def create_ask(
        request: Request, group_id: str, body: HelperAskRequest, current_user: Family
    ) -> HelperAsk:
        """Ask an active member, by name, to take one day of an appointment that needs a helper.
        They get a notification. 422 for yourself, someone not active in the group, a current
        helper, a day that has started or no longer needs a helper; 409 when someone has already
        been asked for that day."""
        store = _calendar(request)
        return _call(lambda: store.create_ask(current_user.sub, group_id, body))

    @application.get(
        "/v1/groups/{group_id}/asks",
        response_model=HelperAskList,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def list_asks(
        request: Request,
        group_id: str,
        current_user: Family,
        state: Annotated[Literal["open"], Query()] = "open",
    ) -> HelperAskList:
        """The group's open asks (asks whose day has started lapse first). Active members only."""
        store = _calendar(request)
        return _call(lambda: store.open_asks(current_user.sub, group_id))

    @application.post(
        "/v1/groups/{group_id}/asks/{ask_id}/accept",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def accept_ask(request: Request, group_id: str, ask_id: str, current_user: Family) -> Response:
        """The asked member says yes and becomes the helper for that day; the asker is told."""
        store = _calendar(request)
        _call(lambda: store.accept_ask(current_user.sub, group_id, ask_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/asks/{ask_id}/decline",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def decline_ask(request: Request, group_id: str, ask_id: str, current_user: Family) -> Response:
        """The asked member says no; the day needs a helper again and the asker is told."""
        store = _calendar(request)
        _call(lambda: store.decline_ask(current_user.sub, group_id, ask_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post(
        "/v1/groups/{group_id}/asks/{ask_id}/withdraw",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def withdraw_ask(
        request: Request, group_id: str, ask_id: str, current_user: Family
    ) -> Response:
        """The asker takes the ask back; the asked member is told."""
        store = _calendar(request)
        _call(lambda: store.withdraw_ask(current_user.sub, group_id, ask_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get(
        "/v1/me/notifications",
        response_model=NotificationPage,
        tags=["family"],
        responses={401: {}, 403: {}, 422: {}},
    )
    def my_notifications(
        request: Request,
        current_user: Family,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        before: Annotated[str | None, Query(max_length=64)] = None,
    ) -> NotificationPage:
        """The caller's notifications across their family groups, newest first, with the unread
        count. `before` is the `next_before` of the previous page. Never for the senior."""
        store = _calendar(request)
        return _call(lambda: store.notifications(current_user.sub, limit, before))

    @application.post(
        "/v1/me/notifications/read",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 422: {}},
    )
    def read_notifications(
        request: Request, body: NotificationReadRequest, current_user: Family
    ) -> Response:
        """Mark your notifications read: the ones named, or `all`. Other ids are ignored."""
        store = _calendar(request)
        _call(lambda: store.mark_notifications_read(current_user.sub, body))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ── Appointment notes ─────────────────────────────────────────────────────

    @application.get(
        "/v1/groups/{group_id}/appointments/{appointment_id}/notes",
        response_model=list[AppointmentNote],
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def list_appointment_notes(
        request: Request,
        group_id: str,
        appointment_id: str,
        current_user: Family,
        on_date: Annotated[date, Query(alias="date")],
    ) -> list[AppointmentNote]:
        """The family's notes on one day of an appointment, oldest first (at most 100). Active
        members only; the senior never reads them."""
        store = _calendar(request)
        return _call(lambda: store.list_notes(current_user.sub, group_id, appointment_id, on_date))

    @application.post(
        "/v1/groups/{group_id}/appointments/{appointment_id}/notes",
        response_model=AppointmentNote,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def add_appointment_note(
        request: Request,
        group_id: str,
        appointment_id: str,
        body: AppointmentNoteRequest,
        current_user: Family,
    ) -> AppointmentNote:
        """Add a note to one day of an appointment, for the group only. The feed records that a
        note was added, not what it said."""
        store = _calendar(request)
        return _call(lambda: store.add_note(current_user.sub, group_id, appointment_id, body))

    @application.post(
        "/v1/groups/{group_id}/notes/{note_id}/delete",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def delete_appointment_note(
        request: Request, group_id: str, note_id: str, current_user: Family
    ) -> Response:
        """Remove one of your own notes. Its feed entry stays."""
        store = _calendar(request)
        _call(lambda: store.delete_note(current_user.sub, group_id, note_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ── Tasks ─────────────────────────────────────────────────────────────────

    @application.get(
        "/v1/groups/{group_id}/tasks",
        response_model=TaskList,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def group_tasks(
        request: Request,
        group_id: str,
        current_user: Family,
        from_date: Annotated[date | None, Query()] = None,
        to_date: Annotated[date | None, Query()] = None,
    ) -> TaskList:
        """The family group's tasks and the days ticked off from `from_date` to `to_date` (default:
        two months back, six ahead), also before its senior is linked. Active members only."""
        today = _today()
        lo = from_date or today - timedelta(days=60)
        hi = to_date or today + timedelta(days=183)
        store = _tasks(request)
        return _call(lambda: store.group_tasks(current_user.sub, group_id, lo, hi))

    @application.get(
        "/v1/people/{person_id}/tasks",
        response_model=TaskList,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def person_tasks(
        request: Request,
        person_id: str,
        current_user: PersonReader,
        from_date: Annotated[date | None, Query()] = None,
        to_date: Annotated[date | None, Query()] = None,
    ) -> TaskList:
        """The senior's tasks, as the group's above. The senior reads their own; a family member
        the senior whose group they are an active member of."""
        check_reader(request, person_id, current_user)
        today = _today()
        lo = from_date or today - timedelta(days=60)
        hi = to_date or today + timedelta(days=183)
        store = _tasks(request)
        return _call(lambda: store.person_tasks(person_id, lo, hi))

    @application.get(
        "/v1/people/{person_id}/my-day",
        response_model=MyDay,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def person_my_day(request: Request, person_id: str, current_user: PersonReader) -> MyDay:
        """ "Read my day": a short script of today's appointments and reminders and tomorrow's
        first appointment, for the browser to read aloud. Written by the "Read my day" agent when
        it is on and approved by a deterministic check, else assembled without a model. Reads only
        what the senior's calendar and task list already show; the same readers as those."""
        check_reader(request, person_id, current_user)
        now = datetime.now(UTC)
        context = _call(
            lambda: build_my_day_context(
                _calendar(request), _tasks(request), person_id, current_user.sub, _today(), now
            )
        )
        return my_day(context, _agent_settings(request, current_user.sub))

    @application.get(
        "/v1/people/{person_id}/my-day/voice",
        response_model=SpeechVoice,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def person_my_day_voice(
        request: Request, person_id: str, current_user: PersonReader
    ) -> SpeechVoice:
        """Whether "Read my day" can speak with the Kokoro voice here (it loads the model the first
        time, so the first reading does not wait). The same readers as `my-day`."""
        check_reader(request, person_id, current_user)
        settings = request.app.state.settings
        if unavailable_reason(settings) is not None:
            return SpeechVoice(available=False, voice=None, label=None)
        return SpeechVoice(
            available=True,
            voice=settings.tts_voice,
            label=voice_label(settings.tts_voice),
            voices=[SpeechVoiceOption(voice=voice, label=voice_label(voice)) for voice in VOICES],
        )

    @application.post(
        "/v1/people/{person_id}/my-day/speech",
        response_class=Response,
        tags=["family"],
        responses={
            200: {"content": {"audio/wav": {}}, "description": "The sentence, spoken (WAV)."},
            401: {},
            403: {},
            404: {},
            422: {},
            429: {"description": "Too many sentences from this person in 10 minutes."},
            503: {"description": "The Kokoro voice is not installed, busy, or could not speak."},
        },
    )
    def person_my_day_speech(
        request: Request, person_id: str, body: SpeechRequest, current_user: PersonReader
    ) -> Response:
        """One sentence of "Read my day", spoken by the Kokoro voice on this server's CPU (no
        cloud service). The same readers as `my-day`. 429 past `tts_rate_per_10_min` sentences
        a person in 10 minutes. 503 when Kokoro or its model files are not installed, it failed,
        or it is busy with another sentence for longer than `tts_busy_wait_seconds`: the browser
        then reads with its own voice."""
        check_reader(request, person_id, current_user)
        settings = request.app.state.settings
        if body.voice is not None and body.voice not in VOICES and body.voice != settings.tts_voice:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown voice.")
        if not _limiter(request, "tts", settings.tts_rate_per_10_min).allow(current_user.sub):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many sentences. Try again later."
            )
        try:
            audio = speak(body.text, settings, body.voice)
        except SpeechBusy as error:
            # Busy is a moment's wait, not "cannot speak": `code` (and `Retry-After`) let the
            # browser ask for this sentence again instead of dropping the Kokoro voice.
            return JSONResponse(
                {"code": SPEECH_BUSY_CODE, "detail": str(error)},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "1"},
            )
        except SpeechUnavailable as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
        # Private: the audio is one person's day. The browser may keep it for this session.
        return Response(
            audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"}
        )

    @application.post(
        "/v1/groups/{group_id}/tasks",
        response_model=Task,
        status_code=status.HTTP_201_CREATED,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def create_task(
        request: Request, group_id: str, body: TaskRequest, current_user: Family
    ) -> Task:
        """Add a task, once or repeating. Any active member can; the senior cannot."""
        store = _tasks(request)
        return _call(lambda: store.create_task(current_user.sub, group_id, body))

    @application.put(
        "/v1/groups/{group_id}/tasks/{task_id}",
        response_model=Task,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def update_task(
        request: Request, group_id: str, task_id: str, body: TaskRequest, current_user: Family
    ) -> Task:
        """Change a task (every day of it, if it repeats). Days already ticked off stay ticked."""
        store = _tasks(request)
        return _call(lambda: store.update_task(current_user.sub, group_id, task_id, body))

    @application.post(
        "/v1/groups/{group_id}/tasks/{task_id}/delete",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def delete_task(
        request: Request, group_id: str, task_id: str, current_user: Family
    ) -> Response:
        """Remove a task (every day of it) and its ticks."""
        store = _tasks(request)
        _call(lambda: store.delete_task(current_user.sub, group_id, task_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.put(
        "/v1/groups/{group_id}/tasks/{task_id}/days/{day}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def set_group_task_day(
        request: Request,
        group_id: str,
        task_id: str,
        day: date,
        body: TaskDayRequest,
        current_user: Family,
    ) -> Response:
        """Tick one day of a task done, or not done. Today or a past day; never a future one."""
        store = _tasks(request)
        _call(
            lambda: store.set_group_day(
                current_user.sub, group_id, task_id, day, body.done, _today()
            )
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.put(
        "/v1/people/{person_id}/tasks/{task_id}/days/{day}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def set_person_task_day(
        request: Request,
        person_id: str,
        task_id: str,
        day: date,
        body: TaskDayRequest,
        current_user: PersonReader,
    ) -> Response:
        """The senior ticks one of today's tasks done, or not done. Today only."""
        check_reader(request, person_id, current_user)
        store = _tasks(request)
        _call(
            lambda: store.set_person_day(
                current_user.sub, person_id, task_id, day, body.done, _today()
            )
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # ── The senior's watch ────────────────────────────────────────────────────

    @application.get(
        "/v1/people/{person_id}/wearable",
        response_model=WearableStatus,
        tags=["family"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def person_wearable(
        request: Request, person_id: str, current_user: PersonReader
    ) -> WearableStatus:
        """The senior's watch: connected or not, last sync and battery, so the family can remind
        them to charge it. Simulated until a real device is connected (`source` says so)."""
        check_reader(request, person_id, current_user)
        try:
            readings = request.app.state.repository.daily_metrics(person_id=person_id, days=1)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found") from exc
        latest = readings[-1] if readings else None
        return simulated_wearable(
            person_id,
            bool(readings),
            datetime.now(UTC),
            latest.day if latest else None,
            readings_synthetic=latest is not None and latest.source == "synthetic",
        )
