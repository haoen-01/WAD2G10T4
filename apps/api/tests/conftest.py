import os
from collections.abc import Iterator

# Isolation must happen before anything imports `silverloop`, because `Settings` reads
# `os.environ` at construction and `get_settings()` is `@lru_cache`d -- the first caller wins for
# the whole process.
#
# The `Settings.model_config["env_file"] = None` line below was intended to do this and does NOT
# work: verified 2026-09-09 by importing the modules in conftest's own order, applying that
# mutation, and observing `get_settings()` still return `llm_enabled=True, llm_provider=bedrock`
# straight out of the developer's `.env`. It is kept because it correctly expresses the intent for
# explicitly-constructed `Settings(...)`, but the environment below is the guard that actually
# holds.
#
# Why this matters beyond tidiness: `SqlAlchemyRepository.settings` falls back to the process-wide
# `get_settings()` when no settings are injected, and 31 of the 31 repository constructions in this
# suite do exactly that. With a real `.env` present that made the suite dial live Bedrock inference
# (observed: ESTABLISHED connections to bedrock-runtime.us-east-1.amazonaws.com, and a runtime of
# minutes instead of seconds) and left it one fallback away from opening the production Supabase
# database. Forcing these three is what keeps the suite hermetic, free and deterministic.
# Every `LLM_*` field on `Settings`, not just the enable flag. `LLM_ENABLED=false` alone is not
# enough: `pnpm test` runs through nx with `NX_LOAD_DOT_ENV_FILES=true`, which loads the real
# `.env` into the process environment, and `Settings` reads `os.environ` regardless of `env_file`.
# That leaked live Bedrock credentials and provider settings into the suite -- six tests in
# `test_agent_planner.py` and `test_runtime.py` failed precisely because they assert behaviour for
# an *absent* key or a *default* provider and found the developer's real ones instead. Tests that
# want a value still pass it explicitly to `Settings(...)`, where it wins over the environment.
_NEUTRAL_LLM_ENV = {
    "LLM_ENABLED": "false",
    "LLM_PROVIDER": "anthropic",
    "LLM_API_KEY": "",
    "LLM_MODEL": "",
    "LLM_AWS_REGION": "",
    "LLM_AWS_ACCESS_KEY_ID": "",
    "LLM_AWS_SECRET_ACCESS_KEY": "",
    "LLM_AWS_SESSION_TOKEN": "",
    "LLM_BEDROCK_ENDPOINT": "mantle",
    "LLM_REQUEST_PROFILE": "modern",
    "LLM_THINKING": "adaptive",
    "LLM_EFFORT": "medium",
    "LLM_MAX_ITERATIONS": "4",
    "LLM_TIMEOUT_SECONDS": "20.0",
    "LLM_MAX_RETRIES": "1",
}
os.environ.update(_NEUTRAL_LLM_ENV)
os.environ["EXTERNAL_CONTEXT_ENABLED"] = "false"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

# ruff: noqa: E402 -- these imports are deliberately below the environment block above. Importing
# `silverloop` constructs `Settings`, which reads `os.environ`, and `get_settings()` is
# `@lru_cache`d, so the first construction wins for the whole process. Moving these to the top of
# the file would re-open the credential leak the block above exists to close.
import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

# The suite must not read the developer's `.env`. `Settings` normally loads it (see
# `SettingsConfigDict(env_file=...)` in `config.py`), which makes every test depend on whatever
# the machine happens to have configured: setting `LLM_ENABLED=true` locally, for instance, makes
# 18 tests fail because the offline runtime profile the fixtures use correctly refuses to start
# with the planner on. That is the guard working, tripped by ambient state that has nothing to do
# with the code under test. Roughly twenty call sites across the suite construct `Settings(...)`
# directly, so the isolation belongs here, once, rather than in each of them. Tests that want a
# non-default value still pass it explicitly, which is the only way it should ever arrive.
Settings.model_config["env_file"] = None

_AUTH_DISABLED_SETTINGS = dict(
    app_env="test",
    database_url="sqlite+pysqlite:///:memory:",
    silverloop_runtime_profile="offline",
    auth_enabled=False,
    llm_enabled=False,
)


@pytest.fixture
def repository() -> Iterator[SqlAlchemyRepository]:
    # Settings are injected rather than left to the process-wide `get_settings()` fallback, which
    # is what reached the developer's `.env` (see the note at the top of this file).
    instance = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:", settings=Settings(**_AUTH_DISABLED_SETTINGS)
    )
    instance.create_schema_for_tests()
    instance.reset()
    yield instance
    instance.close()


@pytest.fixture
def client(repository: SqlAlchemyRepository) -> Iterator[TestClient]:
    settings = Settings(**_AUTH_DISABLED_SETTINGS)
    application = create_app(repository, settings=settings, migrate_on_start=False)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def auth_disabled_settings() -> Settings:
    return Settings(**_AUTH_DISABLED_SETTINGS)
