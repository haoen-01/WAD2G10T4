"""Splitting a signed scalar into evidence for and against (Alembic `e1c9a5d70b42`).

Four properties need a migration-level test rather than an ORM-level one, because all four are
about data that already exists:

1. Every pre-existing belief written at full weight must resolve to *exactly the strength it
   already had*. The split is `positive_evidence = observations` when the row leans for,
   `negative_evidence = observations` when it leans against, and the derived
   `(pos - neg) / (pos + neg + 2)` has to reproduce the stored `strength` for both. A migration
   that quietly re-weighted what Care+ believes about someone would be a worse bug than the
   one it exists to fix.
2. A belief written in the *capped* band -- "it was fine", "I'd prefer something else", stored as
   `0.15 * n/(n+2)` -- must migrate to the evidence it stood for rather than to `n` whole. Read
   whole, three "it was fine"s became three genuinely enjoyed outings and resolved `0.090` to
   `0.600`. The property that can be held here is the one that matters: a migrated database and a
   database this code wrote from the same history must agree, which is what
   `test_a_capped_okay_belief_migrates_to_what_a_fresh_database_would_hold` asserts against
   `apply_enjoyment` itself rather than against a copied constant.
3. A row with `strength == 0` contributes to neither side. "No lean" is not half a lean.
4. `strength` and `observations` stay. `world_model.py` and the Privacy screen both read them; a
   revision that dropped them would be a contract change smuggled inside a storage one.

Steps through the real Alembic chain rather than building the schema from ORM metadata, for the
same reason `test_dimension_preference_run_scope_migration.py` does: the property under test is
what the migration's own SQL does to rows that are already there.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from silverloop.local_time import at_local
from silverloop.models import (
    ActivityCandidate,
    ActivityLocation,
    ActivitySource,
    DimensionPreference,
    Enjoyment,
    IntegrationStatus,
    LikedAspect,
)
from silverloop.preferences import apply_enjoyment
from silverloop.sql_repository import _sync_database_url

_PRE_SPLIT_REVISION = "e3b7d5c18a42"
_REVISION = "e1c9a5d70b42"
_API_ROOT = Path(__file__).resolve().parents[1]
_EVIDENCE_SMOOTHING = 2.0

# An evening session, so `LikedAspect.TIMING` lands on the same `(timing, evening)` key the
# seeded legacy row carries.
_EVENING_CANDIDATE = ActivityCandidate(
    activity_id="act-evening",
    source=ActivitySource.AAC_FIXTURE,
    integration_status=IntegrationStatus.FIXTURE,
    title="Evening singing",
    provider="Community Centre",
    location=ActivityLocation(name="Community Centre"),
    retrieved_at=datetime.now(UTC),
    start_at=at_local(datetime.now(UTC).date(), 19, 0),
)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _backfill_sql() -> str:
    """The migration's own backfill statement, loaded from the versioned file by path rather than
    a dotted import -- `alembic/versions` is not a regular importable package -- so this test
    exercises the exact SQL the migration runs, not a copy that could drift from it."""
    path = (
        _API_ROOT
        / "alembic"
        / "versions"
        / f"{_REVISION}_split_preference_evidence_and_add_scope.py"
    )
    spec = importlib.util.spec_from_file_location(f"_{_REVISION}_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._BACKFILL_EVIDENCE_SQL


def _insert_person(connection) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        text(
            "insert into people (person_id, display_name, preferred_language, created_at) "
            "values ('person-legacy', 'Legacy Person', 'English', :now)"
        ),
        {"now": now},
    )


def _insert_preference(
    connection,
    preference_id: str,
    dimension: str,
    value: str,
    strength: float,
    observations: int,
    source: str,
) -> None:
    connection.execute(
        text(
            "insert into activity_dimension_preferences "
            "(preference_id, person_id, dimension, value, strength, source, confirmed, "
            "observations, updated_at) "
            "values (:p, 'person-legacy', :d, :v, :s, :src, 0, :o, :now)"
        ),
        {
            "p": preference_id,
            "d": dimension,
            "v": value,
            "s": strength,
            "src": source,
            "o": observations,
            "now": datetime.now(UTC).isoformat(),
        },
    )


@pytest.fixture
def pre_split_db(tmp_path: Path) -> str:
    """A SQLite database migrated to the revision immediately before the split, holding one belief
    leaning for, one leaning against, and one with no lean at all."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-split.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_SPLIT_REVISION)

    engine = create_engine(_sync_database_url(database_url))
    with engine.begin() as connection:
        _insert_person(connection)
        # -3/(3+2): three declines, the exact shape `_weak_negative_strength` produced.
        _insert_preference(
            connection, "dimpref-against", "environment", "outdoor", -0.6, 3, "decline_reason"
        )
        # +1/(1+2): one enjoyed activity.
        _insert_preference(connection, "dimpref-for", "social", "social", 0.333, 1, "inferred")
        _insert_preference(connection, "dimpref-neutral", "timing", "morning", 0.0, 2, "inferred")
        # 0.15 * 3/(3+2): three "it was fine"s, the exact shape `_capped_positive_strength`
        # produced. The band `_NEUTRAL_EVIDENCE_CAP` reserved for evidence that is real but weak.
        _insert_preference(connection, "dimpref-okay", "timing", "evening", 0.09, 3, "inferred")
        # A statement, repeated. Pre-split, `observations` counted the repeats.
        _insert_preference(
            connection, "dimpref-stated", "environment", "indoor", 1.0, 4, "senior_statement"
        )
    engine.dispose()
    return database_url


def _rows(database_url: str) -> dict[str, dict[str, object]]:
    engine = create_engine(_sync_database_url(database_url))
    with engine.connect() as connection:
        rows = {
            row.preference_id: dict(row._mapping)
            for row in connection.execute(
                text(
                    "select preference_id, strength, observations, positive_evidence, "
                    "negative_evidence, pivot, direction, origin_id, superseded_by, scope "
                    "from activity_dimension_preferences"
                )
            )
        }
    engine.dispose()
    return rows


def _derived_strength(row: dict[str, object]) -> float:
    positive = float(row["positive_evidence"])
    negative = float(row["negative_evidence"])
    total = positive + negative
    return (positive - negative) / (total + _EVIDENCE_SMOOTHING)


def test_every_existing_belief_resolves_to_the_strength_it_already_had(pre_split_db: str) -> None:
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    rows = _rows(pre_split_db)
    for preference_id in ("dimpref-against", "dimpref-for"):
        row = rows[preference_id]
        assert _derived_strength(row) == pytest.approx(float(row["strength"]), abs=0.001), (
            preference_id
        )


def test_a_capped_okay_belief_migrates_to_what_a_fresh_database_would_hold(
    pre_split_db: str,
) -> None:
    """Red team P1-3. The backfill only had `observations` and threw the cap away, so the whole
    `Enjoyment.OKAY` band was amplified by up to 6.7x: `0.090` -- three "it was fine"s -- came
    back as `0.600`, which is what three *genuinely enjoyed* outings earn. A migrated and a
    freshly-written database then disagreed about identical history.

    Written against `apply_enjoyment` rather than a copied constant: the fresh side of this
    comparison is the production write path, so the two cannot drift apart silently.
    """
    command.upgrade(_alembic_config(pre_split_db), _REVISION)
    migrated = _rows(pre_split_db)["dimpref-okay"]

    fresh: list[DimensionPreference] = []
    for index in range(3):
        fresh = apply_enjoyment(
            fresh,
            Enjoyment.OKAY,
            [LikedAspect.TIMING],
            _EVENING_CANDIDATE,
            datetime.now(UTC),
            origin_id=f"outing-{index}",
        )
    assert len(fresh) == 1

    assert float(migrated["positive_evidence"]) == pytest.approx(fresh[0].positive_evidence)
    assert float(migrated["negative_evidence"]) == pytest.approx(fresh[0].negative_evidence)
    assert _derived_strength(migrated) == pytest.approx(fresh[0].strength, abs=0.001)
    # And it is nowhere near what three enjoyed outings earn, which is the amplification itself.
    assert _derived_strength(migrated) < 0.25


def test_a_repeated_statement_migrates_as_the_one_origin_it_is(pre_split_db: str) -> None:
    """`strength` on a statement row is `+/-1.0` -- there is nothing to invert -- and pre-split
    `observations` counted how often the person repeated themselves, not how much stood behind
    it. Saying one thing four times is one person saying it, which is what
    `_confirm_dimension_preference` writes today."""
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    row = _rows(pre_split_db)["dimpref-stated"]
    assert row["positive_evidence"] == 1
    assert row["negative_evidence"] == 0
    assert row["observations"] == 4, "what the person did is not rewritten"


def test_a_belief_with_no_lean_is_evidence_for_neither_side(pre_split_db: str) -> None:
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    row = _rows(pre_split_db)["dimpref-neutral"]
    assert row["positive_evidence"] == 0
    assert row["negative_evidence"] == 0


def test_the_ordinal_and_provenance_columns_arrive_empty_rather_than_guessed(
    pre_split_db: str,
) -> None:
    """A `near`/`far` bucket cannot be turned back into the metres it was derived from, and a
    migration that invented one would put a number nobody said into a belief about a person."""
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    for row in _rows(pre_split_db).values():
        assert row["pivot"] is None
        assert row["direction"] is None
        assert row["origin_id"] is None
        assert row["superseded_by"] is None
        assert row["scope"] is None


def test_strength_and_observations_are_kept(pre_split_db: str) -> None:
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    row = _rows(pre_split_db)["dimpref-against"]
    assert row["strength"] == pytest.approx(-0.6)
    assert row["observations"] == 3


def test_the_backfill_is_idempotent_on_a_second_pass(pre_split_db: str) -> None:
    """Alembic never re-runs a completed migration against the same database, but the mirror
    applies the same statement by hand against a database the API may already have upgraded. It
    only ever touches rows where both sides are still `NULL`, so a second pass is a no-op -- and
    in particular it must not re-derive the split from a `strength` that has since moved."""
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    engine = create_engine(_sync_database_url(pre_split_db))
    with engine.begin() as connection:
        connection.execute(text("update activity_dimension_preferences set strength = 0.9"))
        connection.execute(text(_backfill_sql()))
    engine.dispose()

    row = _rows(pre_split_db)["dimpref-against"]
    assert row["negative_evidence"] == 3
    assert row["positive_evidence"] == 0


def test_the_clarification_column_reaches_both_decline_surfaces(pre_split_db: str) -> None:
    command.upgrade(_alembic_config(pre_split_db), _REVISION)

    engine = create_engine(_sync_database_url(pre_split_db))
    with engine.connect() as connection:
        for table in ("activity_offer_responses", "intervention_outcomes"):
            columns = {row[1] for row in connection.execute(text(f"pragma table_info({table})"))}
            assert "clarification" in columns, table
    engine.dispose()


def test_downgrade_removes_every_column_the_revision_added(pre_split_db: str) -> None:
    config = _alembic_config(pre_split_db)
    command.upgrade(config, _REVISION)
    command.downgrade(config, _PRE_SPLIT_REVISION)

    engine = create_engine(_sync_database_url(pre_split_db))
    with engine.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("pragma table_info(activity_dimension_preferences)"))
        }
        remaining = connection.execute(
            text("select count(*) from activity_dimension_preferences")
        ).scalar_one()
        responses = {
            row[1]
            for row in connection.execute(text("pragma table_info(activity_offer_responses)"))
        }
    engine.dispose()

    assert remaining == 5, "a downgrade must not take what Care+ knows with it"
    assert columns.isdisjoint(
        {
            "positive_evidence",
            "negative_evidence",
            "pivot",
            "direction",
            "origin_id",
            "superseded_by",
            "scope",
        }
    )
    assert "clarification" not in responses
