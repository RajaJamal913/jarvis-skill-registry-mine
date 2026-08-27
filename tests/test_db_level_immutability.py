"""
Proves the DB-level enforcement added in
alembic/versions/e4555f5a6782_db_level_immutability_triggers.py actually
works, by attempting the forbidden operations via raw SQL and asserting
Postgres itself rejects them - independent of any application code.

Skipped unless TEST_DATABASE_URL points at a real PostgreSQL database,
since SQLite never receives these triggers (see that migration's
docstring and ARCHITECTURE.md). Run against the docker-compose Postgres
service, or via the `test-postgres` job in .github/workflows/ci.yml:

    TEST_DATABASE_URL=postgresql+psycopg2://jarvis:jarvis_dev_password@localhost:5432/jarvis_skills_test \
        pytest tests/test_db_level_immutability.py -v
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import IS_POSTGRES, auth_headers

pytestmark = pytest.mark.skipif(
    not IS_POSTGRES,
    reason="DB-level triggers are PostgreSQL-only; set TEST_DATABASE_URL to a postgres:// URL to run this.",
)


def _create_skill(client, user):
    resp = client.post(
        "/skills",
        json={
            "name": "Trigger Test Skill",
            "department": "operations",
            "instructions": "Original instructions.",
            "requested_tools": ["generate_report"],
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_direct_sql_update_of_version_content_is_rejected(client, orgs, db_session):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    version_id = skill["versions"][0]["id"]

    with pytest.raises(DBAPIError, match="immutable"):
        db_session.execute(
            text("UPDATE skill_versions SET instructions = :new WHERE id = :id"),
            {"new": "tampered content", "id": version_id},
        )
        db_session.flush()
    db_session.rollback()


def test_direct_sql_delete_of_version_is_rejected(client, orgs, db_session):
    abc = orgs["abc"]
    skill = _create_skill(client, abc.owner)
    version_id = skill["versions"][0]["id"]

    with pytest.raises(DBAPIError, match="never be deleted"):
        db_session.execute(text("DELETE FROM skill_versions WHERE id = :id"), {"id": version_id})
        db_session.flush()
    db_session.rollback()


def test_direct_sql_update_of_audit_log_is_rejected(client, orgs, db_session):
    abc = orgs["abc"]
    _create_skill(client, abc.owner)  # generates at least one audit row

    row = db_session.execute(text("SELECT id FROM audit_logs LIMIT 1")).first()
    assert row is not None, "expected at least one audit log row"

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text("UPDATE audit_logs SET event_type = 'tampered' WHERE id = :id"),
            {"id": row[0]},
        )
        db_session.flush()
    db_session.rollback()


def test_direct_sql_delete_of_audit_log_is_rejected(client, orgs, db_session):
    abc = orgs["abc"]
    _create_skill(client, abc.owner)

    row = db_session.execute(text("SELECT id FROM audit_logs LIMIT 1")).first()
    assert row is not None

    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": row[0]})
        db_session.flush()
    db_session.rollback()
