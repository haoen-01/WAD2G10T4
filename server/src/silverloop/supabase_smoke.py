from __future__ import annotations

import json
import sys
from uuid import uuid4

from silverloop.config import Settings
from silverloop.migrations import apply_rls_posture, upgrade_database
from silverloop.runtime import RuntimeConfigurationError, validate_runtime
from silverloop.sql_repository import SqlAlchemyRepository


def run(settings: Settings) -> dict[str, object]:
    validate_runtime(settings)
    if settings.adapter_mode != "fixture" or settings.llm_enabled:
        raise RuntimeConfigurationError(
            "The Supabase smoke test requires ADAPTER_MODE=fixture and LLM_ENABLED=false."
        )
    upgrade_database(settings.database_url)
    # Same order as the FastAPI lifespan, for the same reason: this command migrates the project,
    # so it opens the same window an API start does and must close it the same way.
    apply_rls_posture(settings.database_url)
    repository = SqlAlchemyRepository(
        settings.database_url,
        seed=settings.demo_seed,
        scenario_version=settings.demo_scenario_version,
    )
    try:
        repository.reset()
        readiness = repository.readiness("shared")
        if readiness.tables_without_rls:
            # Named separately from the revision check: "the schema is not ready" would be a
            # misleading description of an RLS gap, and the table names are the actionable part.
            raise RuntimeConfigurationError(
                "Supabase is connected but row-level security is off on: "
                f"{', '.join(readiness.tables_without_rls)}. See docs/supabase.md."
            )
        if readiness.status != "ready":
            raise RuntimeConfigurationError("Supabase is connected but the schema is not ready.")
        advanced = repository.advance("activity_declines", f"supabase-smoke-{uuid4().hex[:16]}")
        if advanced.created_intervention is None:
            raise RuntimeConfigurationError("Synthetic smoke scenario created no intervention.")
        repository.record_outcome(advanced.created_intervention.intervention_id, "accepted")
        metrics = repository.metrics()
        return {
            "status": "ok",
            "database_backend": readiness.database_backend,
            "migration_revision": readiness.migration_revision,
            "scenario_run_id": metrics.scenario_run_id,
            "decision_evidence": metrics.decision_evidence,
            "outcomes": metrics.outcomes,
            "source_classification_counts": metrics.source_classification_counts,
            "synthetic_data": True,
        }
    finally:
        repository.close()


def main() -> None:
    try:
        result = run(Settings())
    except (RuntimeConfigurationError, ValueError) as exc:
        print(f"Supabase smoke configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except Exception as exc:
        print("Supabase smoke failed; inspect server-side logs.", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
