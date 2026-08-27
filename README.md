# Jarvis AI COO — Organization-Scoped Skill Registry (Vertical Slice)

A multi-tenant backend where each organization can draft, review, version,
and activate its own AI COO "skills," with strict organization-level
isolation and full audit logging.

Built for the 8-hour developer evaluation. See `ARCHITECTURE.md` for design
rationale and `LIMITATIONS.md` for known gaps / what's out of scope.

## Stack

- **FastAPI** (Python 3.11)
- **PostgreSQL** (via Docker Compose) — SQLite is used only for the
  automated test suite; see `ARCHITECTURE.md` for the written justification.
- **SQLAlchemy** ORM + **Alembic** migrations
- **pytest** + FastAPI `TestClient` for the automated test suite

## Quick start (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

This starts:
- `db` — Postgres 16, with a healthcheck gating API startup
- `api` — FastAPI app on `http://localhost:8000`, auto-creates the schema
  on startup (`AUTO_CREATE_SCHEMA=1`, evaluation/dev convenience — see
  `ARCHITECTURE.md`)

Once running, seed the two fixture organizations (ABC Construction, XYZ
Builders) with an owner + member user each:

```bash
docker compose exec api python -m scripts.seed
```

This prints API keys to stdout, e.g.:

```
ABC Construction     owner    owner@abc-construction.example api_key=dev_xxxxxxxxxxxxxxxxxxxxxxxx
ABC Construction     member   member@abc-construction.example api_key=dev_xxxxxxxxxxxxxxxxxxxxxxxx
XYZ Builders         owner    owner@xyz-builders.example     api_key=dev_xxxxxxxxxxxxxxxxxxxxxxxx
XYZ Builders         member   member@xyz-builders.example    api_key=dev_xxxxxxxxxxxxxxxxxxxxxxxx
```

These are local dev fixtures, not real secrets — they only work against
your own local database.

Interactive API docs: `http://localhost:8000/docs`

## Quick start (local, no Docker)

Requires a running Postgres instance (or point `DATABASE_URL` at SQLite for
a quick manual spin — not recommended beyond ad-hoc local testing, see
`ARCHITECTURE.md`).

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # edit DATABASE_URL if not using the default Postgres

python -m scripts.seed             # seeds fixture orgs + prints API keys
uvicorn app.main:app --reload      # http://localhost:8000
```

## Running the tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

By default this runs against a fresh, file-based SQLite database per test
(schema built by running the real Alembic migrations, not a shortcut).
4 tests are Postgres-only (the DB-level immutability triggers) and are
skipped on SQLite - to run the full suite against real PostgreSQL:

```bash
docker compose up -d db
TEST_DATABASE_URL=postgresql+psycopg2://jarvis:jarvis_dev_password@localhost:5432/jarvis_skills_test \
    pytest tests/ -v
```

**On `test_output.txt`:** a single locally-generated file only proves
tests passed on one machine, on one date, against one backend — it is a
snapshot, not a trustworthy gate on its own. `.github/workflows/ci.yml`
is the actual gate: it runs the suite on Python 3.11 *and* 3.12 against
SQLite, separately against a real Postgres service container (exercising
the DB-level triggers), and boots the full `docker compose` stack and
hits `/health` + runs the seed script against it. Push this repo to
GitHub and check the Actions tab for current, reproducible results rather
than trusting the committed snapshot alone.

## Authentication model

Every request is authenticated via an `X-API-Key` header. Each key maps
1:1 to a `(organization_id, role, department)` tuple. Keys are hashed
(SHA-256) at rest — the database never stores a raw key, only its hash —
and a revoked key (`api_key_revoked_at` set) is rejected at auth time.
There is no session/JWT layer — the brief explicitly does not require a
frontend or external auth provider, and the property actually under
evaluation is **authorization** (org isolation + owner-only activation),
not login UX.

```
X-API-Key: dev_xxxxxxxxxxxxxxxxxxxxxxxx
```

## API walkthrough

All examples assume `BASE=http://localhost:8000` and an owner API key from
the seed output.

### 1. Create a skill draft

```bash
curl -X POST $BASE/skills \
  -H "X-API-Key: $OWNER_KEY" -H "Content-Type: application/json" \
  -d '{
    "name": "Weekly Site Report",
    "department": "operations",
    "instructions": "Compile a weekly progress report from site logs.",
    "requested_tools": ["generate_report"]
  }'
```

Creates the `Skill` (status `draft`) and its first immutable `SkillVersion`
(version 1, status `draft`) in one call. Response includes both.

### 2. List skills for your organization

```bash
curl $BASE/skills -H "X-API-Key: $OWNER_KEY"
```

### 3. Read one skill with all its versions

```bash
curl $BASE/skills/$SKILL_ID -H "X-API-Key: $OWNER_KEY"
```

### 4. Create a new immutable version

Editing = creating a new version. The previous version is never mutated.

```bash
curl -X POST $BASE/skills/$SKILL_ID/versions \
  -H "X-API-Key: $OWNER_KEY" -H "Content-Type: application/json" \
  -d '{
    "instructions": "Compile a weekly report and flag overdue tasks.",
    "requested_tools": ["generate_report", "send_email"]
  }'
```

### 5. Submit the version for review

New versions start in `draft`. A version cannot be activated until it has
been submitted for review and approved by an owner.

```bash
curl -X POST $BASE/skills/$SKILL_ID/versions/$VERSION_ID/submit-for-review \
  -H "X-API-Key: $ANY_ORG_MEMBER_KEY"
```

### 6. Approve the version (owner only)

```bash
curl -X POST $BASE/skills/$SKILL_ID/versions/$VERSION_ID/approve \
  -H "X-API-Key: $OWNER_KEY"
```

- Non-owners get `403`.
- A version that hasn't been submitted for review yet (still `draft`)
  returns `409`.
- Records `reviewed_by` / `reviewed_at` on the version.

### 7. Activate the approved version (owner only)

```bash
curl -X POST $BASE/skills/$SKILL_ID/versions/$VERSION_ID/activate \
  -H "X-API-Key: $OWNER_KEY"
```

- Non-owners get `403`.
- A version that isn't `approved` yet (still `draft` or `in_review`)
  returns `409` - activation cannot skip review.
- Activating an already-active version is a safe no-op (idempotent) —
  it returns the same version, unchanged, and logs an
  `skill_activation_noop` audit event rather than erroring.
- Activating a new version automatically marks the previously active
  version `superseded` (it is never deleted or edited).

### 8. Disable a skill (owner only)

```bash
curl -X POST $BASE/skills/$SKILL_ID/disable -H "X-API-Key: $OWNER_KEY"
```

Non-owners get `403`. Disabled skills are immediately excluded from
runtime/department selection (see below).

### 9. Retrieve active skills for a department

```bash
curl $BASE/departments/operations/active-skills -H "X-API-Key: $OWNER_KEY"
```

Only returns skills that are (a) in this organization, (b) in this
department, and (c) currently `active`. Draft and disabled skills never
appear here.

### 10. Read the audit log

```bash
curl $BASE/audit-logs -H "X-API-Key: $OWNER_KEY"
```

Org-scoped, append-only. Every draft creation, version creation,
activation (including no-ops), and disable event is recorded with
`organization_id`, `actor_user_id`, `event_type`, `skill_id`, and
`version_id`.

### Cross-tenant isolation, demonstrated

```bash
# XYZ Builders' owner trying to read ABC Construction's skill:
curl -i $BASE/skills/$ABC_SKILL_ID -H "X-API-Key: $XYZ_OWNER_KEY"
# -> HTTP 404 (not 403 — existence itself is not leaked across tenants)
```

## Project layout

```
app/
  main.py            FastAPI app, startup schema bootstrap
  database.py         SQLAlchemy engine/session
  models.py            ORM models (Organization, User, Skill, SkillVersion, AuditLog)
  schemas.py           Pydantic request/response models + input validation
  auth.py               API-key -> user resolution, owner-only dependency
  security_tools.py      Requested-tool allowlist + destructive-pattern rejection
  crud.py                 Domain logic: create/list/read/version/activate/disable
  routers/
    skills.py             /skills endpoints
    departments.py         /departments/{dept}/active-skills
    audit.py                 /audit-logs
alembic/               Migration environment + initial schema migration
scripts/seed.py        Seeds ABC Construction + XYZ Builders fixtures
tests/                  pytest suite (isolation, lifecycle, tools, audit)
docker-compose.yml      Postgres + API
Dockerfile
.env.example
```
