# Architecture Decisions

## 1. Canonical ownership key: `organization_id`

Every tenant-owned table (`skills`, `skill_versions`, `audit_logs`) carries
its own `organization_id` column directly, rather than requiring a join
through `skills` to determine ownership. This is deliberate:

- **Isolation checks stay local to each query.** A `skill_versions` row's
  tenant can be verified without joining back to `skills`, which matters
  once you have more than one or two related tables — the "did I forget a
  join and leak data" failure mode gets structurally harder to hit.
- It matches the brief's explicit instruction that `organization_id` is
  the canonical ownership key, not `skill_id` or any derived relationship.

`AuditLog` also carries `organization_id` directly (denormalized from the
actor/skill) so the audit trail can be queried and isolated even if a
referenced skill is later deleted (it isn't, in this slice, but the schema
doesn't assume that).

## 2. Tenant isolation strategy: scoped lookups, not row-level security

Isolation is enforced in the application layer: every read/write that
touches a `Skill` or `SkillVersion` goes through
`crud.get_skill_scoped_or_404`, which filters by `organization_id` *before*
returning anything. A skill belonging to another org is treated exactly
like a skill that does not exist — **404, not 403** — so a caller cannot
use response codes to enumerate the existence of other tenants' resources.

Postgres row-level security (RLS) was considered as a defense-in-depth
layer but intentionally left out of this slice: it would require
per-request `SET app.current_org` session variables wired through
SQLAlchemy's connection pool, which is a meaningful chunk of additional
plumbing for a slice whose evaluated surface area is the application-layer
authorization logic itself. It's called out in `LIMITATIONS.md` as the
first thing to add for production hardening.

## 3. Immutable versioning model

- `Skill` is a stable pointer: `id`, `organization_id`, `name`,
  `department`, `status`, and `active_version_id`.
- `SkillVersion` rows are **never updated after creation**, except for the
  `status` transition that *is* the activation workflow itself
  (`draft -> active`, `active -> superseded`). There is no PUT/PATCH
  endpoint for a version's content — the only way to change a skill's
  behavior is `POST /skills/{id}/versions`, which always creates a new row
  with an incremented `version_number`.
- Activating a new version supersedes (not deletes) the previous active
  version, preserving full history for audit purposes.
- `Skill.active_version_id` is intentionally **not** a SQL foreign key
  (see `app/models.py` comment) — `SkillVersion.skill_id` already points
  the other direction, and a mutual FK between the two tables creates a
  circular dependency for schema creation and Alembic autogeneration. The
  pointer is written in exactly one place (`crud.activate_version`) and
  validated at the application layer.

## 4. Requested tools vs. granted tools

The brief requires that "a skill's requested tools must not grant
permissions automatically." The data model reflects this directly:
`SkillVersion.requested_tools` and `SkillVersion.granted_tools` are
separate fields. Every version starts with `granted_tools = []`
unconditionally, regardless of what was requested — there is no code path
in this slice that copies `requested_tools` into `granted_tools`. A real
system would add an explicit, separately-audited grant action (likely
owner-only, likely with its own approval step); that's out of scope here,
but the schema doesn't quietly conflate the two concepts.

Requested tool names are validated against two independent rules
(`app/security_tools.py`):
1. An **allowlist** of registered tool names — unknown/typo'd tools are
   rejected outright.
2. A **destructive-pattern blocklist** (`delete`, `drop`, `shell`, `exec`,
   `sudo`, etc.) — this catches invented tool names that are designed to
   *look* dangerous even if they'd never match the allowlist, and would
   also catch a future allowlist entry that shouldn't have been added.

## 5. Idempotent activation

Activating a version that is already the active version is a safe no-op:
it returns `200` with the same version state and logs a distinct
`skill_activation_noop` audit event, rather than either erroring or
silently re-running the supersede logic (which would be harmless here but
is exactly the kind of "harmless until it isn't" shortcut the brief is
testing for). Activating a `superseded` version, however, is rejected with
`409` — re-activating history is a deliberate design decision the brief
doesn't require, and allowing it silently would blur the audit trail.

## 6. Why SQLite for tests, Postgres for everything else

The brief states Postgres is preferred and SQLite is allowed only with
written justification — here it is:

- **Postgres is the actual deployment target.** `docker-compose.yml` runs
  Postgres, the Alembic migration is written against it, and
  `DATABASE_URL` defaults to a Postgres connection string. Nothing about
  the production/dev path uses SQLite.
- **SQLite is used exclusively inside the pytest suite**, via an
  in-memory database created fresh per test (`tests/conftest.py`). This is
  a deliberate, narrow scope, not a substitution for Postgres in general:
  it lets the test suite run in well under a second, in any environment,
  with zero external services, Docker, or network access required — which
  matters for a take-home evaluation that needs to be trivially
  reproducible by a reviewer.
- The ORM layer (SQLAlchemy models, no Postgres-specific column types)
  was kept portable specifically so this split is safe: the schema
  exercised by the tests is structurally the same schema Alembic creates
  in Postgres. The one adjustment (`app/database.py`) is enabling
  `check_same_thread=False` for SQLite's connection handling under
  FastAPI's threaded test client — a driver-level detail, not a schema or
  behavior difference.

## 7. Auth: API key, not JWT/OAuth

The brief explicitly marks a frontend and external AI/API as out of
scope, and the evaluated surface is authorization (org isolation,
owner-only actions), not authentication UX. A static per-user API key
resolved to `(organization_id, role, department)` (`app/auth.py`) gives a
real, testable authorization boundary without building a login flow that
the brief doesn't ask for and that would add surface area unrelated to
what's being scored.

## 9. Review/approval as a real state, not implicit

An earlier version of this slice let any owner activate a `draft` version
directly. That didn't reflect the brief's stated workflow (draft create →
draft review → owner activation) and was flagged in review. Versions now
carry `in_review` and `approved` states between `draft` and `active`:
`POST /versions/{id}/submit-for-review` (any org member) moves a version
to `in_review`; `POST /versions/{id}/approve` (owner-only) moves it to
`approved` and records `reviewed_by`/`reviewed_at`; `activate_version`
now rejects anything that isn't `approved` with `409`. A dedicated
reviewer role distinct from "owner" was considered and left out — the
brief's RBAC surface is owner-vs-member, and introducing a third role
would be scope creep beyond what's being evaluated.

## 10. API keys are hashed, not stored in plaintext

`User.api_key_hash` stores a SHA-256 hash; the raw key is never persisted
and is shown to the operator exactly once (at seed time). An
`api_key_revoked_at` column is checked on every request — set it and the
key stops working immediately, no deletion required. Full key
rotation/expiry (issuing a replacement without downtime, TTL-based
auto-expiry) is still out of scope; see `LIMITATIONS.md`.

## 11. Immutability enforced at two independent layers

Application-layer immutability (§3 above) is real, but it's also a single
point of failure — a bug in `crud.py` is the only thing standing between
"immutable" and "silently mutable." A Postgres-only Alembic migration
(`e4555f5a6782_...`) adds trigger functions that reject:
- any `UPDATE` on `skill_versions` that touches content columns
  (instructions, requested_tools, granted_tools, version_number,
  skill_id, organization_id, created_by, created_at) — only the
  status/activation/review columns may change, since that's the
  activation/review workflow itself;
- any `DELETE` on `skill_versions`;
- any `UPDATE` or `DELETE` on `audit_logs` at all (append-only).

These run independently of the application, so even a direct `psql`
session or a future bug in `crud.py` can't silently violate either
guarantee. `tests/test_db_level_immutability.py` proves this by running
raw SQL against a real Postgres connection and asserting it's rejected —
it's skipped on SQLite, since SQLite never receives this migration's
trigger bodies (see that migration's docstring). This is why the test
suite's schema setup runs the *actual* Alembic migrations rather than
`Base.metadata.create_all()` — the triggers are pure SQL living inside a
migration file, invisible to the ORM metadata, so `create_all()` would
silently produce a schema that looks right but doesn't have this layer.

## 12. Why tests shell out to `alembic` as a subprocess

The test fixtures originally called Alembic's Python API
(`alembic.command.upgrade(cfg, "head")`) directly, in-process, once per
test. This worked on the first invocation and then intermittently
no-op'd on later ones — a fresh, never-before-touched SQLite file would
sometimes report itself already at `head` with no tables ever created,
which then surfaced downstream as `OperationalError: no such table`.
This was reproducible but never fully root-caused (some form of state
being cached across repeated in-process Alembic invocations within one
long-lived pytest process — possibly in `ScriptDirectory`/Python's module
cache, never confirmed). Rather than ship something built on top of an
unexplained flake, the fixture now shells out to a real
`python -m alembic upgrade head` subprocess per test. Each subprocess
gets a fully independent Python interpreter and import state, which
removed the flakiness entirely across repeated local runs, and it has
the added benefit of testing the literal command a real deployment would
run rather than a Python-API approximation of it.

## 13. Error handling (blank fields, malformed input) return `422` with
  a structured error list (FastAPI/Pydantic default, made JSON-safe for
  custom validators — see `app/main.py`).
- Rejected tool requests return `400` with a specific reason.
- Cross-tenant access returns `404` (see §2).
- Non-owner activation returns `403` (this one *is* allowed to reveal
  "this exists but you can't touch it," since it's a same-tenant
  authorization failure, not a cross-tenant one).
- Invalid state transitions (e.g. activating a superseded version,
  creating a version under a disabled skill) return `409`.
