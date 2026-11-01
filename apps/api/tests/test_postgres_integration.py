from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command
from silverloop import demo_story
from silverloop.config import Settings
from silverloop.db_models import (
    AppointmentNoteRow,
    AppointmentRow,
    AvailabilityEntryRow,
    Base,
    CareGroupRow,
    DecisionEvidenceRow,
    FamilyActivityRow,
    GroupMemberRow,
    HelperAssignmentRow,
)
from silverloop.family_calendar import FamilyCalendarStore
from silverloop.family_groups import DEMO_FAMILY, DEMO_FAMILY_SUB, FamilyGroups
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.migrations import apply_rls_posture, upgrade_database
from silverloop.models import (
    AppointmentNoteRequest,
    AppointmentRequest,
    CheckInKind,
    CheckInRequest,
)
from silverloop.schema_revision import expected_database_revision
from silverloop.sql_repository import SqlAlchemyRepository, _sync_database_url

POSTGRES_TEST_URL = os.getenv("SILVERLOOP_POSTGRES_TEST_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_TEST_URL,
        reason="SILVERLOOP_POSTGRES_TEST_URL is required for PostgreSQL integration tests",
    ),
]


def dedicated_postgres_test_url() -> str:
    assert POSTGRES_TEST_URL is not None
    database_url = _sync_database_url(POSTGRES_TEST_URL)
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql" or "test" not in (parsed.database or "").lower():
        pytest.fail(
            "PostgreSQL integration tests require a dedicated database whose name contains 'test'."
        )
    return database_url


def test_postgres_preserves_the_safe_product_loop_across_restart() -> None:
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    repository.reset()

    first = repository.advance("activity_declines", "postgres-event-001")
    assert first.created_intervention is not None
    intervention_id = first.created_intervention.intervention_id
    assert repository.advance("activity_declines", "postgres-event-001") == first

    consent = repository.set_consent(False, "PostgreSQL integration test opt-out.", "test")
    assert intervention_id in consent.withdrawn_intervention_ids
    with pytest.raises(ValueError, match="withdrawn"):
        repository.record_outcome(intervention_id, "accepted")

    repository.close()
    restarted = SqlAlchemyRepository(database_url)
    assert restarted.latest_advance() == first
    assert restarted.metrics().persistence == "postgresql"
    with restarted.sessions() as session:
        # Derived from the repository, never a literal: the pinned string sat at `c9d3e8f2a1b5`
        # through four later revisions, so this assertion tested nothing except that somebody had
        # remembered to edit it, and it failed for that reason rather than for a real one.
        assert (
            session.scalar(text("SELECT version_num FROM alembic_version"))
            == expected_database_revision()
        )
        decision_id = session.scalar(select(DecisionEvidenceRow.evidence_id))
    assert decision_id is not None

    with (
        pytest.raises(DBAPIError, match="append-only evidence cannot be changed"),
        restarted.sessions.begin() as session,
    ):
        session.execute(
            update(DecisionEvidenceRow)
            .where(DecisionEvidenceRow.evidence_id == decision_id)
            .values(decision="no_action")
        )
    restarted.close()


# ── `pnpm demo:story`, on the engine the shared runtime actually uses ─────────────────────────


CLEARED_NOTE = "A note the story has to clear."


def _story_settings(database_url: str) -> Settings:
    """Explicit, so nothing here comes from a `.env`. The fake admin below answers Supabase."""
    return Settings(
        app_env="test",
        database_url=database_url,
        silverloop_runtime_profile="shared",
        auth_enabled=True,
        llm_enabled=False,
        supabase_url="https://project.supabase.invalid",
    )


def _story_logins(
    repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str]:
    """All six logins as `setup_demo_accounts` leaves them, behind a read-only fake admin API."""
    family = FamilyGroups(repository.sessions, repository)
    subs = {login: str(uuid4()) for login in demo_story.LOGINS}
    users = [
        {
            "id": sub,
            "email": f"{login}@{demo_story.EMAIL_DOMAIN}",
            "app_metadata": {"role": "senior"} if login == "senior" else {},
        }
        for login, sub in subs.items()
    ]
    for login in demo_story.FAMILY_LOGINS:
        family.provision_family_account(subs[login], login.title())
    repository.upsert_person_link(subs["senior"], DEMO_PERSON_ID, "setup_demo_accounts")

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "the story only reads Supabase Auth"
        return httpx.Response(200, json={"users": users})

    monkeypatch.setattr(
        demo_story,
        "_supabase_admin",
        lambda *_: httpx.Client(
            transport=httpx.MockTransport(answer), base_url="https://admin.invalid"
        ),
    )
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.invalid")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "not-a-real-admin-key")
    return subs


def _story_rows(repository: SqlAlchemyRepository) -> dict[str, object]:
    """Mdm Lim's group and everything hanging off it, in a form two runs can be compared by."""
    with repository.sessions() as session:
        group = session.scalar(select(CareGroupRow).where(CareGroupRow.person_id == DEMO_PERSON_ID))
        assert group is not None

        def rows(model: type) -> list:
            return list(session.scalars(select(model).where(model.group_id == group.group_id)))

        return {
            "created_by": group.created_by,
            "linked_by": group.linked_by,
            "members": sorted((row.sub, row.role, row.status) for row in rows(GroupMemberRow)),
            "appointments": sorted(row.title for row in rows(AppointmentRow)),
            "availability": len(rows(AvailabilityEntryRow)),
            "helpers": len(rows(HelperAssignmentRow)),
            "notes": sorted(row.text for row in rows(AppointmentNoteRow)),
            "feed": sorted(row.kind for row in rows(FamilyActivityRow)),
        }


def test_postgres_runs_the_demo_story_twice_over_the_seeded_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seeded group's rows hold foreign keys to its members and appointments, and PostgreSQL
    enforces them where SQLite as configured here may not: the run has to delete them in order."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        repository.reset()
        FamilyGroups(repository.sessions, repository).ensure_demo_group()
        calendar = FamilyCalendarStore(repository.sessions)
        calendar.reset_demo(
            DEMO_PERSON_ID,
            local_date(datetime.now(UTC)),
            {sub: relationship for sub, (_, relationship) in DEMO_FAMILY.items()},
        )
        seeded = _story_rows(repository)
        assert seeded["availability"] and seeded["helpers"] and seeded["feed"]
        with repository.sessions() as session:
            group_id = session.scalar(
                select(CareGroupRow.group_id).where(CareGroupRow.person_id == DEMO_PERSON_ID)
            )
            appointment_id = session.scalar(
                select(AppointmentRow.appointment_id).where(AppointmentRow.group_id == group_id)
            )
            on_date = session.scalar(
                select(AppointmentRow.start_date).where(
                    AppointmentRow.appointment_id == appointment_id
                )
            )
        calendar.add_note(
            DEMO_FAMILY_SUB,
            group_id,
            appointment_id,
            AppointmentNoteRequest(date=on_date, text=CLEARED_NOTE),
        )
        assert CLEARED_NOTE in _story_rows(repository)["notes"]
        subs = _story_logins(repository, monkeypatch)
        settings = _story_settings(database_url)

        first = demo_story.run(settings)
        after_first = _story_rows(repository)
        second = demo_story.run(settings)
        after_second = _story_rows(repository)

        assert after_second == after_first
        assert after_first["created_by"] == subs["sarah"]
        # A re-run on a used database finds the previous run's link, which is not a seeded one.
        seeded_link = str(seeded["linked_by"]).startswith("demo-")
        assert after_first["linked_by"] == (subs["sarah"] if seeded_link else seeded["linked_by"])
        assert {member[0] for member in after_first["members"]} == {
            subs["sarah"],
            subs["john"],
            subs["emily"],
        }
        assert CLEARED_NOTE not in after_first["notes"]
        assert after_first["availability"] and after_first["helpers"] and after_first["feed"]
        assert first.landing.lim_group_id == second.landing.lim_group_id
        assert first.landing.tan_group_id != second.landing.tan_group_id
        waiting = [
            row
            for row in repository.list_interventions(person_id=DEMO_PERSON_ID)
            if row.status == "proposed"
        ]
        assert [row.title for row in waiting] == [second.mdm_lim.suggestion_title]
        state = repository.person_state(person_id=DEMO_PERSON_ID)
        assert state.last_decision == "programme_suggestion"
        with repository.sessions() as session:
            assert session.get(CareGroupRow, first.landing.tan_group_id) is None
            assert session.get(CareGroupRow, second.landing.tan_group_id) is not None

        # A failure in the group transaction rolls the whole of it back on the real engine.
        def fails_half_way(*args: object, **kwargs: object) -> None:
            real_seed(*args, **kwargs)
            raise RuntimeError("stopped half way")

        real_seed = demo_story._seed_mr_tan
        monkeypatch.setattr(demo_story, "_seed_mr_tan", fails_half_way)
        with pytest.raises(RuntimeError, match="stopped half way"):
            demo_story.run(settings)
        assert _story_rows(repository) == after_second
        with repository.sessions() as session:
            assert session.get(CareGroupRow, second.landing.tan_group_id) is not None
    finally:
        repository.close()


# ── What Alembic owns on PostgreSQL, checked against the live catalogue ───────────────────────

_NEW_TABLES = ("activity_offer_responses", "plan_follow_through", "plan_enjoyment")


def test_postgres_carries_the_closed_loop_schema_alembic_claims_to_create() -> None:
    """The SQLite suite proves the models behave; it cannot prove the migration chain produces
    this schema on the engine the shared runtime actually uses. Constraint names, trigger
    dialects and `batch_alter_table` rewrites are exactly where SQLite and PostgreSQL diverge.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions() as session:
            present = set(
                session.scalars(
                    text(
                        "select tablename from pg_tables "
                        "where schemaname = 'public' and tablename = any(:names)"
                    ).bindparams(names=list(_NEW_TABLES))
                )
            )
            assert present == set(_NEW_TABLES)

            # The constraint swap: `source` joins the key so a stated preference and a learned
            # one about the same value are two rows rather than one clobbering the other.
            constraints = set(
                session.scalars(
                    text(
                        "select conname from pg_constraint "
                        "where conrelid = 'public.activity_dimension_preferences'::regclass"
                    )
                )
            )
            assert "uq_activity_dimension_person_value_source" in constraints
            assert "uq_activity_dimension_person_value" not in constraints

            columns = set(
                session.scalars(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name = 'activity_dimension_preferences'"
                    )
                )
            )
            assert {"expires_at", "stated_text", "first_observed_at"} <= columns

            # Append-only triggers are written per dialect; this is the half SQLite never runs.
            for table in _NEW_TABLES:
                triggers = set(
                    session.scalars(
                        text(
                            "select tgname from pg_trigger "
                            "where tgrelid = ('public.' || :t)::regclass and not tgisinternal"
                        ).bindparams(t=table)
                    )
                )
                assert triggers, f"{table} has no append-only trigger on PostgreSQL"
    finally:
        repository.close()


def test_postgres_append_only_triggers_are_bound_to_update_and_delete() -> None:
    """A trigger that exists but is wired to the wrong events enforces nothing.

    `pg_trigger.tgtype` is a bitmask: 1 is FOR EACH ROW, 2 is BEFORE, 8 is DELETE, 16 is UPDATE.
    Reading it is the only way to assert the wiring without a row to fire on.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions() as session:
            for table in _NEW_TABLES:
                tgtypes = list(
                    session.scalars(
                        text(
                            "select tgtype from pg_trigger "
                            "where tgrelid = ('public.' || :t)::regclass and not tgisinternal"
                        ).bindparams(t=table)
                    )
                )
                assert tgtypes, f"{table} has no append-only trigger"
                covered_update = any(t & 16 for t in tgtypes)
                covered_delete = any(t & 8 for t in tgtypes)
                assert covered_update, f"{table} has no BEFORE UPDATE trigger"
                assert covered_delete, f"{table} has no BEFORE DELETE trigger"
                assert all(t & 1 for t in tgtypes), f"{table} trigger is not FOR EACH ROW"
                assert all(t & 2 for t in tgtypes), f"{table} trigger is not BEFORE"
    finally:
        repository.close()


def test_postgres_append_only_trigger_actually_fires_on_a_real_row() -> None:
    """The wiring assertion above cannot prove the trigger runs, and the trigger is FOR EACH ROW,
    so a statement against an empty table never fires it -- an earlier version of this test
    asserted a raise on empty tables and therefore proved nothing.

    `activity_offer_responses` is the one of the three that can be populated in a couple of calls,
    so it carries the live proof; the other two are covered structurally above.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        repository.reset()
        results = repository.search_activities(
            text=None, intent=None, person_id=DEMO_PERSON_ID, actor=DEMO_PERSON_ID
        ).results
        assert results, "the fixture catalogue must return something to respond to"
        repository.respond_to_activity(
            results[0].candidate.activity_id,
            "not_for_me",
            reason="too_far",
            actor=DEMO_PERSON_ID,
            person_id=DEMO_PERSON_ID,
        )
        with repository.sessions() as session:
            assert session.scalar(text("select count(*) from public.activity_offer_responses")) == 1

        for statement in (
            "update public.activity_offer_responses set person_id = 'tampered'",
            "delete from public.activity_offer_responses",
        ):
            with (
                pytest.raises(DBAPIError, match="append-only"),
                repository.sessions.begin() as session,
            ):
                session.execute(text(statement))

        with repository.sessions() as session:
            assert session.scalar(text("select count(*) from public.activity_offer_responses")) == 1
    finally:
        repository.close()


# ── What the Supabase mirror owns, which Alembic never applies ────────────────────────────────


def _execute_plpgsql(session, statement: str) -> None:
    """Run a PL/pgSQL statement exactly as written, with no parameter handling at all.

    Neither of the obvious routes works here. `text()` reads a `:name` inside a `$$ ... $$` body
    as a bind parameter and emits a placeholder the server cannot type. `exec_driver_sql` hands
    the statement to psycopg with an empty parameter sequence, which makes psycopg parse the
    mirror's own `format('... %I ...', t)` calls as placeholders and reject `%I`.

    Going straight to the driver cursor with no parameters is the only path that leaves the file
    byte-for-byte as the operator would paste it into Supabase, which is the whole point of
    replaying it here.
    """
    raw = session.connection().connection
    with raw.cursor() as cursor:
        cursor.execute(statement)


def _ensure_data_api_roles(session) -> None:
    """`anon` and `authenticated` are Supabase's Data API roles and do not exist on a stock
    PostgreSQL server; create them so the grants and policies these files write are real
    rather than silently skipped."""
    _execute_plpgsql(
        session,
        "do $$ begin "
        "if not exists (select 1 from pg_roles where rolname = 'anon') "
        "then create role anon nologin; end if; "
        "if not exists (select 1 from pg_roles where rolname = 'authenticated') "
        "then create role authenticated nologin; end if; "
        "end $$",
    )


def test_the_supabase_mirror_replays_over_an_alembic_schema_and_denies_the_browser() -> None:
    """The failure this pins has already happened twice in production, both times recorded in
    `docs/supabase.md`: the API's lifespan runs `alembic upgrade head` on startup, so by the time
    the mirror is applied by hand the tables already exist, a plain `create table` aborts the
    transactional batch, and the RLS posture at the bottom of the file is never reached. Schema
    lands, security does not.

    So this applies the mirror over an Alembic-created schema, which is the situation that broke,
    and then twice, because a hand-applied file gets re-run. `anon` and `authenticated` are
    Supabase's Data API roles and do not exist on a stock server; they are created here so the
    grants and policies the mirror writes are real rather than skipped.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    mirror = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "supabase"
        / "migrations"
        / "202609120011_activity_responses.sql"
    )
    sql = mirror.read_text()

    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions.begin() as session:
            _ensure_data_api_roles(session)

        # Twice: idempotent replay is the property the previous two mirrors lacked.
        for _ in range(2):
            with repository.sessions.begin() as session:
                _execute_plpgsql(session, sql)

        with repository.sessions() as session:
            for table in _NEW_TABLES:
                enabled = session.scalar(
                    text(
                        "select relrowsecurity from pg_class "
                        "where oid = ('public.' || :t)::regclass"
                    ).bindparams(t=table)
                )
                assert enabled is True, f"RLS is not enabled on {table}"

                policies = set(
                    session.scalars(
                        text(
                            "select policyname from pg_policies "
                            "where schemaname = 'public' and tablename = :t"
                        ).bindparams(t=table)
                    )
                )
                assert "deny_browser_access" in policies, f"{table} has no deny policy"

                # Exactly one policy, and it denies: a second permissive policy would OR with it.
                assert policies == {"deny_browser_access"}, (table, policies)

                for role in ("anon", "authenticated"):
                    granted = session.scalar(
                        text(
                            "select count(*) from information_schema.role_table_grants "
                            "where table_schema = 'public' and table_name = :t and grantee = :r"
                        ).bindparams(t=table, r=role)
                    )
                    assert granted == 0, f"{role} still holds a grant on {table}"

                # FastAPI connects as the owner and must keep its bypass, so the mirror
                # deliberately does not force RLS. Pin that, or the API loses its own tables.
                forced = session.scalar(
                    text(
                        "select relforcerowsecurity from pg_class "
                        "where oid = ('public.' || :t)::regclass"
                    ).bindparams(t=table)
                )
                assert forced is False, f"{table} forces RLS; the API owner would be locked out"
    finally:
        repository.close()


# ── The consolidated RLS posture script: closes the gap in one step, on any prior state ────────

_RLS_POSTURE_APPLY_SQL = (
    Path(__file__).resolve().parents[3] / "infra" / "supabase" / "rls_posture_apply.sql"
)
_RLS_POSTURE_CHECK_SQL = (
    Path(__file__).resolve().parents[3] / "infra" / "supabase" / "rls_posture_check.sql"
)


def test_rls_posture_apply_closes_the_gap_on_every_orm_table_and_the_check_reports_it() -> None:
    """`infra/supabase/rls_posture_apply.sql` is the one-step fix for the RLS gap recorded in
    `docs/WAYFINDER.md`: ten tables live on the shared project with RLS disabled and no
    policy because concatenating the historical, partly non-idempotent mirrors into one
    script rolled back partway through. This test applies the file over a schema Alembic
    built from nothing -- the same situation that broke the mirror -- and does it twice,
    since a hand-applied file gets re-run. It then runs the companion read-only check query
    and asserts it reports every table green, proving the check would actually have caught
    the gap this closes.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    apply_sql = _RLS_POSTURE_APPLY_SQL.read_text()
    tables = sorted(Base.metadata.tables.keys())

    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions.begin() as session:
            _ensure_data_api_roles(session)

        # Twice: this is the specific property the gap-causing mirrors lacked.
        for _ in range(2):
            with repository.sessions.begin() as session:
                _execute_plpgsql(session, apply_sql)

        with repository.sessions() as session:
            for table in tables:
                enabled = session.scalar(
                    text(
                        "select relrowsecurity from pg_class "
                        "where oid = ('public.' || :t)::regclass"
                    ).bindparams(t=table)
                )
                assert enabled is True, f"RLS is not enabled on {table}"

                forced = session.scalar(
                    text(
                        "select relforcerowsecurity from pg_class "
                        "where oid = ('public.' || :t)::regclass"
                    ).bindparams(t=table)
                )
                assert forced is False, f"{table} forces RLS; the API owner would be locked out"

                policies = set(
                    session.scalars(
                        text(
                            "select policyname from pg_policies "
                            "where schemaname = 'public' and tablename = :t"
                        ).bindparams(t=table)
                    )
                )
                assert policies == {"deny_browser_access"}, (table, policies)

                for role in ("anon", "authenticated"):
                    granted = session.scalar(
                        text(
                            "select count(*) from information_schema.role_table_grants "
                            "where table_schema = 'public' and table_name = :t and grantee = :r"
                        ).bindparams(t=table, r=role)
                    )
                    assert granted == 0, f"{role} still holds a grant on {table}"

            # The read-only check query is the human's before/after tool; if it disagreed
            # with the assertions above, a human running it would be misled.
            check_rows = session.execute(text(_RLS_POSTURE_CHECK_SQL.read_text())).mappings().all()
            reported = {row["table_name"]: row for row in check_rows}
            for table in tables:
                assert table in reported, f"{table} missing from the posture check report"
                row = reported[table]
                assert row["rls_enabled"] is True, row
                assert row["rls_forced"] is False, row
                assert list(row["policies"]) == ["deny_browser_access"], row
                assert list(row["anon_or_auth_grants"]) == [], row
    finally:
        repository.close()


def test_the_startup_posture_closes_the_gap_with_no_mirror_and_no_manual_script() -> None:
    """The gap the apply script closed by hand, closed by the code path that creates the tables.

    Every earlier posture test here applies a file the way an operator would. This one never
    does: `upgrade_database` (what the lifespan runs on every start) followed by
    `apply_rls_posture` (what the lifespan now runs immediately afterwards), and nothing else.
    That is the situation `docs/supabase.md` records three times -- Alembic created the tables,
    Supabase's `ALTER DEFAULT PRIVILEGES` granted `anon`/`authenticated` on them, and the posture
    waited on a human.

    `anon` and `authenticated` do not exist on a stock PostgreSQL server, so they are created
    first: without them the apply script's `revoke` aborts its own `do $$` block and the whole
    posture rolls back, which is a real caveat for a non-Supabase PostgreSQL and is documented in
    `docs/supabase.md` rather than papered over here.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)

    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions.begin() as session:
            _ensure_data_api_roles(session)
            # Undo any posture a previously-run test in this module left behind, so this test
            # really does start from "Alembic created it and nothing else happened".
            for table in sorted(Base.metadata.tables):
                _execute_plpgsql(
                    session,
                    f"drop policy if exists deny_browser_access on public.{table}; "
                    f"alter table public.{table} disable row level security",
                )

        # Twice, because the lifespan runs on every start, not only the first.
        for _ in range(2):
            apply_rls_posture(database_url)

        with repository.sessions() as session:
            for table in sorted(Base.metadata.tables):
                enabled = session.scalar(
                    text(
                        "select relrowsecurity from pg_class "
                        "where oid = ('public.' || :t)::regclass"
                    ).bindparams(t=table)
                )
                assert enabled is True, f"RLS is not enabled on {table}"

                policies = set(
                    session.scalars(
                        text(
                            "select policyname from pg_policies "
                            "where schemaname = 'public' and tablename = :t"
                        ).bindparams(t=table)
                    )
                )
                assert policies == {"deny_browser_access"}, (table, policies)

        assert repository.readiness("shared").tables_without_rls == []
    finally:
        repository.close()


def test_readiness_names_a_table_someone_opened_by_hand() -> None:
    """A posture that is established but never checked is a posture nobody notices losing. The
    apply runs at startup; drift after that -- a `disable row level security` run in a SQL
    console, a table created outside Alembic -- is only visible if `/ready` looks."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)

    repository = SqlAlchemyRepository(database_url)
    opened = "interventions"
    try:
        with repository.sessions.begin() as session:
            _ensure_data_api_roles(session)
        apply_rls_posture(database_url)
        assert repository.readiness("shared").status == "ready"

        with repository.sessions.begin() as session:
            _execute_plpgsql(session, f"alter table public.{opened} disable row level security")

        posture = repository.readiness("shared")
        assert posture.tables_without_rls == [opened]
        assert posture.status == "not_ready", (
            "an open table must make the service report itself unready, not merely annotate it"
        )
        assert posture.database_connected is True

        # And the next start closes it again rather than needing a human.
        apply_rls_posture(database_url)
        assert repository.readiness("shared").tables_without_rls == []
    finally:
        with repository.sessions.begin() as session:
            _execute_plpgsql(session, f"alter table public.{opened} enable row level security")
        repository.close()


def test_the_dimension_preference_run_scope_mirror_replays_twice_over_an_alembic_schema() -> None:
    """Same property, same reason, as the mirror test above: this file is hand-applied against a
    database the API's lifespan has already migrated, so it must survive both a schema that
    already has the column (idempotent `add column if not exists`) and being run a second time,
    which is exactly what happens when an operator re-pastes a migration by hand.

    Unlike the previous mirror this revision adds no table, so there is no fresh RLS/deny posture
    to assert here -- `activity_dimension_preferences` has carried both since
    `202609060007_activity_catalogue.sql`, and `test_supabase_mirror.py` already pins that every
    table keeps them. What is specific to this file is the column, its foreign key, its index and
    the backfill: a row inserted with `run_id = NULL` before the mirror runs -- standing in for
    data that arrived between the Alembic migration and the hand-applied mirror -- must come out
    the other side backfilled exactly the way `_preference_inactive` requires, not left to read as
    a standing belief by accident.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    mirror = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "supabase"
        / "migrations"
        / "202609130012_dimension_preference_run_scope.sql"
    )
    sql = mirror.read_text()

    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions.begin() as session:
            _ensure_data_api_roles(session)

        reset = repository.reset()
        person_id = reset.state.person_id
        with repository.sessions.begin() as session:
            run_id = session.scalar(
                text(
                    "select run_id from scenario_runs "
                    "where person_id = :person_id and active = true"
                ).bindparams(person_id=person_id)
            )
            assert run_id is not None, "reset() must always leave an active run behind"
            # Plain parameterised statements, not `_execute_plpgsql`: no `$$` body and no `%I`
            # here, so the normal SQLAlchemy `text()` bind-param path is the right one -- psycopg
            # would otherwise read a literal `%` in a string value as its own placeholder.
            session.execute(
                text(
                    "insert into activity_dimension_preferences "
                    "(preference_id, person_id, dimension, value, strength, source, confirmed, "
                    "observations, updated_at, run_id) "
                    "values ('mirror-legacy-inferred', :person_id, 'distance', 'far', -0.3, "
                    "'decline_reason', false, 1, now(), NULL)"
                ).bindparams(person_id=person_id)
            )
            session.execute(
                text(
                    "insert into activity_dimension_preferences "
                    "(preference_id, person_id, dimension, value, strength, source, confirmed, "
                    "observations, updated_at, run_id) "
                    "values ('mirror-legacy-standing', :person_id, 'environment', 'outdoor', "
                    "-1.0, 'senior_statement', true, 1, now(), NULL)"
                ).bindparams(person_id=person_id)
            )

        # Twice: idempotent replay is the property the mirror directory did not always have.
        for _ in range(2):
            with repository.sessions.begin() as session:
                _execute_plpgsql(session, sql)

        with repository.sessions() as session:
            columns = set(
                session.scalars(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name = 'activity_dimension_preferences'"
                    )
                )
            )
            assert "run_id" in columns

            constraints = set(
                session.scalars(
                    text(
                        "select conname from pg_constraint "
                        "where conrelid = 'public.activity_dimension_preferences'::regclass"
                    )
                )
            )
            assert "fk_activity_dimension_preferences_run_id" in constraints

            indexes = set(
                session.scalars(
                    text(
                        "select indexname from pg_indexes "
                        "where tablename = 'activity_dimension_preferences'"
                    )
                )
            )
            assert "ix_activity_dimension_preferences_run_id" in indexes

            version = session.scalar(text("select version_num from public.alembic_version"))
            assert version == "c1e5a8f2d640"

            # A decline_reason row is never standing: the mirror's backfill must catch it even
            # though Alembic's own backfill already ran before this row ever existed.
            inferred_run_id = session.scalar(
                text(
                    "select run_id from activity_dimension_preferences "
                    "where preference_id = 'mirror-legacy-inferred'"
                )
            )
            assert inferred_run_id == run_id

            # A standing senior_statement row (no expires_at) is never run-scoped and must stay
            # NULL -- the mirror's backfill predicate must not touch it.
            standing_run_id = session.scalar(
                text(
                    "select run_id from activity_dimension_preferences "
                    "where preference_id = 'mirror-legacy-standing'"
                )
            )
            assert standing_run_id is None
    finally:
        repository.close()


def test_the_replan_offer_mirror_replays_twice_and_leaves_the_table_answerable() -> None:
    """`202609130015_replan_offers.sql`, hand-applied over a schema Alembic already migrated.

    Two properties are specific to this file. The first is the usual one: a new table needs RLS
    plus exactly one deny policy for the Data API roles, established even though the table already
    exists by the time an operator pastes the file in, and still correct when they paste it twice.

    The second is the opposite of what every other evidence table wants. An offer is *resolved in
    place* -- accepted, declined, expired -- so this table must NOT carry the append-only trigger
    `activity_offer_responses`, `plan_follow_through` and `plan_enjoyment` carry; installing one
    would block the very update the offer store exists for. That is asserted against `pg_trigger`
    rather than by attempting an update, because a `for each row` trigger never fires on a table
    with no rows and an empty update would pass either way.
    """
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    mirror = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "supabase"
        / "migrations"
        / "202609130015_replan_offers.sql"
    )
    sql = mirror.read_text()

    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions.begin() as session:
            _ensure_data_api_roles(session)

        for _ in range(2):
            with repository.sessions.begin() as session:
                _execute_plpgsql(session, sql)

        with repository.sessions() as session:
            enabled = session.scalar(
                text(
                    "select relrowsecurity from pg_class "
                    "where oid = 'public.replan_offers'::regclass"
                )
            )
            assert enabled is True, "RLS is not enabled on replan_offers"

            policies = set(
                session.scalars(
                    text(
                        "select policyname from pg_policies "
                        "where schemaname = 'public' and tablename = 'replan_offers'"
                    )
                )
            )
            # Exactly one policy, and it denies: a second permissive policy would OR with it.
            assert policies == {"deny_browser_access"}, policies

            for role in ("anon", "authenticated"):
                granted = session.scalar(
                    text(
                        "select count(*) from information_schema.role_table_grants "
                        "where table_schema = 'public' and table_name = 'replan_offers' "
                        "and grantee = :r"
                    ).bindparams(r=role)
                )
                assert granted == 0, f"{role} still holds a grant on replan_offers"

            forced = session.scalar(
                text(
                    "select relforcerowsecurity from pg_class "
                    "where oid = 'public.replan_offers'::regclass"
                )
            )
            assert forced is False, "replan_offers forces RLS; the API owner would be locked out"

            triggers = set(
                session.scalars(
                    text(
                        "select tgname from pg_trigger "
                        "where tgrelid = 'public.replan_offers'::regclass "
                        "and not tgisinternal"
                    )
                )
            )
            assert triggers == set(), (
                f"replan_offers carries a trigger ({sorted(triggers)}); an offer is resolved "
                "in place and an append-only guard would block that update"
            )

            # The column the replace route writes, alongside `replaced_reason`.
            column = session.scalar(
                text(
                    "select data_type from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'week_plan_entries' "
                    "and column_name = 'replaced_by_plan_id'"
                )
            )
            assert column is not None, (
                "the mirror did not add week_plan_entries.replaced_by_plan_id"
            )
    finally:
        repository.close()


def test_postgres_demo_reset_clears_the_family_feed_before_the_members_it_points_at() -> None:
    """The feed's rows reference `group_members` by foreign key. SQLite does not enforce those by
    default, so only PostgreSQL proves the demo reset deletes in an order the database accepts, and
    that the feed pages by cursor afterwards."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        repository.reset()
        groups = FamilyGroups(repository.sessions, repository)
        calendar = FamilyCalendarStore(repository.sessions)
        demo_members = {sub: relationship for sub, (_, relationship) in DEMO_FAMILY.items()}
        groups.ensure_demo_group()
        calendar.reset_demo(DEMO_PERSON_ID, date.today(), demo_members)
        group_id = groups.me(DEMO_FAMILY_SUB, None, None).groups[0].group_id

        # A newcomer joins, is approved, and checks in: their feed rows reference their member row.
        newcomer = "demo-family-pg-newcomer"
        pin = groups.create_join_pin(DEMO_FAMILY_SUB, group_id).pin
        groups.join_group(newcomer, pin, "Nephew")
        pending = next(
            m for m in groups.group(DEMO_FAMILY_SUB, group_id).members if m.status == "pending"
        )
        groups.approve(DEMO_FAMILY_SUB, group_id, pending.member_id)
        calendar.check_in(newcomer, group_id, CheckInRequest(kind=CheckInKind.VISITED, note="hi"))
        assert len(calendar.activity(DEMO_FAMILY_SUB, group_id, 50, None).entries) == 8

        calendar.reset_demo(DEMO_PERSON_ID, date.today(), demo_members)

        first = calendar.activity(DEMO_FAMILY_SUB, group_id, 3, None)
        assert len(first.entries) == 3 and first.next_before is not None
        second = calendar.activity(DEMO_FAMILY_SUB, group_id, 3, first.next_before)
        assert len(second.entries) == 3 and second.next_before is None
        seen = [entry.activity_id for entry in [*first.entries, *second.entries]]
        assert len(set(seen)) == 6
        assert {entry.origin for entry in [*first.entries, *second.entries]} == {"demo_seed"}
    finally:
        repository.close()


def test_postgres_deleting_an_appointment_and_the_demo_reset_clear_notes_first() -> None:
    """Notes point at appointments and members by foreign key, which SQLite does not enforce by
    default. Only PostgreSQL proves that deleting an appointment, and the demo reset, remove the
    notes before the rows they reference, and that a feed entry about a note carries no text."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        repository.reset()
        groups = FamilyGroups(repository.sessions, repository)
        calendar = FamilyCalendarStore(repository.sessions)
        demo_members = {sub: relationship for sub, (_, relationship) in DEMO_FAMILY.items()}
        groups.ensure_demo_group()
        calendar.reset_demo(DEMO_PERSON_ID, date.today(), demo_members)
        group_id = groups.me(DEMO_FAMILY_SUB, None, None).groups[0].group_id

        day = date.today()
        appointment = calendar.create_appointment(
            DEMO_FAMILY_SUB,
            group_id,
            AppointmentRequest(
                title="Dentist", kind="medical", date=day, start="09:00", end="10:00"
            ),
        )
        note = calendar.add_note(
            DEMO_FAMILY_SUB,
            group_id,
            appointment.appointment_id,
            AppointmentNoteRequest(date=day, text="locker code 4417"),
        )
        assert calendar.list_notes(DEMO_FAMILY_SUB, group_id, appointment.appointment_id, day) == [
            note
        ]
        with repository.sessions() as session:
            feed = session.execute(
                text("select note from family_activity where kind = 'note_added'")
            ).all()
            assert feed and all(row.note is None for row in feed)

        # Deleting the appointment removes its notes first (the foreign key).
        calendar.delete_appointment(DEMO_FAMILY_SUB, group_id, appointment.appointment_id)
        with repository.sessions() as session:
            assert note.note_id not in set(session.scalars(select(AppointmentNoteRow.note_id)))

        # A note on a seeded appointment, by a member the reset removes, is cleared by the reset.
        newcomer = "demo-family-pg-note-newcomer"
        pin = groups.create_join_pin(DEMO_FAMILY_SUB, group_id).pin
        groups.join_group(newcomer, pin, "Nephew")
        pending = next(
            m for m in groups.group(DEMO_FAMILY_SUB, group_id).members if m.status == "pending"
        )
        groups.approve(DEMO_FAMILY_SUB, group_id, pending.member_id)
        calendar.add_note(
            newcomer,
            group_id,
            "demo-doctor",
            AppointmentNoteRequest(date=day + timedelta(days=1), text="hello"),
        )
        for _ in range(2):
            calendar.reset_demo(DEMO_PERSON_ID, date.today(), demo_members)
            with repository.sessions() as session:
                texts = list(session.scalars(select(AppointmentNoteRow.text)))
            assert texts == ["I'll bring her NRIC and health booklet, they're in the blue folder."]
    finally:
        repository.close()


def test_the_unlinked_groups_mirror_replays_twice_over_an_alembic_schema() -> None:
    """`202610290025_unlinked_groups.sql`, hand-applied over a schema Alembic already migrated,
    and again. It adds no table, so there is no new RLS posture: what is specific to it is the
    columns, the backfill and the two dropped NOT NULLs."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    mirror = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "supabase"
        / "migrations"
        / "202610290025_unlinked_groups.sql"
    )
    sql = mirror.read_text()

    repository = SqlAlchemyRepository(database_url)
    try:
        for _ in range(2):
            with repository.sessions.begin() as session:
                _execute_plpgsql(session, sql)

        with repository.sessions() as session:
            nullable = dict(
                session.execute(
                    text(
                        "select column_name, is_nullable from information_schema.columns "
                        "where table_schema = 'public' and table_name = 'care_groups'"
                    )
                ).all()
            )
            assert nullable["person_id"] == "YES"
            assert nullable["linked_via"] == "YES"
            assert nullable["senior_name"] == "NO"
            assert {"linked_at", "linked_by"} <= set(nullable)
            version = session.scalar(text("select version_num from public.alembic_version"))
            assert version == expected_database_revision()
    finally:
        repository.close()


def test_the_last_opened_mirror_replays_twice_over_an_alembic_schema() -> None:
    """`202610300026_group_member_last_opened.sql`, hand-applied over a schema Alembic already
    migrated, and again: one nullable, timezone-aware column, no new RLS posture."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    mirror = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "supabase"
        / "migrations"
        / "202610300026_group_member_last_opened.sql"
    )
    sql = mirror.read_text()

    repository = SqlAlchemyRepository(database_url)
    try:
        for _ in range(2):
            with repository.sessions.begin() as session:
                _execute_plpgsql(session, sql)

        with repository.sessions() as session:
            column = session.execute(
                text(
                    "select data_type, is_nullable from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'group_members' "
                    "and column_name = 'last_opened_at'"
                )
            ).one()
            assert tuple(column) == ("timestamp with time zone", "YES")
            version = session.scalar(text("select version_num from public.alembic_version"))
            assert version == expected_database_revision()
    finally:
        repository.close()


def test_the_last_opened_mirror_adds_the_column_to_a_schema_stopped_before_it() -> None:
    """The replay above runs over a schema that already has the column, so both statements are
    no-ops there. Here the schema stops at `f3a9c1e7b254`, as a Supabase database that has not had
    this change yet, and the mirror alone must add the column and move the version marker. Going
    down from head rather than up to the revision, because the database may already be at head."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    mirror = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "supabase"
        / "migrations"
        / "202610300026_group_member_last_opened.sql"
    )
    column_query = text(
        "select data_type, is_nullable from information_schema.columns "
        "where table_schema = 'public' and table_name = 'group_members' "
        "and column_name = 'last_opened_at'"
    )
    version_query = text("select version_num from public.alembic_version")

    command.downgrade(config, "f3a9c1e7b254")
    repository = SqlAlchemyRepository(database_url)
    try:
        with repository.sessions() as session:
            assert session.execute(column_query).first() is None
            assert session.scalar(version_query) == "f3a9c1e7b254"

        with repository.sessions.begin() as session:
            _execute_plpgsql(session, mirror.read_text())

        with repository.sessions() as session:
            column = session.execute(column_query).one()
            assert tuple(column) == ("timestamp with time zone", "YES")
            assert session.scalar(version_query) == "c1e5a8f2d640"
    finally:
        repository.close()
        # The other tests in this file expect head.
        upgrade_database(database_url)


def test_postgres_demo_reset_removes_unlinked_demo_groups_children_first() -> None:
    """With foreign keys enforced: a group a demo account created with no senior linked, holding
    an appointment, a note, availability, a helper, a PIN and feed entries, is removed whole by
    the demo reset."""
    database_url = dedicated_postgres_test_url()
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    try:
        repository.reset()
        groups = FamilyGroups(repository.sessions, repository)
        calendar = FamilyCalendarStore(repository.sessions)
        demo_members = {sub: relationship for sub, (_, relationship) in DEMO_FAMILY.items()}
        groups.ensure_demo_group()
        calendar.reset_demo(DEMO_PERSON_ID, date.today(), demo_members)

        unlinked = groups.create_group(DEMO_FAMILY_SUB, "Daughter", senior_name="Mr Ong")
        day = date.today() + timedelta(days=2)
        appointment = calendar.create_appointment(
            DEMO_FAMILY_SUB,
            unlinked.group_id,
            AppointmentRequest(
                title="Haircut", kind="errand", date=day, start="09:00", end="10:00"
            ),
        )
        calendar.add_note(
            DEMO_FAMILY_SUB,
            unlinked.group_id,
            appointment.appointment_id,
            AppointmentNoteRequest(date=day, text="ask for a short trim"),
        )
        calendar.volunteer(
            DEMO_FAMILY_SUB, unlinked.group_id, f"{appointment.appointment_id}@{day.isoformat()}"
        )
        groups.create_join_pin(DEMO_FAMILY_SUB, unlinked.group_id)

        calendar.reset_demo(DEMO_PERSON_ID, date.today(), demo_members)
        with repository.sessions() as session:
            left = session.scalar(
                text("select count(*) from care_groups where group_id = :g").bindparams(
                    g=unlinked.group_id
                )
            )
        assert left == 0
        first = groups.me(DEMO_FAMILY_SUB, None, None).groups[0]
        assert first.person_id == DEMO_PERSON_ID
    finally:
        repository.close()
