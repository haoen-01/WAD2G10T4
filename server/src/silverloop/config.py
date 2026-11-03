from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: Literal["development", "demo", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    database_url: str = "sqlite+pysqlite:///./.demo/silverloop.db"
    # Connection pool for a server database (PostgreSQL/Supabase); SQLite ignores all of these.
    # Sized to stay under the Supabase session pooler's 15-client cap: `pool_size +
    # max_overflow` is the most connections one API process ever holds. A pre-ping on every
    # checkout costs a round trip to the pooler, so the blanket pre-ping is off. Instead:
    # - the pool is LIFO (`database_pool_use_lifo`), so a checkout gets the connection returned
    #   most recently -- in a multi-transaction write such as `advance()`, the one the previous
    #   phase just used -- and idle connections age at the bottom of the stack;
    # - a connection that sat in the pool for at least `database_pool_ping_idle_seconds` is pinged
    #   when it is checked out, and replaced before any statement runs on it if the ping fails; a
    #   connection returned more recently than that is handed out without a round trip;
    # - a connection older than `database_pool_recycle_seconds` is replaced when next checked out.
    #   The pooler's own idle timeout has not been measured, so the recycle is kept short (two
    #   minutes) rather than tuned to a guess.
    # Setting `database_pool_pre_ping` true pings every checkout and makes the idle ping redundant.
    database_pool_size: int = 10
    database_max_overflow: int = 4
    database_pool_recycle_seconds: int = 120
    database_pool_pre_ping: bool = False
    database_pool_use_lifo: bool = True
    database_pool_ping_idle_seconds: float = 30.0
    # TCP keepalives on libpq (psycopg) connections: an idle pooled connection sends a probe after
    # `idle` seconds, then every `interval` seconds, and the OS drops it after `count` unanswered
    # probes. They keep a NAT or load balancer from silently dropping an idle socket and make a
    # dead peer fail fast; they do not reset an application-level idle timeout in the pooler,
    # which is what `database_pool_recycle_seconds` is for. A value set in DATABASE_URL's query
    # string wins over these.
    database_pool_keepalives: bool = True
    database_pool_keepalives_idle_seconds: int = 30
    database_pool_keepalives_interval_seconds: int = 10
    database_pool_keepalives_count: int = 3
    # Read from CAREPLUS_RUNTIME_PROFILE, or the older SILVERLOOP_RUNTIME_PROFILE if that is unset.
    silverloop_runtime_profile: Literal["shared", "offline"] = Field(
        default="shared",
        validation_alias=AliasChoices("careplus_runtime_profile", "silverloop_runtime_profile"),
    )
    demo_seed: int = 2026
    demo_scenario_version: str = "v1"
    adapter_mode: Literal["fixture", "authorised"] = "fixture"

    # Outreach planner (silverloop.agent). Default off: the complete demo, every test and the
    # offline profile run with `llm_enabled=false`, where the deterministic ranker selects the
    # candidate exactly as it did before the planner existed.
    llm_enabled: bool = False
    # Which surface serves the planner. `anthropic` is the first-party API (billed to an
    # Anthropic account, authenticated by `llm_api_key`); `bedrock` is Amazon Bedrock (billed to
    # an AWS account, authenticated by the ambient AWS credential chain). Every feature the
    # planner depends on -- strict tool use, adaptive thinking, effort, prompt caching -- is
    # generally available on both, so the choice is commercial, not functional.
    #
    # `recorded` is neither: it is `silverloop.agent.recorded_client.RecordedClient`, answering
    # from a recording file keyed by the request. It makes no network call, needs no key and no
    # SDK, and exists so agent behaviour can be measured offline. It is a measurement surface,
    # never a deployment one: a request with no recorded answer degrades to the deterministic
    # ranker exactly like a provider outage.
    #
    # `openai` is OpenAI's Chat Completions, behind the same surface (`agent.openai_client`). It
    # reuses the assistant's `OPENAI_API_KEY`, `OPENAI_MODEL` and `OPENAI_BASE_URL` below.
    llm_provider: Literal["anthropic", "bedrock", "openai", "recorded"] = "anthropic"
    llm_api_key: str = ""
    # `recorded` only. A recording file, or a directory of them. Relative paths resolve against
    # the process working directory.
    llm_recording_path: str = ""
    # Bedrock only. Blank defers to the SDK's own resolution (AWS_REGION, or the active profile).
    llm_aws_region: str = ""
    # Which Bedrock surface to call.
    #   mantle -> `bedrock-mantle:CreateInference`, the Messages-API endpoint. Preferred, and the
    #             default, because it is the same request surface as the first-party API.
    #   invoke -> the legacy `bedrock-runtime:InvokeModel` path. Same SDK, same message shapes;
    #             it exists here because an AWS Organizations service control policy can deny one
    #             action and permit the other, and an SCP cannot be overridden from inside the
    #             account. If Mantle returns a 403 naming `bedrock-mantle:CreateInference`, try
    #             this before concluding Bedrock is unavailable.
    llm_bedrock_endpoint: Literal["mantle", "invoke"] = "mantle"
    # Which request features to send.
    #   modern -> adaptive thinking, `output_config.effort`, and `strict: true` on every tool.
    #             The default, and what every current Claude model expects.
    #   legacy -> none of the three. Older models (Claude 3.x, and whatever a restricted Bedrock
    #             account actually permits) reject all of them with a 400 schema error rather
    #             than ignoring them, so the request has to be shaped for the model on the other
    #             end. This costs the `strict: true` argument-validation guarantee and the
    #             reasoning-budget control; it does NOT touch the guardrail, which validates the
    #             model's output and is the actual security boundary. The mode is recorded on
    #             every agent run so the evidence says which shape was sent.
    llm_request_profile: Literal["modern", "legacy"] = "modern"
    # Whether to ask for extended thinking, and how.
    #   adaptive -> `{"type": "adaptive"}`, the current models' mode.
    #   off      -> omit `thinking` entirely.
    # Separate from the request profile because thinking support is a property of the *model*
    # while the profile is a property of the *surface*: Claude Haiku 4.5 is a current model that
    # rejects adaptive thinking ("adaptive thinking is not supported on this model") but accepts
    # everything else modern. Without this knob the only way to run it was the full legacy
    # profile, which needlessly gave up strict tool schemas and prompt caching too.
    llm_thinking: Literal["adaptive", "off"] = "adaptive"
    # Bedrock only, and all three optional. Leave blank to use the ambient AWS credential chain
    # (an IAM role, real `AWS_*` environment variables, or a configured profile) -- that is the
    # right answer for anything deployed.
    #
    # They exist because `.env` is read by pydantic-settings into `Settings` and is never exported
    # to the process environment, so putting `AWS_ACCESS_KEY_ID` in `.env` does NOT reach boto3.
    # These do. `llm_aws_session_token` is required alongside the other two for temporary STS
    # credentials, which expire -- when the planner starts reporting `fallback_error` after
    # working, an expired token is the first thing to check.
    llm_aws_access_key_id: str = ""
    llm_aws_secret_access_key: str = ""
    llm_aws_session_token: str = ""
    # Empty means "use the pinned id for the selected provider" (see
    # `silverloop.agent.constants.default_model_id`). Model ids are read from a constant and
    # never assembled at call time.
    llm_model: str = ""
    # Hard ceiling on planner iterations, clamped again by ITERATION_HARD_CEILING so a mis-set
    # environment variable cannot unbound the loop.
    llm_max_iterations: int = 4
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_timeout_seconds: float = 20.0
    # SDK-level retries per request. The default of 1 favours fast, visible degradation: a
    # provider problem should surface as `fallback_error` rather than being hidden behind a long
    # retry chain mid-demo. Raise it on a rate-limited account -- a shared or throttled Bedrock
    # quota can 429 the second turn of a planning loop that started fine, and the SDK backs off
    # and retries 429s automatically. The iteration cap is unaffected: retries happen inside one
    # iteration and cannot extend the loop.
    llm_max_retries: int = 1

    # Optional, best-effort live weather/public-holiday context (silverloop.context). Default
    # off: nothing changes for the offline demo or Playwright unless explicitly enabled, and it
    # is force-disabled under the `offline` runtime profile regardless of this flag (see
    # `create_app`).
    external_context_enabled: bool = False
    external_context_timeout_seconds: float = 3.0
    external_context_country: str = "SG"

    # The Care+ assistant (silverloop.assistant): the chat helper on every screen. With no
    # `openai_api_key`, or under the `offline` profile, it answers from its built-in helper and
    # makes no outside call. The key is read here, server-side only: it is never sent to the
    # browser, and must never be put in a `VITE_` variable.
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 20.0
    # Questions one person may ask in 10 minutes, so a stuck key or a loop cannot run up a bill.
    assistant_rate_per_10_min: int = 30

    # "Read my day" voice (silverloop.tts): Kokoro-82M on ONNX Runtime, on this server's CPU. No
    # cloud service and no key: nothing leaves the machine. Optional -- it needs `uv sync --extra
    # tts` and the model files (`uv run python -m silverloop.tts download`); without them the
    # speech route answers 503 and the browser reads aloud with its own voice instead.
    tts_enabled: bool = True
    # Relative paths resolve against server.
    tts_model_dir: str = "models/kokoro"
    tts_model_file: str = "kokoro-v1.0.onnx"
    tts_voice: str = "af_heart"
    # A little slower than Kokoro's default, as a calm companion would read.
    tts_speed: float = 0.92

    auth_enabled: bool = True
    supabase_url: str = ""
    supabase_jwt_secret: str = ""  # only for explicitly configured legacy HS256 projects

    model_config = SettingsConfigDict(
        env_file=(REPOSITORY_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
