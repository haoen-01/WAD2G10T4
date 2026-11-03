"""JWT verification tests — algorithm, signature, claims, and JWKS caching."""

from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1 as P256,
)
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    generate_private_key,
)
from fastapi.testclient import TestClient

from silverloop.auth import _JWKS_CACHE, _JWKS_LAST_FORCED_REFRESH, _get_jwks
from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

# ── Test fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_jwks_cache():
    _JWKS_CACHE.clear()
    _JWKS_LAST_FORCED_REFRESH.clear()
    yield
    _JWKS_CACHE.clear()
    _JWKS_LAST_FORCED_REFRESH.clear()


@pytest.fixture
def ec_private_key() -> EllipticCurvePrivateKey:
    return generate_private_key(P256())


@pytest.fixture
def repository_for_auth() -> SqlAlchemyRepository:
    repo = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repo.create_schema_for_tests()
    repo.reset()
    return repo


def _make_jwks_from_key(key: EllipticCurvePrivateKey, kid: str = "test-key-1") -> dict:
    import json

    from jwt.algorithms import ECAlgorithm

    pub = key.public_key()
    jwk_dict = json.loads(ECAlgorithm.to_jwk(pub))
    jwk_dict["kid"] = kid
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "ES256"
    return {"keys": [jwk_dict]}


def _make_es256_token(
    key: EllipticCurvePrivateKey,
    *,
    sub: str = "user-001",
    role: str = "senior",
    issuer: str = "https://project.supabase.co/auth/v1",
    kid: str = "test-key-1",
    exp_delta: int = 3600,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "iss": issuer,
        "aud": "authenticated",
        "iat": now,
        "exp": now + exp_delta,
        "app_metadata": {"role": role},
    }
    return jwt.encode(payload, key, algorithm="ES256", headers={"kid": kid})


def _make_hs256_token(
    secret: str,
    *,
    sub: str = "user-001",
    role: str = "coordinator",
    issuer: str = "https://project.supabase.co/auth/v1",
    exp_delta: int = 3600,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "iss": issuer,
            "aud": "authenticated",
            "iat": now,
            "exp": now + exp_delta,
            "app_metadata": {"role": role},
        },
        secret,
        algorithm="HS256",
    )


def _auth_client(
    repository: SqlAlchemyRepository,
    supabase_url: str = "https://project.supabase.co",
    jwt_secret: str = "",
) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=supabase_url,
        supabase_jwt_secret=jwt_secret,
    )
    app = create_app(repository, settings=settings, migrate_on_start=False)
    return TestClient(app, raise_server_exceptions=False)


# ── Missing / malformed credentials ──────────────────────────────────────────


def test_missing_credentials_returns_401(repository_for_auth: SqlAlchemyRepository) -> None:
    client = _auth_client(repository_for_auth)
    assert client.get("/v1/auth/me").status_code == 401


def test_malformed_token_returns_401(repository_for_auth: SqlAlchemyRepository) -> None:
    client = _auth_client(repository_for_auth)
    response = client.get("/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401


# ── Valid ES256 token ─────────────────────────────────────────────────────────


def test_valid_es256_token_succeeds(
    ec_private_key: EllipticCurvePrivateKey,
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    supabase_url = "https://project.supabase.co"
    jwks = _make_jwks_from_key(ec_private_key)

    with patch("silverloop.auth._fetch_jwks", return_value=jwks):
        client = _auth_client(repository_for_auth, supabase_url=supabase_url)
        # Link senior to person so require_senior doesn't 403
        repository_for_auth.upsert_person_link("user-001", "mdm-lim", "test")
        token = _make_es256_token(ec_private_key, issuer=supabase_url + "/auth/v1")
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "senior"


# ── Valid HS256 token ─────────────────────────────────────────────────────────


def test_valid_hs256_token_succeeds(repository_for_auth: SqlAlchemyRepository) -> None:
    secret = "supersecretjwtsecret"
    supabase_url = "https://project.supabase.co"
    client = _auth_client(repository_for_auth, supabase_url=supabase_url, jwt_secret=secret)
    token = _make_hs256_token(secret, role="coordinator", issuer=supabase_url + "/auth/v1")
    resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "coordinator"


def test_hs256_rejected_when_secret_not_configured(
    ec_private_key: EllipticCurvePrivateKey,
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    secret = "somesecret"
    client = _auth_client(repository_for_auth, supabase_url="https://project.supabase.co")
    token = _make_hs256_token(secret, role="coordinator")
    resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ── Expired token ─────────────────────────────────────────────────────────────


def test_expired_token_returns_401(
    ec_private_key: EllipticCurvePrivateKey,
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    supabase_url = "https://project.supabase.co"
    jwks = _make_jwks_from_key(ec_private_key)
    with patch("silverloop.auth._fetch_jwks", return_value=jwks):
        client = _auth_client(repository_for_auth, supabase_url=supabase_url)
        token = _make_es256_token(ec_private_key, issuer=supabase_url + "/auth/v1", exp_delta=-60)
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


# ── Wrong issuer ──────────────────────────────────────────────────────────────


def test_wrong_issuer_returns_401(
    ec_private_key: EllipticCurvePrivateKey,
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    supabase_url = "https://project.supabase.co"
    jwks = _make_jwks_from_key(ec_private_key)
    with patch("silverloop.auth._fetch_jwks", return_value=jwks):
        client = _auth_client(repository_for_auth, supabase_url=supabase_url)
        token = _make_es256_token(ec_private_key, issuer="https://evil.example.com/auth/v1")
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


# ── Unsupported algorithm ─────────────────────────────────────────────────────


def test_unsupported_algorithm_returns_401(repository_for_auth: SqlAlchemyRepository) -> None:
    key = "secretkey"
    token = jwt.encode(
        {
            "sub": "u1",
            "iss": "x",
            "exp": int(time.time()) + 3600,
            "app_metadata": {"role": "senior"},
        },
        key,
        algorithm="HS384",
    )
    client = _auth_client(repository_for_auth, supabase_url="https://project.supabase.co")
    resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ── Unknown role ──────────────────────────────────────────────────────────────


def test_unknown_role_returns_403(repository_for_auth: SqlAlchemyRepository) -> None:
    secret = "supersecret"
    supabase_url = "https://project.supabase.co"
    client = _auth_client(repository_for_auth, supabase_url=supabase_url, jwt_secret=secret)
    token = _make_hs256_token(secret, role="administrator", issuer=supabase_url + "/auth/v1")
    resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ── JWKS caching ──────────────────────────────────────────────────────────────


def test_jwks_cache_avoids_redundant_fetches(ec_private_key: EllipticCurvePrivateKey) -> None:
    url = "https://project.supabase.co"
    jwks = _make_jwks_from_key(ec_private_key)
    with patch("silverloop.auth._fetch_jwks", return_value=jwks) as mock_fetch:
        _get_jwks(url)
        _get_jwks(url)
        assert mock_fetch.call_count == 1


def test_jwks_cache_can_be_force_refreshed(ec_private_key: EllipticCurvePrivateKey) -> None:
    url = "https://project.supabase.co"
    jwks = _make_jwks_from_key(ec_private_key)
    with patch("silverloop.auth._fetch_jwks", return_value=jwks) as mock_fetch:
        _get_jwks(url)
        _get_jwks(url, force_refresh=True)
        assert mock_fetch.call_count == 2


# ── Unknown-kid DoS hardening ─────────────────────────────────────────────────


def test_repeated_unknown_kid_requests_do_not_flood_jwks_fetch(
    ec_private_key: EllipticCurvePrivateKey,
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    """A flood of requests each carrying a distinct, unknown `kid` must not
    trigger one outbound JWKS fetch per request. Only the (unavoidable) first
    cache-warming fetch plus at most one throttled forced refresh should
    occur, regardless of how many distinct bogus `kid`s are presented.
    """
    supabase_url = "https://project.supabase.co"
    jwks = _make_jwks_from_key(ec_private_key, kid="test-key-1")

    with patch("silverloop.auth._fetch_jwks", return_value=jwks) as mock_fetch:
        client = _auth_client(repository_for_auth, supabase_url=supabase_url)
        for i in range(10):
            token = _make_es256_token(
                ec_private_key,
                issuer=supabase_url + "/auth/v1",
                kid=f"bogus-kid-{i}",
            )
            resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 401

        # One fetch to populate the cold cache, one throttled forced refresh
        # attempt -- never one fetch per request.
        assert mock_fetch.call_count <= 2


def test_jwks_fetch_failure_returns_401_or_503_not_500(
    ec_private_key: EllipticCurvePrivateKey,
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    """A JWKS endpoint that is unreachable (network error, timeout, DNS
    failure, bad status) must fail closed as 401/503, never leak an
    unhandled 500.
    """
    supabase_url = "https://project.supabase.co"

    with patch(
        "silverloop.auth._fetch_jwks",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        client = _auth_client(repository_for_auth, supabase_url=supabase_url)
        token = _make_es256_token(ec_private_key, issuer=supabase_url + "/auth/v1")
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (401, 503)


def test_legitimate_key_rotation_still_resolves_after_forced_refresh(
    repository_for_auth: SqlAlchemyRepository,
) -> None:
    """The forced-refresh throttle must not prevent a genuine key rotation
    from being picked up: a token signed with a brand-new `kid` that only
    exists after refresh must still succeed on the first forced refresh.
    """
    supabase_url = "https://project.supabase.co"
    old_key = generate_private_key(P256())
    new_key = generate_private_key(P256())
    old_jwks = _make_jwks_from_key(old_key, kid="key-old")
    rotated_jwks = {
        "keys": [
            *_make_jwks_from_key(old_key, kid="key-old")["keys"],
            *_make_jwks_from_key(new_key, kid="key-new")["keys"],
        ]
    }

    with patch(
        "silverloop.auth._fetch_jwks",
        side_effect=[old_jwks, rotated_jwks],
    ) as mock_fetch:
        client = _auth_client(repository_for_auth, supabase_url=supabase_url)
        repository_for_auth.upsert_person_link("user-001", "mdm-lim", "test")

        # Warms the cache with only the old key.
        old_token = _make_es256_token(old_key, issuer=supabase_url + "/auth/v1", kid="key-old")
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
        assert resp.status_code == 200

        # A token signed with the newly rotated-in key is unknown against the
        # cached JWKS, forcing exactly one refresh, which must succeed.
        new_token = _make_es256_token(new_key, issuer=supabase_url + "/auth/v1", kid="key-new")
        resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert resp.status_code == 200
        assert mock_fetch.call_count == 2
