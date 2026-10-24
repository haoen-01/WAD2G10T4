"""HTTP routes for accounts, family groups and the family calendar. The rules live in
`silverloop.family_groups` and `silverloop.family_calendar`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response, status

from silverloop.auth import Family, PersonReader, Senior, SignedIn
from silverloop.config import Settings
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_groups import DEMO_FAMILY, FamilyGroupError, FamilyGroups
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import (
    Appointment,
    AppointmentRequest,
    AuthRole,
    AvailabilityEntryOut,
    AvailabilityRequest,
    CareGroup,
    CheckInRequest,
    CreateGroupRequest,
    CurrentUser,
    FamilyActivityEntry,
    FamilyActivityPage,
    FamilyCalendar,
    JoinGroupRequest,
    MeResponse,
    MyGroup,
    OccurrenceAnswerRequest,
    OccurrenceRequest,
    OnboardRequest,
    PinResponse,
    WearableStatus,
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


def _call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except FamilyGroupError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def _today() -> date:
    return local_date(datetime.now(UTC))


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
        """A senior's 15-minute, single-use PIN. Giving it to a family member lets them create the
        senior's family group; asking again replaces the previous one."""
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
        """Create a senior's family group with the PIN on the senior's screen. The caller becomes
        its owner. A senior can only have one group."""
        family = _family(request)
        return _call(
            lambda: family.create_group(current_user.sub, body.senior_pin, body.relationship)
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
        return simulated_wearable(person_id, bool(readings), datetime.now(UTC))
