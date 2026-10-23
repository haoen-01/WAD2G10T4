from __future__ import annotations

import os
import subprocess
import sys

import pytest

from silverloop.config import Settings
from silverloop.runtime import RuntimeConfigurationError, validate_runtime


def _with_both_profile_names(environment: dict[str, str]) -> dict[str, str]:
    """Set the profile under both names, as the launchers do, so a `.env` cannot override it."""
    profile = environment.get("SILVERLOOP_RUNTIME_PROFILE")
    if profile is None:
        return environment
    return {**environment, "CAREPLUS_RUNTIME_PROFILE": profile}


def run_runtime_check(**environment: str) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment.update(_with_both_profile_names(environment))
    return subprocess.run(
        [sys.executable, "-m", "silverloop.runtime", "check"],
        check=False,
        capture_output=True,
        env=process_environment,
        text=True,
    )


def run_supabase_smoke(**environment: str) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    process_environment.update(_with_both_profile_names(environment))
    return subprocess.run(
        [sys.executable, "-m", "silverloop.supabase_smoke"],
        check=False,
        capture_output=True,
        env=process_environment,
        text=True,
    )


def test_shared_runtime_rejects_sqlite_with_supabase_guidance() -> None:
    result = run_runtime_check(
        SILVERLOOP_RUNTIME_PROFILE="shared",
        DATABASE_URL="sqlite+pysqlite:///./.demo/silverloop.db",
    )

    assert result.returncode == 2
    assert "Supabase-first startup requires a PostgreSQL DATABASE_URL" in result.stderr
    assert "pnpm demo:offline" in result.stderr


def test_shared_runtime_rejects_placeholder_supabase_url() -> None:
    result = run_runtime_check(
        SILVERLOOP_RUNTIME_PROFILE="shared",
        DATABASE_URL=(
            "postgresql+psycopg://postgres.PROJECT_REF:password@"
            "aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require"
        ),
    )

    assert result.returncode == 2
    assert "placeholder" in result.stderr.lower()
    assert "never commit the real value" in result.stderr.lower()


def test_offline_runtime_accepts_safe_sqlite_fixture_configuration() -> None:
    result = run_runtime_check(
        SILVERLOOP_RUNTIME_PROFILE="offline",
        DATABASE_URL="sqlite+pysqlite:///./.demo/silverloop.db",
        ADAPTER_MODE="fixture",
        LLM_ENABLED="false",
    )

    assert result.returncode == 0


@pytest.mark.parametrize(
    ("database_url", "adapter_mode", "llm_enabled", "expected_message"),
    [
        (
            "postgresql+psycopg://user:secret@localhost/silverloop",
            "fixture",
            "false",
            "requires a SQLite DATABASE_URL",
        ),
        (
            "sqlite+pysqlite:///./.demo/silverloop.db",
            "authorised",
            "false",
            "requires ADAPTER_MODE=fixture",
        ),
        (
            "sqlite+pysqlite:///./.demo/silverloop.db",
            "fixture",
            "true",
            "requires LLM_ENABLED=false",
        ),
    ],
)
def test_offline_runtime_rejects_external_dependencies(
    database_url: str,
    adapter_mode: str,
    llm_enabled: str,
    expected_message: str,
) -> None:
    result = run_runtime_check(
        SILVERLOOP_RUNTIME_PROFILE="offline",
        DATABASE_URL=database_url,
        ADAPTER_MODE=adapter_mode,
        LLM_ENABLED=llm_enabled,
    )

    assert result.returncode == 2
    assert expected_message in result.stderr


def test_supabase_smoke_refuses_sqlite_without_echoing_connection_details() -> None:
    database_url = "sqlite+pysqlite:///private/sensitive/location/silverloop.db"
    result = run_supabase_smoke(
        SILVERLOOP_RUNTIME_PROFILE="shared",
        DATABASE_URL=database_url,
        ADAPTER_MODE="fixture",
        LLM_ENABLED="false",
    )

    assert result.returncode == 2
    assert "requires a PostgreSQL DATABASE_URL" in result.stderr
    assert database_url not in result.stderr


def test_enabled_planner_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A planner switched on without credentials is a configuration error, not a silent fallback."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(
        database_url="postgresql+psycopg://silverloop:localsecret@127.0.0.1:5432/silverloop",
        silverloop_runtime_profile="shared",
        llm_enabled=True,
        llm_api_key="",
    )
    with pytest.raises(RuntimeConfigurationError, match="LLM_API_KEY"):
        validate_runtime(settings)


def test_planner_iterations_cannot_exceed_the_hard_ceiling() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://silverloop:localsecret@127.0.0.1:5432/silverloop",
        silverloop_runtime_profile="shared",
        llm_enabled=True,
        llm_api_key="test-key",
        llm_max_iterations=99,
    )
    with pytest.raises(RuntimeConfigurationError, match="hard ceiling"):
        validate_runtime(settings)


def test_offline_profile_still_forbids_an_enabled_planner() -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        llm_enabled=True,
        llm_api_key="test-key",
    )
    with pytest.raises(RuntimeConfigurationError, match="LLM_ENABLED=false"):
        validate_runtime(settings)


def _profile_from(
    monkeypatch: pytest.MonkeyPatch, tmp_path, environment: dict[str, str], dotenv: str
) -> str:
    for name in ("CAREPLUS_RUNTIME_PROFILE", "SILVERLOOP_RUNTIME_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    env_file = tmp_path / ".env"
    env_file.write_text(dotenv, encoding="utf-8")
    return Settings(_env_file=env_file).silverloop_runtime_profile


def test_runtime_profile_reads_the_careplus_name(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    assert (
        _profile_from(monkeypatch, tmp_path, {}, "CAREPLUS_RUNTIME_PROFILE=offline\n") == "offline"
    )


def test_runtime_profile_falls_back_to_the_silverloop_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    dotenv = "SILVERLOOP_RUNTIME_PROFILE=offline\n"
    assert _profile_from(monkeypatch, tmp_path, {}, dotenv) == "offline"


def test_runtime_profile_prefers_careplus_when_both_are_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    dotenv = "CAREPLUS_RUNTIME_PROFILE=offline\nSILVERLOOP_RUNTIME_PROFILE=shared\n"
    assert _profile_from(monkeypatch, tmp_path, {}, dotenv) == "offline"


def test_offline_launchers_override_a_careplus_profile_in_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """`pnpm demo:offline` and Playwright set both names, so `.env` cannot pull them to shared."""
    launcher = {"CAREPLUS_RUNTIME_PROFILE": "offline", "SILVERLOOP_RUNTIME_PROFILE": "offline"}
    dotenv = "CAREPLUS_RUNTIME_PROFILE=shared\n"
    assert _profile_from(monkeypatch, tmp_path, launcher, dotenv) == "offline"
