from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from silverloop.config import Settings
from silverloop.models import AuthRole, CurrentUser

_SUPPORTED_ALGORITHMS = frozenset({"ES256", "RS256", "HS256"})
_JWKS_CACHE: dict[str, tuple[dict, float]] = {}
_JWKS_TTL = 3600.0  # 1 hour; force refresh on unknown kid
_JWKS_FETCH_TIMEOUT = 3.0  # seconds; matches house precedent in context.py

# A forced refresh is triggered by an *unauthenticated* caller presenting an
# unrecognised `kid`. Without a bound, a flood of requests each using a
# distinct random `kid` would trigger one outbound JWKS fetch per request,
# exhausting the threadpool even after the blocking HTTP call is moved off
# the event loop. Throttle forced refreshes to at most once per Supabase
# URL per this interval; other requests in that window are served the
# existing cached JWKS (and correctly fail with "unknown kid" if it really
# is bogus). 10 seconds bounds attacker-triggered outbound traffic to a
# negligible rate while still picking up a genuine key rotation well within
# the 1-hour normal TTL.
_JWKS_FORCE_REFRESH_MIN_INTERVAL = 10.0
_JWKS_LAST_FORCED_REFRESH: dict[str, float] = {}
_JWKS_LOCK = threading.Lock()


def _fetch_jwks(supabase_url: str) -> dict:
    url = supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    response = httpx.get(url, timeout=_JWKS_FETCH_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _get_jwks(supabase_url: str, *, force_refresh: bool = False) -> dict:
    now = time.monotonic()

    if not force_refresh:
        cached = _JWKS_CACHE.get(supabase_url)
        if cached is not None and (now - cached[1]) < _JWKS_TTL:
            return cached[0]
    else:
        # Atomically check-and-set the last-forced-refresh timestamp so that
        # concurrent threadpool workers racing on a burst of bogus `kid`s
        # can't all slip through before the timestamp is updated.
        with _JWKS_LOCK:
            last_forced = _JWKS_LAST_FORCED_REFRESH.get(supabase_url)
            throttled = (
                last_forced is not None and (now - last_forced) < _JWKS_FORCE_REFRESH_MIN_INTERVAL
            )
            if not throttled:
                _JWKS_LAST_FORCED_REFRESH[supabase_url] = now
        if throttled:
            cached = _JWKS_CACHE.get(supabase_url)
            if cached is not None:
                return cached[0]
            # No cache has ever been populated and we're already within the
            # throttle window of a recent forced-refresh attempt: fail
            # closed rather than hammering a possibly-unreachable endpoint.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "JWKS temporarily unavailable; please retry shortly",
            )

    jwks = _fetch_jwks(supabase_url)
    _JWKS_CACHE[supabase_url] = (jwks, now)
    return jwks


def _find_public_key(jwks: dict, kid: str | None) -> jwt.PyJWK:
    keys = jwks.get("keys", [])
    if not keys:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "JWKS contains no keys")
    if kid:
        for key_data in keys:
            if key_data.get("kid") == kid:
                return jwt.PyJWK(key_data)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Unknown kid: {kid!r}")
    return jwt.PyJWK(keys[0])


def _verify_token(token: str, settings: Settings) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token") from exc

    alg = header.get("alg", "")
    if alg not in _SUPPORTED_ALGORITHMS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Unsupported algorithm: {alg}")

    decode_options = {"require": ["exp", "sub", "iss"]}
    kwargs: dict = {"algorithms": [alg], "options": decode_options, "audience": "authenticated"}

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "HS256 is not configured for this project"
            )
        if not settings.supabase_url:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "SUPABASE_URL is required for HS256 issuer validation",
            )
        kwargs["key"] = settings.supabase_jwt_secret
        kwargs["issuer"] = settings.supabase_url.rstrip("/") + "/auth/v1"
    else:
        if not settings.supabase_url:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "SUPABASE_URL not configured")
        kid = header.get("kid")
        try:
            jwks = _get_jwks(settings.supabase_url)
            public_key = _find_public_key(jwks, kid)
        except HTTPException:
            # On unknown-kid 401 (or a throttled-and-uncached forced-refresh
            # 503), try one forced refresh in case of a genuine key rotation.
            try:
                jwks = _get_jwks(settings.supabase_url, force_refresh=True)
                public_key = _find_public_key(jwks, kid)
            except HTTPException:
                raise
            except Exception as exc:
                msg = "Could not load JWKS key"
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg) from exc
        except Exception as exc:
            # Network failures (ConnectError, TimeoutException,
            # HTTPStatusError from raise_for_status(), DNS failures, ...)
            # from the initial JWKS fetch must fail closed, never surface as
            # an unhandled 500.
            msg = "Could not load JWKS key"
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg) from exc

        issuer = settings.supabase_url.rstrip("/") + "/auth/v1"
        kwargs["key"] = public_key
        kwargs["issuer"] = issuer

    try:
        payload: dict = jwt.decode(token, **kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has expired") from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token issuer") from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token audience") from exc
    except jwt.InvalidSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token signature") from exc
    except jwt.DecodeError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token decode error") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token validation failed") from exc

    sub = payload.get("sub", "")
    if not sub or not isinstance(sub, str):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing or invalid sub claim")

    # No role in `app_metadata` is a self-registered account: its role is in the `accounts` table
    # (see `_resolve_role`). A role that is present but unknown is still refused here.
    role_str = payload.get("app_metadata", {}).get("role", "")
    role: AuthRole | None = None
    if role_str:
        try:
            role = AuthRole(role_str)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Unknown or unsupported role: {role_str!r}"
            ) from exc

    return {"sub": sub, "role": role, "payload": payload}


def _account_role(request: Request, sub: str) -> AuthRole | None:
    family = getattr(request.app.state, "family", None)
    return family.account_role(sub) if family is not None else None


def _resolve_role(request: Request, result: dict) -> AuthRole:
    """The token's role, else the role the account chose at sign-up. 403 until it has chosen."""
    role: AuthRole | None = result["role"] or _account_role(request, result["sub"])
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account not set up yet")
    return role


def demo_sub(request: Request) -> str:
    """Sign-in off only: who the demo is acting as (`X-Demo-Sub`), default the demo family member.

    With sign-in off nothing is access-controlled (see `main._check_person_scope`); the header only
    lets the offline demo and the e2e run act as more than one family member.
    """
    from silverloop.family_groups import DEMO_FAMILY_SUB

    raw = request.headers.get("x-demo-sub", "").strip()
    return raw[:128] if raw else DEMO_FAMILY_SUB


@dataclass(frozen=True)
class Identity:
    """A verified sign-in whose account may not have chosen a role yet."""

    sub: str
    token_role: AuthRole | None
    role: AuthRole | None


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser | None:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return None
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    role = await run_in_threadpool(_resolve_role, request, result)
    return CurrentUser(sub=result["sub"], role=role)


async def require_senior(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        from silverloop.fixtures import DEMO_PERSON_ID

        return CurrentUser(sub=DEMO_PERSON_ID, role=AuthRole.SENIOR, person_id=DEMO_PERSON_ID)
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    if await run_in_threadpool(_resolve_role, request, result) != AuthRole.SENIOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Senior role required")
    # Resolve durable person_id from link table
    repo = request.app.state.repository
    person_id = repo.lookup_person_for_sub(result["sub"])
    if person_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No person mapped to this senior account")
    return CurrentUser(sub=result["sub"], role=AuthRole.SENIOR, person_id=person_id)


async def require_coordinator(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return CurrentUser(sub="coordinator", role=AuthRole.COORDINATOR)
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    if result["role"] != AuthRole.COORDINATOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Coordinator role required")
    return CurrentUser(sub=result["sub"], role=AuthRole.COORDINATOR)


async def require_demo_operator(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return CurrentUser(sub="demo_operator", role=AuthRole.DEMO_OPERATOR)
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    if result["role"] != AuthRole.DEMO_OPERATOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Demo operator role required")
    return CurrentUser(sub=result["sub"], role=AuthRole.DEMO_OPERATOR)


async def require_any_authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return CurrentUser(sub="demo", role=AuthRole.SENIOR)
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    role = await run_in_threadpool(_resolve_role, request, result)
    return CurrentUser(sub=result["sub"], role=role)


async def require_family(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return CurrentUser(sub=demo_sub(request), role=AuthRole.FAMILY)
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    if await run_in_threadpool(_resolve_role, request, result) != AuthRole.FAMILY:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Family role required")
    return CurrentUser(sub=result["sub"], role=AuthRole.FAMILY)


async def require_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> Identity:
    """Any verified sign-in, including one that has not chosen `senior` or `family` yet: only
    `GET /v1/me` and `POST /v1/me/onboard` accept it."""
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        sub = demo_sub(request)
        return Identity(sub=sub, token_role=None, role=_account_role(request, sub))
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    account_role = await run_in_threadpool(_account_role, request, result["sub"])
    return Identity(
        sub=result["sub"], token_role=result["role"], role=result["role"] or account_role
    )


async def require_person_reader(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> CurrentUser:
    """A senior (with their own `person_id`) or a family member. Which senior a family member may
    read is checked per route (`family_routes.check_reader`): only one whose group they are in."""
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        from silverloop.family_groups import DEMO_SENIOR_SUB
        from silverloop.fixtures import DEMO_PERSON_ID

        sub = demo_sub(request)
        if sub == DEMO_SENIOR_SUB:
            return CurrentUser(sub=sub, role=AuthRole.SENIOR, person_id=DEMO_PERSON_ID)
        return CurrentUser(sub=sub, role=AuthRole.FAMILY)
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    result = await run_in_threadpool(_verify_token, credentials.credentials, settings)
    role = await run_in_threadpool(_resolve_role, request, result)
    if role is AuthRole.FAMILY:
        return CurrentUser(sub=result["sub"], role=role)
    if role is not AuthRole.SENIOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Senior or family role required")
    person_id = request.app.state.repository.lookup_person_for_sub(result["sub"])
    if person_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No person mapped to this senior account")
    return CurrentUser(sub=result["sub"], role=role, person_id=person_id)


Senior = Annotated[CurrentUser, Depends(require_senior)]
PersonReader = Annotated[CurrentUser, Depends(require_person_reader)]
Coordinator = Annotated[CurrentUser, Depends(require_coordinator)]
DemoOperator = Annotated[CurrentUser, Depends(require_demo_operator)]
AnyUser = Annotated[CurrentUser, Depends(require_any_authenticated)]
Family = Annotated[CurrentUser, Depends(require_family)]
SignedIn = Annotated[Identity, Depends(require_identity)]
