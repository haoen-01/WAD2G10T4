from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from silverloop.assistant_routes import register_assistant_routes
from silverloop.auth import (
    AnyUser,
    DemoOperator,
    PersonReader,
    Senior,
)
from silverloop.config import Settings, get_settings
from silverloop.context import ExternalContextProvider
from silverloop.error_responses import SERVER_ERROR_RESPONSES, register_server_error_handlers
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_groups import FamilyGroups
from silverloop.family_routes import check_reader, register_family_routes, reset_demo_family
from silverloop.family_tasks import FamilyTaskStore
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.logging_config import request_id_var, request_logger
from silverloop.migrations import apply_rls_posture, upgrade_database
from silverloop.models import (
    AdvanceRequest,
    AdvanceResponse,
    AuthRole,
    ConsentRequest,
    ConsentResponse,
    CurrentUser,
    DailyMetric,
    DemoResetResponse,
    HealthResponse,
    Intervention,
    OutcomeRequest,
    OutcomeResponse,
    PersonState,
    ReadinessResponse,
)
from silverloop.repository import SilverLoopRepository
from silverloop.runtime import validate_runtime
from silverloop.sql_repository import (
    SqlAlchemyRepository,
    StaleRunConflict,
)
from silverloop.tts import warm_up as warm_up_speech


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
    family_tasks = FamilyTaskStore(sessions) if sessions is not None else None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        validate_runtime(config)
        if migrate_on_start:
            upgrade_database(config.database_url)
            # Immediately after, never before: the posture has to cover the tables the upgrade
            # just created. On Supabase those arrive already granted to `anon`/`authenticated`
            # by `ALTER DEFAULT PRIVILEGES`, so until this ran on every start the deny policy
            # waited on someone remembering to paste a SQL file (docs/supabase.md, "Row-level
            # security"). No-op off PostgreSQL; failures are reported through
            # `/ready`'s `tables_without_rls` rather than by refusing to start.
            apply_rls_posture(config.database_url)
        persistent_repository.ensure_active_run()
        if family_groups is not None and resets_demo_family_on_start(config, persistent_repository):
            # Sign-in off: a demo family member already in Mdm Lim's group (family_groups.py).
            family_groups.ensure_demo_group()
            reset_demo_family(application)
        if config.app_env != "test":
            # Load the "Read my day" voice in the background so the first reading does not wait;
            # a no-op when Kokoro or its model files are not installed (silverloop.tts).
            warm_up_speech(config)
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
    application.state.family_tasks = family_tasks
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
    register_assistant_routes(application)
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


# ── Route-level auth helpers ──────────────────────────────────────────────────


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
