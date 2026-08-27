# Known Limitations

This is intentionally a narrow vertical slice. Items below were reviewed
and updated after external feedback — see the "Resolved" section for what
was fixed and when, and the "Still open" section for what remains.

## Still open

### Security / auth
- **API keys have no rotation/expiry**, only revocation
  (`api_key_revoked_at`, checked at auth time). Issuing a replacement key
  without downtime, or TTL-based auto-expiry, is not implemented.
- **No rate limiting** on any endpoint, including auth.
- **No explicit "grant tool" workflow.** `granted_tools` exists in the
  schema and is always empty, correctly demonstrating that requesting a
  tool doesn't grant it, but there's no endpoint to actually grant one —
  that's a distinct, larger feature (likely needing its own approval
  step and audit trail) that the brief didn't ask for.

### Lifecycle
- **No re-enable path for a disabled skill.** Once disabled, a skill stays
  disabled; `activate_version` explicitly rejects activation attempts
  against a disabled skill.
- **No pagination** on `GET /skills` or `GET /audit-logs`.

### Operational
- **Schema bootstrap via `Base.metadata.create_all()` at startup**
  (`AUTO_CREATE_SCHEMA=1`) is a dev/eval convenience for the running
  service. A real deployment would run `alembic upgrade head` as a
  release step and set `AUTO_CREATE_SCHEMA=0`. (Note: the test suite
  itself already runs the real migrations, not `create_all()` — see
  `ARCHITECTURE.md` §11-12 — this item is about the running app's
  own startup path, not the tests.)
- **No structured logging / observability** beyond the audit log table
  itself (a domain audit trail, not an operational log).
- **No soft-delete / retention policy** for audit log rows.

### Testing
- No load/concurrency tests (e.g. two simultaneous activation requests
  racing on the same skill).
- The in-process-vs-subprocess Alembic flake documented in
  `ARCHITECTURE.md` §12 was worked around, not root-caused. If it
  resurfaces in CI, that's the first place to look.

## Resolved (after review)

- **Draft skills could be activated directly, with no real review step.**
  Fixed: versions now go `draft -> in_review -> approved -> active`, with
  `submit-for-review` (any member) and owner-only `approve` endpoints.
  Activating anything less than `approved` returns `409`.
- **`disable` was callable by any authenticated org member, not just the
  owner.** Fixed: `POST /skills/{id}/disable` now requires
  `require_owner`, matching activation.
- **API keys were stored in plaintext.** Fixed: `User.api_key_hash`
  (SHA-256) replaces the raw key column; the raw key is shown once at
  seed time and never persisted.
- **Immutability and audit append-only were enforced only in application
  code**, with no independent check. Fixed: a Postgres-only Alembic
  migration adds trigger functions rejecting mutating `UPDATE`s to
  `skill_versions` and any `UPDATE`/`DELETE` on `audit_logs`, proven by
  `tests/test_db_level_immutability.py` against a real Postgres
  connection.
- **Tests were SQLite-only, and a committed `test_output.txt` was the
  only evidence offered**, which is not a trustworthy gate on its own.
  Fixed: `.github/workflows/ci.yml` runs the suite on a Python 3.11/3.12
  matrix against SQLite, separately against a real Postgres service
  container, and boots the full `docker compose` stack end to end. The
  committed `test_output.txt` is now labeled as a snapshot, not a gate.
- **A hang was reported on an independent Python 3.11 run.** Root cause
  not reproduced in this environment (no Python 3.11 available to test
  against directly), but `pytest-timeout` (30s/test) was added so any
  future hang fails loudly and visibly in CI instead of hanging
  indefinitely — see `.github/workflows/ci.yml`'s `test-sqlite` job,
  which does run on 3.11.

## What I would implement next
1. An explicit, owner-gated "grant tool" endpoint + audit event.
2. API key rotation (issue-without-downtime) and TTL-based expiry.
3. Postgres RLS as an additional isolation layer beneath the
   application-layer checks (belt-and-suspenders alongside the
   immutability triggers already added).
4. Pagination on list endpoints.
5. Concurrency tests for simultaneous activation requests.
