from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from silverloop.analytics import ACTIVITY_RELATIVE_DEFAULT_DAYS, ACTIVITY_RELATIVE_MAX_DAYS
from silverloop.auth import (
    AnyUser,
    Coordinator,
    DemoOperator,
    PersonReader,
    Senior,
    require_any_authenticated,
)
from silverloop.config import Settings, get_settings
from silverloop.context import ExternalContextProvider
from silverloop.error_responses import SERVER_ERROR_RESPONSES, register_server_error_handlers
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_groups import FamilyGroups
from silverloop.family_routes import check_reader, register_family_routes, reset_demo_family
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.logging_config import request_id_var, request_logger
from silverloop.migrations import apply_rls_posture, upgrade_database
from silverloop.models import (
    ActivityCandidate,
    ActivityGoal,
    ActivityGoalRequest,
    ActivityPreferences,
    ActivityQueryRequest,
    ActivityQueryResponse,
    ActivityRelativeToUsual,
    ActivityResponseRequest,
    ActivityResponseResponse,
    AdvanceRequest,
    AdvanceResponse,
    AuditEvent,
    AuthRole,
    BaselineConfirmationRequest,
    BaselineConfirmationResponse,
    CandidatePreference,
    CandidatePreferenceRequest,
    CandidatePreferenceResponse,
    CarePriorityBoard,
    CaseReviewResponse,
    CaseStatus,
    ConsentRequest,
    ConsentResponse,
    ContextAnswerRequest,
    ContextAnswerResponse,
    CoordinatorFleetMetrics,
    CoordinatorPersonRow,
    CurrentUser,
    DailyMetric,
    DayDisputeRequest,
    DayDisputeResponse,
    DemoResetResponse,
    EnjoymentRequest,
    EnjoymentResponse,
    FollowThroughRequest,
    FollowThroughResponse,
    FollowUpObservation,
    HealthResponse,
    Intervention,
    MemoryDecisionRequest,
    MemoryDecisionResponse,
    OperationalMetrics,
    OutcomeRequest,
    OutcomeResponse,
    OutreachDetail,
    OutreachSummary,
    PersonState,
    PersonWorldModel,
    PlanActivityRequest,
    PlannedEnjoymentRequest,
    PlannedEnjoymentResponse,
    PlannedFollowThroughRequest,
    PlannedFollowThroughResponse,
    PreferenceDimension,
    PreferenceStatementRequest,
    PreferenceStatementResponse,
    Programme,
    ProposedMemory,
    RankerInspectRequest,
    RankerInspectResponse,
    RankerPresetsResponse,
    ReadinessResponse,
    ReplacePlannedActivityRequest,
    ReplanNotice,
    ReplanOffer,
    ReviewCase,
    ReviewRequest,
    ReviewThresholdApproveRequest,
    ReviewThresholdDecisionResponse,
    ReviewThresholdManualSetRequest,
    ReviewThresholdRejectRequest,
    ReviewThresholdReplay,
    ReviewThresholdShownRequest,
    ReviewThresholdState,
    ReviewThresholdValue,
    SeniorHomePreview,
    SimulationHistoryEntry,
    WeekPlan,
)
from silverloop.ranker_inspector import (
    RankerInspectorDefect,
    RankerPersonNotFound,
    RankerRequestError,
)
from silverloop.repository import SilverLoopRepository
from silverloop.review_threshold import (
    MAX_PERSISTENCE_DAYS,
    MAX_SEVERITY_PCT,
    MIN_PERSISTENCE_DAYS,
    MIN_SEVERITY_PCT,
    SEVERITY_STEP_PCT,
)
from silverloop.runtime import validate_runtime
from silverloop.sql_repository import (
    ReviewThresholdConflict,
    ReviewThresholdNotFound,
    SqlAlchemyRepository,
    StaleRunConflict,
)
from silverloop.triage import DEFAULT_TOP_K, MAX_TOP_K

SENIOR_HOME_PREVIEW_DISCLOSURE = (
    "Preview for evaluation. This is not the senior's own screen; nothing here can be answered or "
    "recorded."
)


def resets_demo_family_on_start(config: Settings, repository: object) -> bool:
    """Only a local SQLite run with sign-in off starts with the demo family put back. On a server
    database that reset would wipe the family data on every start, whoever it belongs to."""
    engine = getattr(repository, "engine", None)
    return (
        not config.auth_enabled and engine is not None and engine.url.get_backend_name() == "sqlite"
    )


def create_app(
    repository: SilverLoopRepository | None = None,
    *,
    settings: Settings | None = None,
    migrate_on_start: bool = True,
) -> FastAPI:
    config = settings or get_settings()
    # Live context must never be required: force-disabled under the offline profile (no network
    # in the offline demo / Playwright) regardless of `external_context_enabled`.
    context_provider = (
        ExternalContextProvider(
            country_code=config.external_context_country,
            timeout_seconds=config.external_context_timeout_seconds,
        )
        if config.external_context_enabled and config.silverloop_runtime_profile != "offline"
        else None
    )
    persistent_repository = repository or SqlAlchemyRepository(
        config.database_url,
        seed=config.demo_seed,
        scenario_version=config.demo_scenario_version,
        context_provider=context_provider,
        # The repository needs the resolved config so the outreach planner honours this app's
        # settings rather than re-reading process defaults.
        settings=config,
    )

    # Family groups share the repository's database. A repository without one (a test double)
    # simply has no family routes behind it: they answer 503.
    sessions = getattr(persistent_repository, "sessions", None)
    family_groups = FamilyGroups(sessions, persistent_repository) if sessions is not None else None
    family_calendar = FamilyCalendarStore(sessions) if sessions is not None else None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        validate_runtime(config)
        if migrate_on_start:
            upgrade_database(config.database_url)
            # Immediately after, never before: the posture has to cover the tables the upgrade
            # just created. On Supabase those arrive already granted to `anon`/`authenticated`
            # by `ALTER DEFAULT PRIVILEGES`, so until this ran on every start the deny policy
            # waited on someone remembering to paste a SQL file (docs/supabase.md records three
            # occasions when nobody did). No-op off PostgreSQL; failures are reported through
            # `/ready`'s `tables_without_rls` rather than by refusing to start.
            apply_rls_posture(config.database_url)
        persistent_repository.ensure_active_run()
        if family_groups is not None and resets_demo_family_on_start(config, persistent_repository):
            # Sign-in off: a demo family member already in Mdm Lim's group (family_groups.py).
            family_groups.ensure_demo_group()
            reset_demo_family(application)
        yield

    security_schemes: dict = {}
    if True:  # always document bearer auth
        security_schemes["BearerAuth"] = {"type": "http", "scheme": "bearer"}

    application = FastAPI(
        title="Care+ API",
        version="0.2.0",
        description=(
            "Deterministic, synthetic active-ageing orchestration. "
            "Not a medical, diagnostic, emergency or surveillance system."
        ),
        lifespan=lifespan,
        # Every route can end in a classified server error (`error_responses`); declaring it here
        # puts `ServerErrorBody` and its `code` enum in the contract for all of them.
        responses=SERVER_ERROR_RESPONSES,
    )
    application.state.repository = persistent_repository
    application.state.settings = config
    application.state.family = family_groups
    application.state.family_calendar = family_calendar
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )
    logger = request_logger()

    @application.middleware("http")
    async def structured_request_log(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex[:16]}"
        started = perf_counter()
        status_code = 500
        # Published so code far below the route handler -- the planner's provider-failure log --
        # can correlate its own lines with this request without threading an id through the
        # repository.
        request_id_token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            request_id_var.reset(request_id_token)
            logger.info(
                "request_completed",
                extra={
                    "structured_fields": {
                        "request_id": request_id,
                        "method": request.method,
                        # The route template, never the concrete path: a path segment can carry
                        # a person's own words (a stated preference value) and a log is an
                        # operator surface.
                        "path": _route_template(request),
                        "status_code": status_code,
                        "duration_ms": round((perf_counter() - started) * 1000, 2),
                    }
                },
            )

    register_routes(application)
    register_family_routes(application)
    register_exception_handlers(application)
    register_server_error_handlers(application)
    return application


def get_repository(request: Request) -> SilverLoopRepository:
    return request.app.state.repository


Repository = Annotated[SilverLoopRepository, Depends(get_repository)]


# ── App-level fallback exception handlers ─────────────────────────────────────
#
# `SqlAlchemyRepository._active_run` is on the hot path of nearly every route below it: it is
# how a repository call resolves "does this person exist, and are they seeded for this run at
# all". It raises `KeyError(person_id)` for the first question and `RuntimeError(...)` for the
# second, and until now most routes only caught the first. A handful had no try/except at all.
# The result was a bare 500 for something as ordinary as a typo'd person_id in a URL, or a person
# who exists but has never been reset -- see `GET /v1/people/{id}/week` and `/goals` in the audit
# this fixes.
#
# Registering handlers here, once, is deliberately preferred over auditing and patching every
# route: it can't miss a route the next person adds, and it does not touch the routes that
# already have a more specific local `except KeyError`/`except ValueError` -- those still run
# first and still produce their own, more specific message. These are a safety net underneath
# them, not a replacement.
_UNINITIALIZED_RUN_MESSAGE_PREFIXES = (
    # Raised by `_active_run` for a person who exists but has no active scenario run -- i.e. has
    # never been through `/v1/demo/reset` (or the equivalent seed step) for this database.
    "No active scenario run",
    # Raised by `_load_metrics` for a run that exists but was never given wearable data -- the
    # same "not properly seeded" family, just caught a step later.
    "Active scenario contains no wearable metrics",
)


def _is_uninitialized_run_error(exc: RuntimeError) -> bool:
    """Narrowly identify the two known "this person was never seeded" `RuntimeError`s.

    A blanket `RuntimeError -> 409` mapping would launder a genuine internal error into a status
    that tells an operator "just seed the person", which is actively misleading. Repo-wide, only
    `_active_run` and `_load_metrics` raise `RuntimeError` on any path a route can reach (every
    LLM/provider failure in `agent/` is caught and degraded internally, never propagated as
    `RuntimeError`) -- so matching their exact, stable message prefixes is a reliable way to
    identify this one family without guessing at every other `RuntimeError` that could ever be
    added later.
    """
    message = str(exc)
    return any(message.startswith(prefix) for prefix in _UNINITIALIZED_RUN_MESSAGE_PREFIXES)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else "<unmatched>"


# `GET /v1/coordinator/queue` hygiene (audit-H finding 8): a resolved case never interleaves with
# an open/acknowledged one on screen, and the default view never has to be told to hide it. This
# is a route-local, in-memory filter/sort over `repository.list_cases()` -- no change to that
# method's own signature or default (still "every case", used as-is by every existing caller).
_QUEUE_STATUS_RANK: dict[CaseStatus, int] = {
    CaseStatus.OPEN: 0,
    CaseStatus.ACKNOWLEDGED: 1,
    CaseStatus.RESOLVED: 2,
}

# The default when `?status=` is omitted: active cases only. A resolved case is still reachable,
# on request, via `?status=resolved` (or `?status=open,acknowledged,resolved` for everything).
_DEFAULT_QUEUE_STATUSES = frozenset({CaseStatus.OPEN, CaseStatus.ACKNOWLEDGED})

# The actor recorded when the Simulator's demo script records a review or approval to skip a
# chapter. Deliberately not "system": that reviewer means a system closure (`review_lessons`).
DEMO_SCRIPT_ACTOR = "demo-script"
DEMO_SCRIPT_SIGN_IN_ON_MESSAGE = "Demo script actions are only available with sign-in off."


def _demo_script_actor(settings: Settings, recorded_by_demo_script: bool, sub: str) -> str:
    """Who a review or approval is recorded as. A demo-script action is refused (403) while
    sign-in is on: with real identities, a request must never be able to rename its own actor."""
    if not recorded_by_demo_script:
        return sub
    if settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_SCRIPT_SIGN_IN_ON_MESSAGE
        )
    return DEMO_SCRIPT_ACTOR


def _parse_queue_statuses(raw: str | None) -> frozenset[CaseStatus]:
    """Parse `?status=open,acknowledged` into the set of statuses to include.

    `None` (the parameter omitted) is `_DEFAULT_QUEUE_STATUSES`, not "everything" -- that is the
    whole point of the filter: a coordinator who never asks for `resolved` never sees one
    interleaved with an active case.
    """
    if raw is None:
        return _DEFAULT_QUEUE_STATUSES
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        return _DEFAULT_QUEUE_STATUSES
    try:
        return frozenset(CaseStatus(token) for token in tokens)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown case status in '?status=': {exc}",
        ) from exc


def _ordered_queue(cases: list[ReviewCase], statuses: frozenset[CaseStatus]) -> list[ReviewCase]:
    """Filter to `statuses`, then order open before acknowledged before resolved, newest first
    within each status. `ReviewCase.priority` is not part of the ordering: every case is opened
    with the same hard-coded value (`sql_repository.py::_create_case`), so it carries no signal to
    sort by."""
    matching = [case for case in cases if case.status in statuses]
    return sorted(
        matching, key=lambda case: (_QUEUE_STATUS_RANK[case.status], -case.opened_at.timestamp())
    )


def register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(IntegrityError)
    async def _handle_integrity_error(request: Request, exc: IntegrityError) -> Response:
        # Two taps on the same control, in flight together, race to the same unique row. The
        # first wins and the second is a conflict, not an internal error: the person's answer
        # is on record, once. Only a uniqueness violation is read that way; any other integrity
        # failure (a bad foreign key, a null where none is allowed) is a genuine defect and
        # falls through to a plain 500 rather than being reported as a double tap.
        message = str(exc.orig if exc.orig is not None else exc).lower()
        if "unique" not in message and "duplicate key" not in message:
            raise exc
        return await http_exception_handler(
            request,
            HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That answer was already recorded.",
            ),
        )

    @application.exception_handler(ReviewThresholdNotFound)
    async def _handle_review_threshold_not_found(
        request: Request, exc: ReviewThresholdNotFound
    ) -> Response:
        # A proposal or decision id that is not this person's: named, so a 404 on a
        # review-setting route is never misreported as "Person not found".
        return await http_exception_handler(
            request,
            HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)),
        )

    @application.exception_handler(KeyError)
    async def _handle_key_error(request: Request, exc: KeyError) -> Response:
        # Every route already handling `KeyError` locally (with a more specific message, e.g.
        # "Activity not found") never reaches this handler -- it only catches what nothing else
        # did. On every route we audited, the only thing left uncaught is `_active_run`'s
        # `KeyError(person_id)`, so "Person not found" is correct here, not just a generic guess.
        return await http_exception_handler(
            request,
            HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"),
        )

    @application.exception_handler(RuntimeError)
    async def _handle_runtime_error(request: Request, exc: RuntimeError) -> Response:
        if not _is_uninitialized_run_error(exc):
            # Not the known "never seeded" family: this is a genuine internal error. Re-raise so
            # it falls through to Starlette's default unhandled-exception handling (a plain 500),
            # exactly as it would have before this handler existed -- it must never become a 409.
            raise exc
        return await http_exception_handler(
            request,
            HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{exc} This person exists but is not seeded for an active run. "
                    "POST /v1/demo/reset (or run the demo seed step) before retrying."
                ),
            ),
        )

    @application.exception_handler(StaleRunConflict)
    async def _handle_stale_run_conflict(request: Request, exc: StaleRunConflict) -> Response:
        # A reset deactivated the run, or an advance moved the simulated day, between the read
        # and the run lock. Nothing was written; re-reading the person resolves it.
        return await http_exception_handler(
            request,
            HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)),
        )

    @application.exception_handler(ReviewThresholdConflict)
    async def _handle_review_threshold_conflict(
        request: Request, exc: ReviewThresholdConflict
    ) -> Response:
        # A review-setting action that was valid when the coordinator's screen was drawn but is
        # not any more: the proposal was already decided, the simulated day moved on under the
        # replay they approved against, a cooldown or the weekly proposal cap binds. Re-reading
        # the review-setting state resolves it; the request itself was well formed.
        return await http_exception_handler(
            request,
            HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)),
        )

    @application.exception_handler(ValueError)
    async def _handle_value_error(request: Request, exc: ValueError) -> Response:
        # Every domain `ValueError` in the repository is already written to be read by a human
        # (e.g. "That day is outside the week being planned ..."), matching the routes that
        # already catch `ValueError` locally and return `str(exc)` as the 422 detail. This is the
        # same behaviour for the routes that had no local catch at all.
        return await http_exception_handler(
            request,
            HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)),
        )


def register_routes(application: FastAPI) -> None:
    # ── Public system endpoints ───────────────────────────────────────────────

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health(request: Request) -> HealthResponse:
        config: Settings = request.app.state.settings
        return HealthResponse(
            status="ok",
            version="0.2.0",
            mode=config.adapter_mode,
            llm_enabled=config.llm_enabled,
        )

    @application.get("/ready", response_model=ReadinessResponse, tags=["system"])
    def readiness(request: Request, repository: Repository) -> ReadinessResponse:
        config: Settings = request.app.state.settings
        return repository.readiness(config.silverloop_runtime_profile)

    # ── Auth identity ─────────────────────────────────────────────────────────

    @application.get(
        "/v1/auth/me",
        response_model=CurrentUser,
        tags=["auth"],
        responses={401: {"description": "Missing or invalid credentials"}},
    )
    async def me(current_user: AnyUser) -> CurrentUser:
        return current_user

    # ── Metrics / Operations (coordinator + demo_operator) ────────────────────

    @application.get(
        "/v1/metrics",
        response_model=OperationalMetrics,
        tags=["system"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def metrics(
        repository: Repository,
        _: Annotated[CurrentUser, Depends(_require_metrics)],
        person_id: str | None = None,
    ) -> OperationalMetrics:
        try:
            return repository.metrics(person_id=person_id or DEMO_PERSON_ID)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    # ── Demo reset (demo_operator or auth-disabled; not in production) ────────

    @application.post("/v1/demo/reset", response_model=DemoResetResponse, tags=["demo"])
    def reset_demo(
        request: Request,
        repository: Repository,
        person_id: str | None = None,
    ) -> DemoResetResponse:
        """Start one person's story over. `person_id` defaults to the demo person; any other
        registered demo persona resets only that persona's run, and an unknown id is a 422."""
        config: Settings = request.app.state.settings
        if config.app_env == "production":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo reset is disabled in production.",
            )
        # auth_enabled=False → accept without token; auth_enabled=True → checked below
        if config.auth_enabled:
            # We must handle this synchronously; use the synchronous path
            _check_demo_operator_sync(request)
        result = repository.reset(person_id=person_id or DEMO_PERSON_ID)
        if not config.auth_enabled and (person_id or DEMO_PERSON_ID) == DEMO_PERSON_ID:
            # The demo family and its schedule start over too, relative to today.
            reset_demo_family(request.app)
        return result

    # ── Senior routes ─────────────────────────────────────────────────────────

    def check_person_scope(person_id: str, current_user: CurrentUser) -> None:
        """Bound to THIS app's settings, read the same way every other handler reads them.

        The process-wide `get_settings()` is the wrong source: an app constructed with explicit
        settings -- every auth test, and any embedded use -- would otherwise be judged against a
        configuration it is not running.
        """
        _check_person_scope(person_id, current_user, application.state.settings)

    @application.get(
        "/v1/people/{person_id}/state",
        response_model=PersonState,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_state(
        request: Request, person_id: str, repository: Repository, current_user: PersonReader
    ) -> PersonState:
        """The senior's own status, or that of the senior whose family group the caller is in."""
        check_reader(request, person_id, current_user)
        try:
            return repository.person_state(person_id=person_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    @application.get(
        "/v1/people/{person_id}/metrics",
        response_model=list[DailyMetric],
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_metrics(
        request: Request,
        person_id: str,
        repository: Repository,
        current_user: PersonReader,
        days: int = 14,
    ) -> list[DailyMetric]:
        check_reader(request, person_id, current_user)
        try:
            return repository.daily_metrics(person_id=person_id, days=days)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    @application.post(
        "/v1/people/{person_id}/consent",
        response_model=ConsentResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def update_consent(
        person_id: str,
        request: ConsentRequest,
        repository: Repository,
        current_user: Senior,
    ) -> ConsentResponse:
        check_person_scope(person_id, current_user)
        actor = current_user.sub
        try:
            return repository.set_consent(
                request.active, request.reason, actor, person_id=person_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    # ── Intervention routes (senior only) ─────────────────────────────────────

    @application.get(
        "/v1/interventions",
        response_model=list[Intervention],
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def interventions(repository: Repository, current_user: Senior) -> list[Intervention]:
        return repository.list_interventions(person_id=current_user.person_id or DEMO_PERSON_ID)

    @application.post(
        "/v1/interventions/{intervention_id}/outcome",
        response_model=OutcomeResponse,
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def intervention_outcome(
        intervention_id: str,
        request: OutcomeRequest,
        repository: Repository,
        current_user: Senior,
    ) -> OutcomeResponse:
        actor = current_user.sub
        try:
            return repository.record_outcome(
                intervention_id,
                request.outcome,
                actor,
                reason=request.reason,
                person_id=current_user.person_id or DEMO_PERSON_ID,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Intervention not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.get(
        "/v1/interventions/{intervention_id}/detail",
        response_model=OutreachDetail,
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def intervention_detail(
        intervention_id: str, repository: Repository, current_user: Senior
    ) -> OutreachDetail:
        """What "tell me more" shows. Fixed reviewed content, keyed off the candidate."""
        try:
            return repository.outreach_detail(
                intervention_id, person_id=current_user.person_id or DEMO_PERSON_ID
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Intervention not found"
            ) from exc

    @application.post(
        "/v1/interventions/{intervention_id}/follow-through",
        response_model=FollowThroughResponse,
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def intervention_follow_through(
        intervention_id: str,
        request: FollowThroughRequest,
        repository: Repository,
        current_user: Senior,
    ) -> FollowThroughResponse:
        try:
            return repository.record_follow_through(
                intervention_id,
                request.follow_through,
                current_user.sub,
                note=request.note,
                person_id=current_user.person_id or DEMO_PERSON_ID,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Intervention not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.get(
        "/v1/interventions/{intervention_id}/follow-up",
        response_model=FollowUpObservation,
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def intervention_follow_up(
        intervention_id: str, repository: Repository, current_user: Senior
    ) -> FollowUpObservation:
        """What activity did in the days after. Always 200 -- `available` says whether there is
        anything to report yet, so "too early to say" is a normal answer rather than an error."""
        try:
            return repository.follow_up_observation(
                intervention_id, person_id=current_user.person_id or DEMO_PERSON_ID
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Intervention not found"
            ) from exc

    @application.get(
        "/v1/interventions/history",
        response_model=list[OutreachSummary],
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def intervention_history(repository: Repository, current_user: Senior) -> list[OutreachSummary]:
        return repository.list_outreach_summaries(
            person_id=current_user.person_id or DEMO_PERSON_ID
        )

    # ── Personal preferences (senior only, senior-owned) ──────────────────────

    @application.get(
        "/v1/people/{person_id}/preferences",
        response_model=list[CandidatePreference],
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_preferences(
        person_id: str, repository: Repository, current_user: Senior
    ) -> list[CandidatePreference]:
        check_person_scope(person_id, current_user)
        return repository.list_candidate_preferences(person_id=person_id)

    @application.post(
        "/v1/people/{person_id}/preferences/{candidate_key}",
        response_model=CandidatePreferenceResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def set_person_preference(
        person_id: str,
        candidate_key: str,
        request: CandidatePreferenceRequest,
        repository: Repository,
        current_user: Senior,
    ) -> CandidatePreferenceResponse:
        """Only the senior may write this. A coordinator cannot mute a suggestion on someone
        else's behalf, which is the whole point of the control existing."""
        check_person_scope(person_id, current_user)
        try:
            return repository.set_candidate_preference(
                candidate_key,
                request.suppressed,
                request.reason,
                current_user.sub,
                person_id=person_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
            ) from exc

    @application.post(
        "/v1/people/{person_id}/day-dispute",
        response_model=DayDisputeResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def dispute_day(
        person_id: str,
        request: DayDisputeRequest,
        repository: Repository,
        current_user: Senior,
    ) -> DayDisputeResponse:
        check_person_scope(person_id, current_user)
        try:
            return repository.record_day_dispute(
                request.day,
                request.accurate,
                request.note,
                current_user.sub,
                person_id=person_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Day not found"
            ) from exc

    # ── The user-initiated loop (senior only) ─────────────────────────────────

    @application.post(
        "/v1/activities/search",
        response_model=ActivityQueryResponse,
        tags=["activities"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def search_activities(
        request: ActivityQueryRequest,
        repository: Repository,
        current_user: Senior,
    ) -> ActivityQueryResponse:
        """A senior asking for something to do, rather than the wearable prompting us.

        Deliberately not routed through the policy ladder. The ladder answers "should we contact
        this person?", which is the wrong question here -- they contacted us. What the ladder's
        guarantees still cover is the candidate set: the deterministic filter runs before the
        planner sees anything, and the planner can only choose from what survived it.
        """
        try:
            return repository.search_activities(
                text=request.text,
                intent=request.intent,
                person_id=current_user.person_id or DEMO_PERSON_ID,
                actor=current_user.sub,
            )
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.post(
        "/v1/activities/{activity_id}/response",
        response_model=ActivityResponseResponse,
        tags=["activities"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def respond_to_activity(
        activity_id: str,
        request: ActivityResponseRequest,
        repository: Repository,
        current_user: Senior,
    ) -> ActivityResponseResponse:
        """The senior answers a search result: "I'm interested" or "Not for me".

        The person is always the caller's own (from the token, like `search_activities`);
        listings are shared, so there is no other person's record to reach here. `interested`
        puts the listing on their week when its day is inside the week being planned and says
        so plainly when it is not; `not_for_me` with a reason that names a kind of activity
        teaches the dimensional learner, exactly as an outreach decline does. An optional
        `clarification` says how far that reason reaches; without one the answer stays
        item-level, which is the honest reading of one tap.
        """
        try:
            return repository.respond_to_activity(
                activity_id,
                request.response,
                reason=request.reason,
                clarification=request.clarification,
                query_id=request.query_id,
                rank_shown=request.rank_shown,
                day=request.day,
                actor=current_user.sub,
                person_id=current_user.person_id or DEMO_PERSON_ID,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found"
            ) from exc

    @application.get(
        "/v1/activities",
        response_model=list[ActivityCandidate],
        tags=["activities"],
        responses={401: {}, 403: {}},
    )
    def list_activities(
        repository: Repository, _: Annotated[CurrentUser, Depends(_require_any)]
    ) -> list[ActivityCandidate]:
        return repository.list_activities()

    @application.get(
        "/v1/activities/{activity_id}",
        response_model=ActivityCandidate,
        tags=["activities"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def activity_detail(
        activity_id: str,
        repository: Repository,
        _: Annotated[CurrentUser, Depends(_require_any)],
    ) -> ActivityCandidate:
        try:
            return repository.get_activity(activity_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found"
            ) from exc

    @application.get(
        "/v1/people/{person_id}/world-model",
        response_model=PersonWorldModel,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_world_model(
        person_id: str, repository: Repository, current_user: Senior
    ) -> PersonWorldModel:
        """Everything Care+ knows about this person, each fact labelled with where it came
        from. The senior's own surface: the facts include the kinds of activity they like, which
        by the standing care-team-visibility decision never reach a coordinator in content --
        `GET /v1/metrics` carries only the counts (`world_model_quality`)."""
        check_person_scope(person_id, current_user)
        return repository.world_model(person_id=person_id)

    @application.get(
        "/v1/people/{person_id}/activity-preferences",
        response_model=ActivityPreferences,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def person_activity_preferences(
        person_id: str, repository: Repository, current_user: Senior
    ) -> ActivityPreferences:
        """What Care+ believes about the *kinds* of activity this person prefers.

        Shown to the senior as "Your preferences" and editable there. Never surfaced to a
        coordinator: what a person asks for is theirs, and only the aggregate that they
        self-initiate at all reaches the care team.
        """
        check_person_scope(person_id, current_user)
        return repository.activity_preferences(person_id=person_id)

    @application.post(
        "/v1/interventions/{intervention_id}/enjoyment",
        response_model=EnjoymentResponse,
        tags=["interventions"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def intervention_enjoyment(
        intervention_id: str,
        request: EnjoymentRequest,
        repository: Repository,
        current_user: Senior,
    ) -> EnjoymentResponse:
        """Whether it was any good -- the beat after "did you get a chance?".

        Separate from follow-through because attending and enjoying are different facts, and a
        system that cannot tell them apart will keep offering something a person dutifully turns
        up to and quietly dislikes.
        """
        try:
            return repository.record_enjoyment(
                intervention_id,
                request.enjoyment,
                request.liked,
                current_user.sub,
                person_id=current_user.person_id or DEMO_PERSON_ID,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Intervention not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    # ── Proposed memory, goals and the week (senior only) ─────────────────────

    @application.get(
        "/v1/people/{person_id}/proposed-memories",
        response_model=list[ProposedMemory],
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_proposed_memories(
        person_id: str, repository: Repository, current_user: Senior
    ) -> list[ProposedMemory]:
        check_person_scope(person_id, current_user)
        return repository.list_proposed_memories(person_id=person_id)

    @application.post(
        "/v1/people/{person_id}/proposed-memories/{proposal_id}",
        response_model=MemoryDecisionResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def decide_proposed_memory(
        person_id: str,
        proposal_id: str,
        request: MemoryDecisionRequest,
        repository: Repository,
        current_user: Senior,
    ) -> MemoryDecisionResponse:
        """Only the senior may answer. Nothing inferred from their words is stored until they do."""
        check_person_scope(person_id, current_user)
        try:
            return repository.decide_proposed_memory(
                proposal_id, request.decision, current_user.sub, person_id=person_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found"
            ) from exc

    @application.post(
        "/v1/people/{person_id}/context-answer",
        response_model=ContextAnswerResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def answer_context_question(
        person_id: str,
        request: ContextAnswerRequest,
        repository: Repository,
        current_user: Senior,
    ) -> ContextAnswerResponse:
        check_person_scope(person_id, current_user)
        try:
            return repository.answer_context_question(
                request.question_id,
                request.value,
                request.note,
                current_user.sub,
                person_id=person_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Question not found"
            ) from exc

    @application.post(
        "/v1/people/{person_id}/baseline-confirmation",
        response_model=BaselineConfirmationResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def decide_baseline_confirmation(
        person_id: str,
        request: BaselineConfirmationRequest,
        repository: Repository,
        current_user: Senior,
    ) -> BaselineConfirmationResponse:
        """Only the senior may answer "is this your new normal?". Nothing re-anchors unless they
        confirm it themselves; see `SqlAlchemyRepository.decide_baseline_confirmation`.
        """
        check_person_scope(person_id, current_user)
        try:
            return repository.decide_baseline_confirmation(
                request.decision, current_user.sub, person_id=person_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No baseline confirmation is currently pending for this person",
            ) from exc

    @application.get(
        "/v1/people/{person_id}/goals",
        response_model=list[ActivityGoal],
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_goals(
        person_id: str, repository: Repository, current_user: Senior
    ) -> list[ActivityGoal]:
        check_person_scope(person_id, current_user)
        return repository.list_goals(person_id=person_id)

    @application.post(
        "/v1/people/{person_id}/goals",
        response_model=ActivityGoal,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def set_person_goal(
        person_id: str,
        request: ActivityGoalRequest,
        repository: Repository,
        current_user: Senior,
    ) -> ActivityGoal:
        check_person_scope(person_id, current_user)
        return repository.set_goal(
            request.kind,
            request.target_per_week,
            request.active,
            current_user.sub,
            person_id=person_id,
        )

    @application.get(
        "/v1/people/{person_id}/week",
        response_model=WeekPlan,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_week(person_id: str, repository: Repository, current_user: Senior) -> WeekPlan:
        check_person_scope(person_id, current_user)
        return repository.week_plan(person_id=person_id)

    @application.post(
        "/v1/people/{person_id}/week",
        response_model=WeekPlan,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def plan_activity(
        person_id: str,
        request: PlanActivityRequest,
        repository: Repository,
        current_user: Senior,
    ) -> WeekPlan:
        check_person_scope(person_id, current_user)
        try:
            return repository.plan_activity(
                request.activity_id, request.day, current_user.sub, person_id=person_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found"
            ) from exc

    @application.post(
        "/v1/people/{person_id}/week/{plan_id}/follow-through",
        response_model=PlannedFollowThroughResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def planned_follow_through(
        person_id: str,
        plan_id: str,
        request: PlannedFollowThroughRequest,
        repository: Repository,
        current_user: Senior,
    ) -> PlannedFollowThroughResponse:
        """What happened to a planned activity. 404 for a plan that is not this person's, so the
        route is not an existence oracle; 422 before the day has come or on a repeat."""
        check_person_scope(person_id, current_user)
        try:
            return repository.record_planned_follow_through(
                plan_id,
                request.follow_through,
                request.note,
                current_user.sub,
                person_id=person_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.post(
        "/v1/people/{person_id}/week/{plan_id}/enjoyment",
        response_model=PlannedEnjoymentResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def planned_enjoyment(
        person_id: str,
        plan_id: str,
        request: PlannedEnjoymentRequest,
        repository: Repository,
        current_user: Senior,
    ) -> PlannedEnjoymentResponse:
        check_person_scope(person_id, current_user)
        try:
            return repository.record_planned_enjoyment(
                plan_id,
                request.enjoyment,
                request.liked,
                current_user.sub,
                person_id=person_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.put(
        "/v1/people/{person_id}/activity-preferences/{dimension}/{value}",
        response_model=PreferenceStatementResponse,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def state_activity_preference(
        person_id: str,
        dimension: PreferenceDimension,
        value: Annotated[
            str,
            # A dimension value is a short token or category name, never prose: bounded to the
            # column and to printable text so the path cannot carry a paragraph into storage.
            Path(max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9 &'()+,./_-]{0,159}$"),
        ],
        request: PreferenceStatementRequest,
        repository: Repository,
        current_user: Senior,
    ) -> PreferenceStatementResponse:
        """The person's own control over what Care+ remembers about the kinds of activity
        they like: prefer, avoid (optionally until a day), or forget. Only the senior may write
        it, exactly like `set_candidate_preference`."""
        check_person_scope(person_id, current_user)
        try:
            return repository.state_preference(
                dimension,
                value,
                request.stance,
                until=request.until,
                stated_text=request.stated_text,
                actor=current_user.sub,
                person_id=person_id,
            )
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.get(
        "/v1/people/{person_id}/replan-notices",
        response_model=list[ReplanNotice],
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def person_replan_notices(
        person_id: str, repository: Repository, current_user: Senior
    ) -> list[ReplanNotice]:
        """Planned activities that can no longer happen, each with a suggested alternative.

        A proposal only. Nothing is ever swapped without the person choosing it -- substituting
        silently would be Care+ deciding how someone spends their day.
        """
        check_person_scope(person_id, current_user)
        return repository.replan_notices(person_id=person_id)

    @application.post(
        "/v1/people/{person_id}/week/{plan_id}/replace",
        response_model=WeekPlan,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def replace_planned_activity(
        person_id: str,
        plan_id: str,
        request: ReplacePlannedActivityRequest,
        repository: Repository,
        current_user: Senior,
    ) -> WeekPlan:
        """The person's answer to a replan offer: this one instead, on the same day.

        Only the senior may answer, and only for their own plan: 404 for a plan or listing that is
        not theirs (or that a dead run made), so the route is not an existence oracle. 422 when
        there is nothing to replace, when the listing cannot be planned on that day, or when the
        answer has already been given -- never a silent success that changes nothing.
        """
        check_person_scope(person_id, current_user)
        try:
            return repository.replace_planned_activity(
                plan_id, request.activity_id, current_user.sub, person_id=person_id
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Plan or listing not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @application.post(
        "/v1/people/{person_id}/replan-offers/{offer_id}/decline",
        response_model=ReplanOffer,
        tags=["people"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def decline_replan_offer(
        person_id: str,
        offer_id: str,
        repository: Repository,
        current_user: Senior,
    ) -> ReplanOffer:
        """ "No thanks" -- recorded once, on the server, so the same offer is not put again.

        The plan itself is untouched: declining a replacement is not declining the outing.
        """
        check_person_scope(person_id, current_user)
        try:
            return repository.decline_replan_offer(offer_id, current_user.sub, person_id=person_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Replan offer not found"
            ) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    # ── Programme catalogue (senior + coordinator + demo_operator) ────────────

    @application.get(
        "/v1/programmes",
        response_model=list[Programme],
        tags=["programmes"],
        responses={401: {}, 403: {}},
    )
    def programmes(
        repository: Repository, _: Annotated[CurrentUser, Depends(_require_any)]
    ) -> list[Programme]:
        return repository.list_programmes()

    # ── Simulator routes (demo_operator only) ─────────────────────────────────

    @application.post(
        "/v1/simulation/advance",
        response_model=AdvanceResponse,
        tags=["simulation"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def advance(
        request: AdvanceRequest,
        repository: Repository,
        current_user: DemoOperator,
    ) -> AdvanceResponse:
        try:
            return repository.advance(
                request.event,
                request.event_id,
                person_id=request.person_id or DEMO_PERSON_ID,
            )
        except StaleRunConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValidationError:
            # A server-side model failure, not a bad request: `error_responses` classifies it.
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc
        except IntegrityError as exc:
            # Two advances for the same person racing on the same simulated day. The unique
            # constraint on (run_id, day) does its job -- exactly one day is written and the
            # data stays correct -- but the loser reached the client as an unhandled 500. A
            # double-clicked "advance" button is a conflict, not a server fault. Callers that
            # pass an `event_id` never get here: that path is idempotent and replays the first
            # response.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This simulated day was already advanced by a concurrent request. "
                    "Re-read the person's state, or pass an event_id to make the call "
                    "idempotent."
                ),
            ) from exc

    @application.get(
        "/v1/simulation/events",
        response_model=list[AuditEvent],
        tags=["simulation"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def events(
        repository: Repository, current_user: DemoOperator, person_id: str | None = None
    ) -> list[AuditEvent]:
        try:
            return repository.list_events(person_id=person_id or DEMO_PERSON_ID)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    @application.get(
        "/v1/simulation/latest",
        response_model=AdvanceResponse | None,
        tags=["simulation"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def latest_advance(
        repository: Repository, current_user: DemoOperator, person_id: str | None = None
    ) -> AdvanceResponse | None:
        try:
            return repository.latest_advance(person_id=person_id or DEMO_PERSON_ID)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    @application.get(
        "/v1/simulation/history",
        response_model=list[SimulationHistoryEntry],
        tags=["simulation"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def simulation_history(
        repository: Repository,
        current_user: DemoOperator,
        person_id: str | None = None,
        limit: int = 10,
    ) -> list[SimulationHistoryEntry]:
        try:
            return repository.simulation_history(person_id=person_id or DEMO_PERSON_ID, limit=limit)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    # ── Evaluator routes (demo_operator only; read-only, never persist) ───────

    @application.post(
        "/v1/evaluator/ranker/inspect",
        response_model=RankerInspectResponse,
        tags=["evaluator"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def inspect_ranker(
        request: RankerInspectRequest,
        repository: Repository,
        current_user: DemoOperator,
    ) -> RankerInspectResponse:
        """How the activity ranker got from one request to the cards it would show, and what a
        previewed history, counterfactual or response would change.

        Evaluator-only and read-only: the trace is built from one execution of the production
        ranker and nothing is persisted -- no audit event, preference, engagement, plan or
        catalogue write. A senior or coordinator token is refused.
        """
        try:
            return repository.inspect_ranker(request)
        except RankerRequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
        except RankerPersonNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc
        except (KeyError, ValueError) as exc:
            # Only the two named errors above are the caller's fault. A stray `KeyError` or
            # `ValueError` (a pydantic `ValidationError` while building the trace included) is a
            # defect in the inspector, and the app-wide handlers would otherwise report it as
            # "Person not found" or as a bad request.
            raise RankerInspectorDefect(type(exc).__name__) from exc

    @application.get(
        "/v1/evaluator/ranker/presets",
        response_model=RankerPresetsResponse,
        tags=["evaluator"],
        responses={401: {}, 403: {}},
    )
    def ranker_presets(repository: Repository, current_user: DemoOperator) -> RankerPresetsResponse:
        """The scripted history presets and preview controls the ranker inspector allows."""
        return repository.ranker_presets()

    @application.get(
        "/v1/evaluator/people/{person_id}/senior-home",
        response_model=SeniorHomePreview,
        tags=["evaluator"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def senior_home_preview(
        person_id: str, repository: Repository, current_user: DemoOperator
    ) -> SeniorHomePreview:
        """One persona's senior home content, for the Demo Tools senior-screen preview.

        Demo operator only, and read-only: it composes the same person-state and intervention reads
        the senior's own screen uses and writes nothing. It is not the senior's own screen and is
        never an identity path into one -- `/senior` stays pinned to the demo person.
        """
        state, latest = repository.senior_home(person_id=person_id)
        return SeniorHomePreview(
            person_id=person_id,
            state=state,
            latest_intervention=latest,
            disclosure=SENIOR_HOME_PREVIEW_DISCLOSURE,
        )

    # ── Coordinator routes ────────────────────────────────────────────────────

    @application.get(
        "/v1/coordinator/people/{person_id}/outreach-history",
        response_model=list[OutreachSummary],
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def coordinator_outreach_history(
        person_id: str, repository: Repository, _: Coordinator
    ) -> list[OutreachSummary]:
        """What was offered, what the person said, and what their activity did afterwards.

        Separate from the senior's own `/v1/interventions/history` rather than one route with a
        widened scope check: the senior route is scoped by identity, this one by role, and
        collapsing them would mean a single `person_id` mistake exposes one senior's record to
        another. Same repository call, same shape, different door.
        """
        return repository.list_outreach_summaries(person_id=person_id)

    @application.get(
        "/v1/coordinator/people/{person_id}/activity-relative",
        response_model=ActivityRelativeToUsual,
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def coordinator_activity_relative(
        person_id: str,
        repository: Repository,
        _: Coordinator,
        days: Annotated[
            int, Query(ge=1, le=ACTIVITY_RELATIVE_MAX_DAYS)
        ] = ACTIVITY_RELATIVE_DEFAULT_DAYS,
    ) -> ActivityRelativeToUsual:
        """Recent days as positions against the person's own usual level, for a case page.

        Coordinator-scoped and derived on read: each day is usable or not (the wear-time gate) and,
        when usable, lower than usual or not (the ladder's low-day rule against the effective
        baseline today's decision used). No step counts, percentages or scores, so the browser
        never holds a policy cut-off. Once the person withdraws consent no day is returned
        (`consent_active` false). The senior's own `/v1/people/{id}/metrics` and `/state` stay
        senior-only; this is a separate door, not a widened one.
        """
        return repository.activity_relative_to_usual(person_id=person_id, days=days)

    @application.get(
        "/v1/coordinator/people",
        response_model=list[CoordinatorPersonRow],
        tags=["coordinator"],
        responses={401: {}, 403: {}},
    )
    def coordinator_people(
        repository: Repository, current_user: Coordinator
    ) -> list[CoordinatorPersonRow]:
        """The care-team roster: everyone with an active run, most attention first.

        Separate from `/v1/coordinator/queue` on purpose. The queue answers "what needs a
        decision"; this answers "who is on my caseload and is anything happening to them", which
        the queue could never answer because a person with nothing wrong has no case to appear as.

        Bands and standings only -- no step count, no percentage, no score. See
        `CoordinatorPersonRow`.
        """
        return repository.list_coordinator_roster()

    @application.get(
        "/v1/coordinator/priorities",
        response_model=CarePriorityBoard,
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def coordinator_priorities(
        repository: Repository,
        current_user: Coordinator,
        top_k: Annotated[int, Query(ge=1, le=MAX_TOP_K)] = DEFAULT_TOP_K,
        person_id: Annotated[str | None, Query(max_length=64)] = None,
    ) -> CarePriorityBoard:
        """Who to follow up with first: follow-up windows, reading order, and what to take note of.

        Read-only and deterministic (`triage.py`). The contact windows are capped by the decision
        the policy ladder already made, so no gate the ladder applies can be bypassed from here.
        Like the roster, it carries no step count, percentage or score about anyone.

        `person_id` returns the same board narrowed to that one person: `people` holds their row
        exactly as it appears on the full board -- `position` is still their place in the whole
        caseload's reading order -- and `follow_up_first` holds it only if the full board's
        `top_k` includes it. A person with no readings yet has no row (`people` is empty); an
        unknown person is a 404.
        """
        try:
            return repository.care_priorities(top_k=top_k, person_id=person_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found"
            ) from exc

    @application.get(
        "/v1/coordinator/metrics",
        response_model=CoordinatorFleetMetrics,
        tags=["coordinator"],
        responses={401: {}, 403: {}},
    )
    def coordinator_metrics(
        repository: Repository, current_user: Coordinator
    ) -> CoordinatorFleetMetrics:
        """The caseload's operational totals in one read.

        The sum of `GET /v1/metrics?person_id=...` over everyone `GET /v1/coordinator/people`
        lists, so Care Team no longer asks for each person's metrics in turn. Counts only.
        """
        return repository.coordinator_metrics()

    @application.get(
        "/v1/coordinator/queue",
        response_model=list[ReviewCase],
        tags=["coordinator"],
        responses={401: {}, 403: {}, 422: {}},
    )
    def coordinator_queue(
        repository: Repository,
        current_user: Coordinator,
        status: str | None = None,
    ) -> list[ReviewCase]:
        """The care-team queue: open and acknowledged cases by default, newest first within each
        status, never interleaved with a resolved one. Pass `?status=resolved` (or any
        comma-separated combination of `open`, `acknowledged`, `resolved`) to see closed cases."""
        statuses = _parse_queue_statuses(status)
        return _ordered_queue(repository.list_cases(), statuses)

    @application.get(
        "/v1/cases/{case_id}",
        response_model=ReviewCase,
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}},
    )
    def get_case(case_id: str, repository: Repository, current_user: Coordinator) -> ReviewCase:
        try:
            return repository.get_case(case_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Case not found"
            ) from exc

    @application.post(
        "/v1/cases/{case_id}/review",
        response_model=CaseReviewResponse,
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}, 422: {}},
    )
    def review_case(
        case_id: str,
        request: ReviewRequest,
        repository: Repository,
        current_user: Coordinator,
    ) -> CaseReviewResponse:
        reviewer = _demo_script_actor(
            application.state.settings, request.recorded_by_demo_script, current_user.sub
        )
        try:
            return repository.review_case(
                case_id,
                request.status,
                request.reviewer_note,
                reviewer,
                human_action=request.human_action,
                override_reason=request.override_reason,
                reached_too_late=request.reached_too_late,
                context_gap_category=request.context_gap_category,
                recorded_by_demo_script=request.recorded_by_demo_script,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Case not found"
            ) from exc

    # ── Review setting, person by person (coordinator; ADR 0008) ──────────────
    #
    # A coordinator's structured false-alarm judgement may lead Care+ to propose a change to
    # when it asks a human about one person. Nothing here changes a baseline or any other gate,
    # and every change takes effect from the next simulated day. `KeyError` -> 404, `ValueError`
    # -> 422, `ReviewThresholdConflict` -> 409 (already decided, stale `shown_on_day`, cooldown,
    # weekly cap), all through the app-wide handlers.

    _threshold_responses: dict[int | str, dict[str, object]] = {
        401: {},
        403: {},
        404: {},
        409: {},
        422: {},
    }

    @application.get(
        "/v1/coordinator/people/{person_id}/review-threshold",
        response_model=ReviewThresholdState,
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}, 409: {}},
    )
    def review_threshold_state(
        person_id: str, repository: Repository, current_user: Coordinator
    ) -> ReviewThresholdState:
        """This person's live review setting, its bounds, any open proposal and its history.

        Read-only: reading it any number of times writes nothing.
        """
        return repository.review_threshold_state(person_id, viewer_sub=current_user.sub)

    @application.get(
        "/v1/coordinator/people/{person_id}/review-threshold/replay",
        response_model=ReviewThresholdReplay,
        tags=["coordinator"],
        responses={401: {}, 403: {}, 404: {}, 409: {}, 422: {}},
    )
    def review_threshold_replay(
        person_id: str,
        repository: Repository,
        current_user: Coordinator,
        severity_pct: Annotated[
            int, Query(ge=MIN_SEVERITY_PCT, le=MAX_SEVERITY_PCT, multiple_of=SEVERITY_STEP_PCT)
        ],
        persistence_days: Annotated[int, Query(ge=MIN_PERSISTENCE_DAYS, le=MAX_PERSISTENCE_DAYS)],
    ) -> ReviewThresholdReplay:
        """What the live setting and a candidate setting would each have done over the last eight
        weeks of stored synthetic history. Calculated by code; read-only.

        The candidate must be on the allowed grid: below 40% only three days (422 otherwise)."""
        try:
            candidate = ReviewThresholdValue(
                severity_pct=severity_pct, persistence_days=persistence_days
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Below 40% a review setting must stay at three days (no mixed settings).",
            ) from exc
        return repository.review_threshold_replay(person_id, candidate)

    @application.post(
        "/v1/coordinator/people/{person_id}/review-threshold/proposals/{proposal_id}/approve",
        response_model=ReviewThresholdDecisionResponse,
        tags=["coordinator"],
        responses=_threshold_responses,
    )
    def approve_threshold_proposal(
        person_id: str,
        proposal_id: str,
        request: ReviewThresholdApproveRequest,
        repository: Repository,
        current_user: Coordinator,
    ) -> ReviewThresholdDecisionResponse:
        actor = _demo_script_actor(
            application.state.settings, request.recorded_by_demo_script, current_user.sub
        )
        return repository.approve_threshold_proposal(
            person_id,
            proposal_id,
            cause_confirmed=request.cause_confirmed,
            shown_on_day=request.shown_on_day,
            note=request.note,
            actor=actor,
            recorded_by_demo_script=request.recorded_by_demo_script,
        )

    @application.post(
        "/v1/coordinator/people/{person_id}/review-threshold/proposals/{proposal_id}/reject",
        response_model=ReviewThresholdDecisionResponse,
        tags=["coordinator"],
        responses=_threshold_responses,
    )
    def reject_threshold_proposal(
        person_id: str,
        proposal_id: str,
        request: ReviewThresholdRejectRequest,
        repository: Repository,
        current_user: Coordinator,
    ) -> ReviewThresholdDecisionResponse:
        return repository.reject_threshold_proposal(
            person_id,
            proposal_id,
            reason=request.reason,
            note=request.note,
            actor=current_user.sub,
        )

    @application.post(
        "/v1/coordinator/people/{person_id}/review-threshold/manual",
        response_model=ReviewThresholdDecisionResponse,
        tags=["coordinator"],
        responses=_threshold_responses,
    )
    def set_threshold_manually(
        person_id: str,
        request: ReviewThresholdManualSetRequest,
        repository: Repository,
        current_user: Coordinator,
    ) -> ReviewThresholdDecisionResponse:
        """Only once the latest round has run out -- three proposals rejected, or a no-change after
        a coordinator asked for the other change -- with nothing open or pending; before that, 409.
        A looser value also needs a round that began with "not a concern for this person" and a
        rejected too-tight proposal, and never a value reverted away from; otherwise 422."""
        return repository.set_threshold_manually(
            person_id,
            threshold=request.threshold,
            note=request.note,
            shown_on_day=request.shown_on_day,
            actor=current_user.sub,
        )

    @application.post(
        "/v1/coordinator/people/{person_id}/review-threshold/confirm-starting",
        response_model=ReviewThresholdDecisionResponse,
        tags=["coordinator"],
        responses=_threshold_responses,
    )
    def confirm_starting_threshold(
        person_id: str,
        request: ReviewThresholdShownRequest,
        repository: Repository,
        current_user: Coordinator,
    ) -> ReviewThresholdDecisionResponse:
        """Record that a coordinator looked at the starting setting and kept it. Gates nothing."""
        return repository.confirm_starting_threshold(
            person_id, shown_on_day=request.shown_on_day, actor=current_user.sub
        )

    @application.post(
        "/v1/coordinator/people/{person_id}/review-threshold/decisions/{decision_id}/reconfirm",
        response_model=ReviewThresholdDecisionResponse,
        tags=["coordinator"],
        responses=_threshold_responses,
    )
    def reconfirm_threshold(
        person_id: str,
        decision_id: str,
        request: ReviewThresholdShownRequest,
        repository: Repository,
        current_user: Coordinator,
    ) -> ReviewThresholdDecisionResponse:
        """Keep a live looser setting for another expiry period."""
        return repository.reconfirm_threshold(
            person_id, decision_id, shown_on_day=request.shown_on_day, actor=current_user.sub
        )


# ── Route-level auth helpers ──────────────────────────────────────────────────


async def _require_metrics(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(require_any_authenticated)],
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return current_user
    if current_user.role not in {AuthRole.COORDINATOR, AuthRole.DEMO_OPERATOR}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Coordinator or demo operator role required")
    return current_user


async def _require_any(
    current_user: Annotated[CurrentUser, Depends(require_any_authenticated)],
) -> CurrentUser:
    return current_user


def _check_person_scope(person_id: str, current_user: CurrentUser, settings: Settings) -> None:
    """Return 404 (not 403) if the path person_id is out of scope for this senior.

    404 rather than 403 on purpose: another person's record must be indistinguishable from one
    that does not exist, or the status code itself leaks who is registered.

    Two carve-outs, both narrow:

    * **Only seniors are scoped.** A coordinator or demo operator reading another person is doing
      their job -- the review queue already spans people -- so the identity check is the senior's
      own, not a blanket rule.
    * **Nothing is scoped when authentication is off.** With `AUTH_ENABLED=false` every request is
      handed the same synthetic senior (`require_senior` pins it to `DEMO_PERSON_ID`), so there is
      no real identity to protect and the check could only ever compare the demo person against
      themselves. Enforcing it there did not add safety; it made every persona except Mdm Lim
      return 404, which is why the demo's own persona switcher could not load four of its five
      people. An unauthenticated API is not access-controlled by this function or any other.
    """
    if not settings.auth_enabled:
        return
    if current_user.role is not AuthRole.SENIOR:
        return
    scoped_person_id = current_user.person_id or DEMO_PERSON_ID
    if person_id != scoped_person_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found")


def _check_demo_operator_sync(request: Request) -> None:
    """Synchronous wrapper that reads the Authorization header and validates a demo_operator JWT."""
    from silverloop.auth import _verify_token

    settings: Settings = request.app.state.settings
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    token = auth_header[len("Bearer ") :]
    result = _verify_token(token, settings)
    if result["role"] != AuthRole.DEMO_OPERATOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo operator role required")


app = create_app()
