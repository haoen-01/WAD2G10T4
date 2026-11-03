"""The server remembers each member's last opened family group (issue #17).

`POST /v1/groups/{id}/open` sets it, creating a group sets it, and `GET /v1/me` reports it as
`last_opened`, with `member_count` for the groups page. Foreign keys are enforced (the `repo`
fixture from `test_family_activity`), so the demo reset runs as on PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.db_models import GroupMemberRow
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_family_activity import repo  # noqa: F401 - pytest fixture (foreign keys on)
from tests.test_family_calendar import demo  # noqa: F401 - pytest fixture
from tests.test_family_groups import (
    _group_with_owner,
    _headers,
    _join_pin,
    _onboard,
    _senior_pin,
    client,  # noqa: F401 - pytest fixture
)
from tests.test_family_unlinked_groups import OWNER, _add_member, _create_unlinked, _kinds, _link


def _second_group(client: TestClient, sub: str = OWNER, name: str = "Mr Ong") -> str:  # noqa: F811
    response = client.post(
        "/v1/groups",
        json={"senior_name": name, "relationship": "Son"},
        headers=_headers(sub),
    )
    assert response.status_code == 201, response.text
    return response.json()["group_id"]


def _join_as_pending(client: TestClient, group_id: str, sub: str) -> str:  # noqa: F811
    """For an account that is already set up (`_add_member` onboards a new one)."""
    joined = client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers(sub),
    )
    assert joined.status_code == 200, joined.text
    group = client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()
    return next(m["member_id"] for m in group["members"] if m["status"] == "pending")


def _open(client: TestClient, group_id: str, sub: str = OWNER):  # noqa: F811
    return client.post(f"/v1/groups/{group_id}/open", headers=_headers(sub))


def _groups(client: TestClient, sub: str = OWNER) -> dict[str, dict]:  # noqa: F811
    me = client.get("/v1/me", headers=_headers(sub))
    assert me.status_code == 200, me.text
    return {group["group_id"]: group for group in me.json()["groups"]}


def _current(client: TestClient, sub: str = OWNER) -> list[str]:  # noqa: F811
    return [group_id for group_id, group in _groups(client, sub).items() if group["last_opened"]]


def _opened_at(
    repo: SqlAlchemyRepository,  # noqa: F811
    group_id: str,
    sub: str = OWNER,
) -> datetime | None:
    with repo.sessions() as session:
        return session.scalar(
            select(GroupMemberRow.last_opened_at).where(
                GroupMemberRow.group_id == group_id, GroupMemberRow.sub == sub
            )
        )


def _set_opened_at(
    repo: SqlAlchemyRepository,  # noqa: F811
    group_id: str,
    sub: str,
    at: datetime | None,
) -> None:
    with repo.sessions.begin() as session:
        member = session.scalar(
            select(GroupMemberRow).where(
                GroupMemberRow.group_id == group_id, GroupMemberRow.sub == sub
            )
        )
        assert member is not None
        member.last_opened_at = at


# ── AC1: opening a group ──────────────────────────────────────────────────────


def test_opening_a_group_returns_204_with_no_body_and_makes_it_the_only_current_one(
    client: TestClient,  # noqa: F811
) -> None:
    first = _create_unlinked(client)["group_id"]
    second = _second_group(client)
    assert _current(client) == [second]

    response = _open(client, first)
    assert response.status_code == 204
    assert response.content == b""
    groups = _groups(client)
    assert groups[first]["last_opened"] is True
    assert groups[second]["last_opened"] is False

    assert _open(client, second).status_code == 204
    assert _current(client) == [second]


def test_opening_a_group_is_seen_by_another_session_of_the_same_account(
    client: TestClient,  # noqa: F811
) -> None:
    first = _create_unlinked(client)["group_id"]
    _second_group(client)
    assert _open(client, first).status_code == 204
    # A new token, as on another device: the current group lives on the server.
    assert client.get("/v1/me", headers=_headers(OWNER)).json()["groups"][0]["last_opened"] is True


def test_opening_needs_a_sign_in(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    assert client.post(f"/v1/groups/{group_id}/open").status_code == 401


# ── AC2: who cannot open ──────────────────────────────────────────────────────


def test_a_pending_member_cannot_open_the_group_and_nothing_is_written(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=False)

    assert _open(client, group_id, "family-b").status_code == 404
    assert _opened_at(repo, group_id, "family-b") is None


def test_a_non_member_cannot_open_the_group_and_nothing_is_written(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    before = _opened_at(repo, group_id)
    _onboard(client, "family-b", "family", "Jun")

    assert _open(client, group_id, "family-b").status_code == 404
    assert _opened_at(repo, group_id) == before
    with repo.sessions() as session:
        assert (
            session.scalars(select(GroupMemberRow).where(GroupMemberRow.sub == "family-b")).all()
            == []
        )


def test_a_senior_gets_404_not_403_even_for_their_own_group(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = _group_with_owner(client)
    before = _opened_at(repo, group_id)

    assert _open(client, group_id, "senior-1").status_code == 404
    assert _opened_at(repo, group_id) == before


def test_a_senior_token_on_an_owners_account_gets_the_same_404_and_nothing_is_written(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    """The token's role wins over the account's: this caller is a senior, though the account also
    holds an active membership. `GET /v1/groups/{id}` refuses them too, with 403."""
    group_id = _create_unlinked(client)["group_id"]
    before = _opened_at(repo, group_id)
    assert before is not None
    _onboard(client, "family-b", "family", "Jun")
    non_member = _open(client, group_id, "family-b")
    assert non_member.status_code == 404
    senior_token = _headers(OWNER, "senior")
    assert client.get(f"/v1/groups/{group_id}", headers=senior_token).status_code == 403

    response = client.post(f"/v1/groups/{group_id}/open", headers=senior_token)

    assert response.status_code == 404
    assert response.json() == non_member.json() == {"detail": "Group not found"}
    assert _opened_at(repo, group_id) == before


def test_an_account_with_no_role_yet_gets_404(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    assert _open(client, group_id, "brand-new").status_code == 404


def test_an_unknown_group_is_404(client: TestClient) -> None:  # noqa: F811
    _onboard(client, OWNER, "family", "Wei Ling")
    assert _open(client, "grp_missing").status_code == 404


# ── AC3: no feed entry ────────────────────────────────────────────────────────


def test_opening_adds_nothing_to_the_activity_feed(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    before = _kinds(client, group_id)
    assert _open(client, group_id).status_code == 204
    assert _kinds(client, group_id) == before == ["group_created"]


# ── AC4: member_count ─────────────────────────────────────────────────────────


def test_member_count_counts_active_members_only(client: TestClient) -> None:  # noqa: F811
    group_id = _create_unlinked(client)["group_id"]
    assert _groups(client)[group_id]["member_count"] == 1

    _add_member(client, group_id, "family-b", approve=False)
    assert _groups(client)[group_id]["member_count"] == 1
    # A pending member sees the same count on their own card.
    assert _groups(client, "family-b")[group_id]["member_count"] == 1

    pending = next(
        member
        for member in client.get(f"/v1/groups/{group_id}", headers=_headers(OWNER)).json()[
            "members"
        ]
        if member["status"] == "pending"
    )
    approved = client.post(
        f"/v1/groups/{group_id}/members/{pending['member_id']}/approve", headers=_headers(OWNER)
    )
    assert approved.status_code == 200, approved.text
    assert _groups(client)[group_id]["member_count"] == 2
    assert _groups(client, "family-b")[group_id]["member_count"] == 2


def test_member_count_is_worked_out_per_group(client: TestClient) -> None:  # noqa: F811
    first = _create_unlinked(client)["group_id"]
    second = _second_group(client)
    _add_member(client, first, "family-b", approve=True)

    groups = _groups(client)
    assert groups[first]["member_count"] == 2
    assert groups[second]["member_count"] == 1


def test_the_join_response_reports_the_active_count_and_is_not_current(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _onboard(client, "family-b", "family", "Jun")
    joined = client.post(
        "/v1/groups/join",
        json={"pin": _join_pin(client, group_id), "relationship": "Son"},
        headers=_headers("family-b"),
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["member_count"] == 1
    assert joined.json()["last_opened"] is False


# ── AC5: never opened ─────────────────────────────────────────────────────────


def test_memberships_never_opened_show_no_current_group(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    """As data from before the migration looks: every `last_opened_at` is NULL."""
    first = _create_unlinked(client)["group_id"]
    second = _second_group(client)
    _set_opened_at(repo, first, OWNER, None)
    _set_opened_at(repo, second, OWNER, None)

    assert [group["last_opened"] for group in _groups(client).values()] == [False, False]


def test_an_account_in_no_group_has_an_empty_list(client: TestClient) -> None:  # noqa: F811
    _onboard(client, OWNER, "family", "Wei Ling")
    assert _groups(client) == {}


# ── AC6: creating a group makes it current ────────────────────────────────────


def test_creating_an_unlinked_group_makes_it_current(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    first = _create_unlinked(client)["group_id"]
    assert _current(client) == [first]
    assert _opened_at(repo, first) is not None

    second = _second_group(client)
    assert _current(client) == [second]


def test_creating_a_group_with_the_senior_pin_makes_it_current(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    earlier = _create_unlinked(client)["group_id"]
    assert _current(client) == [earlier]
    _onboard(client, "senior-1", "senior", "Mdm Tan")
    created = client.post(
        "/v1/groups",
        json={"senior_pin": _senior_pin(client, "senior-1"), "relationship": "Daughter"},
        headers=_headers(OWNER),
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["group_id"]

    assert _current(client) == [group_id]
    assert _opened_at(repo, group_id) is not None


# ── AC7: what must not change the current group ───────────────────────────────


def test_joining_and_being_approved_leave_the_current_group_alone(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    theirs = _create_unlinked(client, "family-b", name="Mr Ong", display_name="Jun")["group_id"]
    group_id = _create_unlinked(client)["group_id"]
    assert _current(client, "family-b") == [theirs]

    member_id = _join_as_pending(client, group_id, "family-b")
    assert _current(client, "family-b") == [theirs]
    assert _groups(client, "family-b")[group_id]["last_opened"] is False
    assert _opened_at(repo, group_id, "family-b") is None

    approved = client.post(
        f"/v1/groups/{group_id}/members/{member_id}/approve", headers=_headers(OWNER)
    )
    assert approved.status_code == 200, approved.text
    assert _current(client, "family-b") == [theirs]
    assert _opened_at(repo, group_id, "family-b") is None
    # The approver is not moved either.
    assert _current(client) == [group_id]


def test_being_approved_with_no_other_group_does_not_mark_the_group_opened(
    client: TestClient,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=True)
    assert _current(client, "family-b") == []


def test_linking_a_senior_and_renaming_leave_the_current_group_alone(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    first = _create_unlinked(client)["group_id"]
    second = _second_group(client)
    assert _current(client) == [second]
    opened_at = _opened_at(repo, first)

    renamed = client.put(
        f"/v1/groups/{first}/senior-name",
        json={"senior_name": "Mdm Tan Ah Mui"},
        headers=_headers(OWNER),
    )
    assert renamed.status_code == 200, renamed.text
    assert _current(client) == [second]

    _onboard(client, "senior-1", "senior", "Mdm Tan")
    linked = _link(client, first, _senior_pin(client, "senior-1"))
    assert linked.status_code == 200, linked.text
    assert _current(client) == [second]
    assert _opened_at(repo, first) == opened_at


def test_a_pending_group_is_never_current_even_if_it_holds_a_later_time(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    theirs = _create_unlinked(client, "family-b", name="Mr Ong", display_name="Jun")["group_id"]
    group_id = _create_unlinked(client)["group_id"]
    _join_as_pending(client, group_id, "family-b")
    _set_opened_at(repo, theirs, "family-b", datetime(2026, 10, 1, tzinfo=UTC))
    _set_opened_at(repo, group_id, "family-b", datetime(2026, 10, 2, tzinfo=UTC))

    assert _current(client, "family-b") == [theirs]


def test_a_pending_group_alone_shows_nothing_current_even_with_a_time(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    group_id = _create_unlinked(client)["group_id"]
    _add_member(client, group_id, "family-b", approve=False)
    _set_opened_at(repo, group_id, "family-b", datetime(2026, 10, 2, tzinfo=UTC))

    assert _current(client, "family-b") == []


def test_an_exact_tie_picks_the_same_single_group_every_time(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    first = _create_unlinked(client)["group_id"]
    second = _second_group(client)
    third = _second_group(client, name="Mdm Koh")
    at = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    for group_id in (first, second, third):
        _set_opened_at(repo, group_id, OWNER, at)

    assert _current(client) == [max(first, second, third)]
    assert _current(client) == [max(first, second, third)]


# ── AC8: one member's open is theirs alone ────────────────────────────────────


def test_one_members_open_does_not_change_another_members_current_group(
    client: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    shared = _create_unlinked(client)["group_id"]
    other = _second_group(client)
    _add_member(client, shared, "family-b", approve=True)
    owner_time = _opened_at(repo, shared)

    assert _open(client, shared, "family-b").status_code == 204
    assert _current(client, "family-b") == [shared]
    assert _current(client) == [other]
    assert _opened_at(repo, shared) == owner_time


# ── AC9: the offline demo ─────────────────────────────────────────────────────


def test_the_demo_reset_clears_the_current_group_for_the_demo_family(
    demo: TestClient,  # noqa: F811
    repo: SqlAlchemyRepository,  # noqa: F811
) -> None:
    john = {"X-Demo-Sub": "demo-john"}
    [group] = demo.get("/v1/me").json()["groups"]
    group_id = group["group_id"]
    assert group["last_opened"] is False
    assert group["member_count"] == 3

    assert demo.post(f"/v1/groups/{group_id}/open").status_code == 204
    assert demo.post(f"/v1/groups/{group_id}/open", headers=john).status_code == 204
    assert demo.get("/v1/me").json()["groups"][0]["last_opened"] is True

    assert demo.post("/v1/demo/reset").status_code == 200
    with repo.sessions() as session:
        times = session.scalars(
            select(GroupMemberRow.last_opened_at).where(GroupMemberRow.group_id == group_id)
        ).all()
    assert times == [None, None, None]
    [after] = demo.get("/v1/me").json()["groups"]
    assert (after["group_id"], after["last_opened"]) == (group_id, False)


def test_the_demo_senior_cannot_open_the_demo_group(demo: TestClient) -> None:  # noqa: F811
    [group] = demo.get("/v1/me").json()["groups"]
    response = demo.post(
        f"/v1/groups/{group['group_id']}/open", headers={"X-Demo-Sub": "demo-senior"}
    )
    assert response.status_code == 404
