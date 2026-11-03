from __future__ import annotations

import os
import sys

from sqlalchemy.engine import make_url

from silverloop.agent.constants import ITERATION_HARD_CEILING, default_model_id
from silverloop.config import Settings
from silverloop.sql_repository import _sync_database_url


class RuntimeConfigurationError(ValueError):
    pass


def validate_runtime(settings: Settings) -> None:
    database_url = _sync_database_url(settings.database_url)
    backend = make_url(database_url).get_backend_name()
    if settings.silverloop_runtime_profile == "shared" and backend != "postgresql":
        raise RuntimeConfigurationError(
            "Supabase-first startup requires a PostgreSQL DATABASE_URL. "
            "Set the server-side Supabase connection string, or run "
            "`pnpm demo:offline` for the SQLite fallback."
        )
    placeholders = ("PROJECT_REF", "REGION", ":password@", "<password>")
    if settings.silverloop_runtime_profile == "shared" and any(
        placeholder in database_url for placeholder in placeholders
    ):
        raise RuntimeConfigurationError(
            "The Supabase DATABASE_URL still contains a placeholder. Copy the server-side "
            "connection string into your local or deployment secret store; never commit the "
            "real value."
        )
    if settings.silverloop_runtime_profile == "offline":
        if backend != "sqlite":
            raise RuntimeConfigurationError("The offline fallback requires a SQLite DATABASE_URL.")
        if settings.adapter_mode != "fixture":
            raise RuntimeConfigurationError("The offline fallback requires ADAPTER_MODE=fixture.")
        if settings.llm_enabled and settings.llm_provider != "recorded":
            # `recorded` is the one exception, and it is not a loophole: the recorded client
            # answers from a committed file and makes no network call at all, so it breaks
            # neither of the two promises the offline profile makes (no provider, no egress).
            # It exists so the agent loops can be measured under exactly the profile CI runs.
            raise RuntimeConfigurationError(
                "The offline fallback requires LLM_ENABLED=false, or LLM_PROVIDER=recorded "
                "(which replays a committed recording and makes no network call)."
            )
    if settings.llm_enabled:
        # Fail here rather than silently falling back mid-demo: a planner that is switched on
        # but cannot authenticate degrades correctly, but the operator should know before the
        # pitch that they are watching the deterministic ranker, not the agent.
        if settings.llm_provider == "recorded":
            # No key, no region, no SDK: the recorded client reads a file. What it does need is
            # that file, and an unset path would otherwise surface as a silent `fallback_disabled`
            # on every run -- the exact failure this block exists to pull forward to start-up.
            if not settings.llm_recording_path.strip():
                raise RuntimeConfigurationError(
                    "LLM_PROVIDER=recorded requires LLM_RECORDING_PATH -- a recording file or a "
                    "directory of them. Set it, or run with LLM_ENABLED=false to use the "
                    "deterministic ranker."
                )
        elif settings.llm_provider == "bedrock":
            # Bedrock authenticates through the ambient AWS credential chain, not an Anthropic
            # key, so the key check above does not apply. What it does need is a region: without
            # one the SDK cannot pick an endpoint, and the failure would surface as a silent
            # fallback mid-demo rather than at start-up.
            if not settings.llm_aws_region.strip() and not os.environ.get("AWS_REGION"):
                raise RuntimeConfigurationError(
                    "LLM_PROVIDER=bedrock requires LLM_AWS_REGION (or AWS_REGION) to be set. "
                    "Set the region, or run with LLM_ENABLED=false to use the deterministic "
                    "ranker."
                )
        elif not settings.llm_api_key.strip() and not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeConfigurationError(
                "LLM_ENABLED=true requires LLM_API_KEY (or ANTHROPIC_API_KEY) to be set. "
                "Set the key, or run with LLM_ENABLED=false to use the deterministic ranker."
            )
        if settings.llm_max_iterations > ITERATION_HARD_CEILING:
            raise RuntimeConfigurationError(
                f"LLM_MAX_ITERATIONS={settings.llm_max_iterations} exceeds the hard ceiling of "
                f"{ITERATION_HARD_CEILING}. Every planner loop must stay bounded."
            )
        if settings.llm_provider != "recorded":
            try:
                import anthropic  # noqa: F401
            except ImportError as exc:
                raise RuntimeConfigurationError(
                    "LLM_ENABLED=true requires the `anthropic` package. Run `uv sync` in "
                    "server/, or set LLM_ENABLED=false."
                ) from exc

    if settings.app_env == "production" and not settings.auth_enabled:
        raise RuntimeConfigurationError(
            "AUTH_ENABLED=false is not permitted in production. "
            "Set AUTH_ENABLED=true and configure SUPABASE_URL."
        )


def main() -> None:
    if sys.argv[1:] != ["check"]:
        raise SystemExit("Usage: python -m silverloop.runtime check")
    try:
        settings = Settings()
        validate_runtime(settings)
    except (RuntimeConfigurationError, ValueError) as exc:
        print(f"Runtime configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    # State plainly which selector will run, so nobody discovers mid-demo that they are
    # watching the deterministic ranker when they expected the planner, or the reverse.
    if settings.llm_enabled:
        from silverloop.agent.planner import describe_tool_surface

        model = settings.llm_model.strip() or default_model_id(settings.llm_provider)
        print(
            f"Outreach planner: enabled (provider={settings.llm_provider}, model={model}, "
            f"max_iterations={settings.llm_max_iterations}, effort={settings.llm_effort})"
        )
        if settings.llm_provider == "recorded":
            # Say it out loud. Someone reading "planner: enabled" must never be left thinking a
            # model is being consulted when a committed file is answering.
            print(
                "Planner transport: RECORDED -- replaying "
                f"{settings.llm_recording_path}; no model is consulted and no request leaves "
                "this machine. The model id above is not called: it is one of the four fields "
                "the recording is keyed by, so it must match the id the recording was made "
                "under or every request will miss and fall back."
            )
        print(f"Planner tool surface: {describe_tool_surface()}")
    else:
        print("Outreach planner: disabled; the deterministic ranker selects every candidate.")


if __name__ == "__main__":
    main()
