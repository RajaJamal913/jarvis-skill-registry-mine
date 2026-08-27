"""
Test fixtures.

By default this suite runs against an isolated, file-based SQLite DB
(a fresh temp file per test) - see README "Architecture Decisions" for
why SQLite is acceptable here: it's test-only, never used for the actual
running service, and it lets each test get a fresh, fast, fully-isolated
schema with zero external dependencies/CI setup.

To run the SAME suite against real PostgreSQL (recommended before trusting
results, and required to exercise the Postgres-only DB-level immutability
triggers - see tests/test_db_level_immutability.py), set TEST_DATABASE_URL:

    TEST_DATABASE_URL=postgresql+psycopg2://jarvis:jarvis_dev_password@localhost:5432/jarvis_skills_test \
        pytest tests/ -v

The CI workflow (.github/workflows/ci.yml) runs both: a fast SQLite job on
a Python version matrix, and a separate job against a real Postgres
service container. A single locally-generated test_output.txt is a
snapshot from one machine, one date, one backend - not a trustworthy gate
on its own. The CI workflow is the actual gate.

Schema setup for both backends goes through the REAL Alembic migrations
(upgrade head / downgrade base), not SQLAlchemy's Base.metadata.create_all().
This matters specifically for PostgreSQL: the DB-level immutability
triggers are raw SQL inside a migration, not part of the ORM metadata, so
create_all() would silently skip them - the tests would then be exercising
a schema that doesn't match what actually gets deployed.
"""
import os
import subprocess
import sys
import tempfile
import uuid

TEST_DATABASE_URL_OVERRIDE = os.environ.get("TEST_DATABASE_URL")
IS_POSTGRES = bool(TEST_DATABASE_URL_OVERRIDE) and TEST_DATABASE_URL_OVERRIDE.startswith("postgresql")

TEST_DATABASE_URL = TEST_DATABASE_URL_OVERRIDE or f"sqlite:///{tempfile.gettempdir()}/jarvis_test_placeholder.db"
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ["AUTO_CREATE_SCHEMA"] = "0"  # schema is created explicitly per test, via Alembic

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import get_db
from app import models
from app.auth import hash_api_key
from app.main import app

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _run_alembic(*args: str, db_url: str) -> None:
    """
    Runs Alembic as a real subprocess (not the Python API in-process)
    against db_url. This is a deliberate choice made after the in-process
    `alembic.command.upgrade()` API exhibited unexplained, intermittent
    state leakage across repeated calls within one long-lived pytest
    process (a fresh SQLite file would sometimes silently no-op instead of
    running any migrations - never fully root-caused, and not worth
    shipping on a hunch). A subprocess is fully isolated per invocation,
    matches exactly what a real deploy runs (`alembic upgrade head`), and
    removed the flakiness entirely in local testing.
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed (db_url={db_url}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def _make_engine(db_url: str):
    if IS_POSTGRES:
        return create_engine(db_url, pool_pre_ping=True)
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_con, _):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture()
def db_session():
    """
    PostgreSQL: upgrade head / downgrade base against the shared test DB
    (Postgres handles DROP COLUMN natively, so downgrade cleanly restores
    an empty schema).

    SQLite: a brand-new temp file PER TEST, upgraded to head via a real
    `alembic upgrade head` subprocess, deleted afterwards.
    """
    if IS_POSTGRES:
        db_url = TEST_DATABASE_URL
        _run_alembic("upgrade", "head", db_url=db_url)
        engine = _make_engine(db_url)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
            _run_alembic("downgrade", "base", db_url=db_url)
    else:
        db_path = os.path.join(tempfile.gettempdir(), f"jarvis_test_{uuid.uuid4().hex}.db")
        db_url = f"sqlite:///{db_path}"
        try:
            _run_alembic("upgrade", "head", db_url=db_url)
            engine = _make_engine(db_url)
            TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            session = TestingSessionLocal()
            try:
                yield session
            finally:
                session.close()
                engine.dispose()
        finally:
            try:
                os.remove(db_path)
            except OSError:
                pass


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Fixture:
    """Small container for a seeded org + its two users."""

    def __init__(self, org, owner, member, owner_raw_key, member_raw_key):
        self.org = org
        self.owner = owner
        self.member = member
        self.owner_raw_key = owner_raw_key
        self.member_raw_key = member_raw_key


def _make_org_with_users(db_session, org_name: str, dept: str = "operations") -> Fixture:
    org = models.Organization(name=org_name)
    db_session.add(org)
    db_session.flush()

    owner_raw_key = f"key-owner-{org.id}"
    member_raw_key = f"key-member-{org.id}"

    owner = models.User(
        organization_id=org.id,
        email=f"owner@{org_name.lower().replace(' ', '-')}.example",
        api_key_hash=hash_api_key(owner_raw_key),
        role=models.UserRole.owner,
        department=dept,
    )
    member = models.User(
        organization_id=org.id,
        email=f"member@{org_name.lower().replace(' ', '-')}.example",
        api_key_hash=hash_api_key(member_raw_key),
        role=models.UserRole.member,
        department=dept,
    )
    db_session.add_all([owner, member])
    db_session.commit()
    db_session.refresh(owner)
    db_session.refresh(member)
    # Attach the raw key as a plain Python attribute (not persisted - the
    # DB only ever stores the hash) so tests can authenticate as this user.
    owner.raw_api_key = owner_raw_key
    member.raw_api_key = member_raw_key
    return Fixture(org, owner, member, owner_raw_key, member_raw_key)


@pytest.fixture()
def orgs(db_session):
    """Two fixture organizations, matching the evaluation brief."""
    abc = _make_org_with_users(db_session, "ABC Construction")
    xyz = _make_org_with_users(db_session, "XYZ Builders")
    return {"abc": abc, "xyz": xyz}


def auth_headers(user) -> dict:
    return {"X-API-Key": user.raw_api_key}
