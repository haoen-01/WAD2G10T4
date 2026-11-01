"""Admin setup command: provision demo accounts in Supabase and link to application database.

Usage:
    uv run python -m silverloop.setup_demo_accounts [--allow-production]

Refuses to run when APP_ENV=production unless --allow-production is passed. This script
creates shared, well-known demo logins in a live identity provider; running it against a
production tenant by accident (for example with production admin credentials still exported
in the shell) would be difficult to undo.

Reads SUPABASE_URL, SUPABASE_SECRET_KEY, DATABASE_URL from environment.
Reads demo account passwords from SENIOR_PASSWORD, COORDINATOR_PASSWORD,
DEMO_OPERATOR_PASSWORD, SARAH_PASSWORD, JOHN_PASSWORD, EMILY_PASSWORD, WEIMING_PASSWORD and
AISHA_PASSWORD environment variables, or prompts securely if absent.

The senior, coordinator and demo-operator accounts keep their role in Supabase `app_metadata`.
The family accounts are set up the way a family member who signed up is: no role in `app_metadata`
and a row in `accounts`, which is where the display name `GET /v1/me` returns lives. Family groups
are not created here. Re-running updates every account instead of adding another.

Never commits or logs passwords. Never places person_id in Supabase user metadata.
"""

from __future__ import annotations

import getpass
import os
import sys
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from silverloop.config import Settings
from silverloop.family_groups import FamilyGroups
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

_ACCOUNTS = [
    {
        "env_key": "SENIOR_EMAIL",
        "default_email": "senior@silverloop.demo",
        "role": "senior",
        "password_env": "SENIOR_PASSWORD",
        "label": "Senior (Mdm Lim)",
    },
    {
        "env_key": "COORDINATOR_EMAIL",
        "default_email": "coordinator@silverloop.demo",
        "role": "coordinator",
        "password_env": "COORDINATOR_PASSWORD",
        "label": "Coordinator",
    },
    {
        "env_key": "DEMO_OPERATOR_EMAIL",
        "default_email": "demo-operator@silverloop.demo",
        "role": "demo_operator",
        "password_env": "DEMO_OPERATOR_PASSWORD",
        "label": "Demo Operator",
    },
    {
        "default_email": "sarah@silverloop.demo",
        "role": "family",
        "password_env": "SARAH_PASSWORD",
        "label": "Family (Sarah)",
        "display_name": "Sarah",
    },
    {
        "default_email": "john@silverloop.demo",
        "role": "family",
        "password_env": "JOHN_PASSWORD",
        "label": "Family (John)",
        "display_name": "John",
    },
    {
        "default_email": "emily@silverloop.demo",
        "role": "family",
        "password_env": "EMILY_PASSWORD",
        "label": "Family (Emily)",
        "display_name": "Emily",
    },
    {
        "default_email": "weiming@silverloop.demo",
        "role": "family",
        "password_env": "WEIMING_PASSWORD",
        "label": "Family (Wei Ming)",
        "display_name": "Wei Ming",
    },
    {
        "default_email": "aisha@silverloop.demo",
        "role": "family",
        "password_env": "AISHA_PASSWORD",
        "label": "Family (Aisha)",
        "display_name": "Aisha",
    },
]


def _account_email(account: dict[str, str]) -> str:
    """The fixed address, unless this account has an override and it is filled in. The family
    accounts have none: an override could point the update path at someone's real account."""
    override = os.environ.get(account.get("env_key", ""), "")
    return override if override.strip() else account["default_email"]


def _supabase_admin(supabase_url: str, secret_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=supabase_url.rstrip("/") + "/auth/v1/admin",
        headers={
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )


def _find_user_by_email(client: httpx.Client, email: str) -> dict | None:
    """Search all pages of admin users list for a matching email."""
    page = 1
    while True:
        resp = client.get("/users", params={"page": page, "per_page": 50})
        resp.raise_for_status()
        body = resp.json()
        users = body.get("users", [])
        for u in users:
            if u.get("email", "").lower() == email.lower():
                return u
        if len(users) < 50:
            return None
        page += 1


def _upsert_user(client: httpx.Client, email: str, password: str, role: str) -> str:
    """Create or update a Supabase user and set server-controlled role metadata. Returns sub.

    A family account's role lives in `accounts`, not the token. Supabase merges `app_metadata` on
    update and a null value removes the key, so a role left over on that user is cleared.
    """
    existing = _find_user_by_email(client, email)

    is_family = role == "family"

    if existing:
        user_id = existing["id"]
        resp = client.put(
            f"/users/{user_id}",
            json={"password": password, "app_metadata": {"role": None if is_family else role}},
        )
        resp.raise_for_status()
        print(f"  Updated: {email} (sub={user_id})")
        return user_id
    else:
        resp = client.post(
            "/users",
            json={
                "email": email,
                "password": password,
                "app_metadata": {} if is_family else {"role": role},
                "email_confirm": True,
            },
        )
        resp.raise_for_status()
        user_id = resp.json()["id"]
        print(f"  Created: {email} (sub={user_id})")
        return user_id


def _reject_production(settings: Settings, argv: list[str]) -> None:
    """Refuse to provision well-known demo logins against a production tenant."""
    if settings.app_env != "production":
        return
    if "--allow-production" in argv:
        print(
            "Warning: APP_ENV=production and --allow-production was passed; continuing.",
            file=sys.stderr,
        )
        return
    print(
        "Error: refusing to provision demo accounts while APP_ENV=production.\n"
        "This creates shared, well-known logins in a live identity provider. If that is "
        "genuinely intended, re-run with --allow-production.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _supabase_host(supabase_url: str) -> str:
    """Host only - never echo the key, and never the full URL with any query string."""
    return urlparse(supabase_url).hostname or supabase_url


def main() -> None:
    settings = Settings()
    _reject_production(settings, sys.argv[1:])

    supabase_url = os.environ.get("SUPABASE_URL", "")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY", "")

    if not supabase_url:
        print("Error: SUPABASE_URL is not set.", file=sys.stderr)
        raise SystemExit(1)
    if not secret_key:
        print("Error: SUPABASE_SECRET_KEY is not set.", file=sys.stderr)
        raise SystemExit(1)

    repo = SqlAlchemyRepository(settings.database_url)

    try:
        with repo.engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM auth_user_person_links LIMIT 1"))
            conn.execute(text("SELECT 1 FROM accounts LIMIT 1"))
    # SQLite reports a missing table as OperationalError; psycopg as ProgrammingError.
    except (OperationalError, ProgrammingError) as exc:
        print(
            "Error: auth_user_person_links or accounts table not found. "
            "Run 'alembic upgrade head' (or start the API server) before running this script.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print(f"Target Supabase host: {_supabase_host(supabase_url)}  (APP_ENV={settings.app_env})")

    family = FamilyGroups(repo.sessions, repo)

    with _supabase_admin(supabase_url, secret_key) as admin:
        for account in _ACCOUNTS:
            email = _account_email(account)
            password = os.environ.get(account["password_env"], "")
            if not password:
                password = getpass.getpass(f"Password for {account['label']} ({email}): ")
            if not password:
                print(f"  Skipping {email}: no password provided.", file=sys.stderr)
                continue

            print(f"\nProvisioning {account['label']}...")
            sub = _upsert_user(admin, email, password, account["role"])

            if account["role"] == "senior":
                repo.upsert_person_link(sub, DEMO_PERSON_ID, "setup_demo_accounts")
                print(f"  Linked {sub} -> person_id={DEMO_PERSON_ID}")
            elif account["role"] == "family":
                family.provision_family_account(sub, account["display_name"])
                print(f"  Family account ready: {account['display_name']}")

    print("\nSetup complete.")


if __name__ == "__main__":
    main()
