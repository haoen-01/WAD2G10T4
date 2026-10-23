from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def expected_database_revision() -> str:
    api_root = Path(__file__).parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic has no current head revision.")
    return revision
