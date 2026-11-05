import json

from silverloop.config import get_settings
from silverloop.fixtures import DEMO_PERSONAS
from silverloop.migrations import upgrade_database
from silverloop.sql_repository import SqlAlchemyRepository


def main() -> None:
    """Seed every curated persona in `DEMO_PERSONAS` (F5).

    `SqlAlchemyRepository.ensure_active_run()` -- called from the API lifespan -- deliberately
    keeps seeding only `DEMO_PERSON_ID`, so offline-demo and Playwright startup behaviour is
    unaffected. Run `pnpm seed` explicitly to get all six personas for the pitch/demo flow.
    """
    settings = get_settings()
    upgrade_database(settings.database_url)
    repository = SqlAlchemyRepository(
        settings.database_url,
        seed=settings.demo_seed,
        scenario_version=settings.demo_scenario_version,
        # So `demo_dates_follow_today` applies here as it does to the API's own resets.
        settings=settings,
    )
    for person_id in DEMO_PERSONAS:
        result = repository.reset(person_id=person_id)
        print(f"--- {person_id} ---")
        print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
