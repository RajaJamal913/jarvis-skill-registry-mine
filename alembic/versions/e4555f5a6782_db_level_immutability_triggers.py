"""enforce version immutability and audit append-only at the database level (PostgreSQL only)

Revision ID: e4555f5a6782
Revises: df5a91caf961
Create Date: 2026-08-27 00:00:00.000000

These triggers are a second, independent enforcement layer beneath the
application-layer rules in app/crud.py. They only run on PostgreSQL -
SQLite (used exclusively by the test suite, see ARCHITECTURE.md) does not
get this migration's trigger bodies, since PL/pgSQL is Postgres-specific.
This means the automated pytest suite (SQLite) does NOT exercise these
triggers directly; app/../tests/test_db_level_immutability.py is a
Postgres-only test (skipped elsewhere) written specifically to prove they
work. Run it against the docker-compose Postgres service, or in the
`test-postgres` CI job, to get real evidence for this layer.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e4555f5a6782'
down_revision = '26b4207992da'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_skill_version_content_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.instructions IS DISTINCT FROM OLD.instructions
                OR NEW.requested_tools IS DISTINCT FROM OLD.requested_tools
                OR NEW.granted_tools IS DISTINCT FROM OLD.granted_tools
                OR NEW.version_number IS DISTINCT FROM OLD.version_number
                OR NEW.skill_id IS DISTINCT FROM OLD.skill_id
                OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                OR NEW.created_by IS DISTINCT FROM OLD.created_by
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION
                    'skill_versions is immutable: only status/activated_by/activated_at/reviewed_by/reviewed_at may change (attempted on version id %)',
                    OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_skill_version_no_content_mutation
        BEFORE UPDATE ON skill_versions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_skill_version_content_mutation();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_skill_version_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'skill_versions rows may never be deleted (attempted on version id %)', OLD.id;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_skill_version_no_delete
        BEFORE DELETE ON skill_versions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_skill_version_delete();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only: UPDATE and DELETE are not permitted (attempted on log id %)',
                COALESCE(OLD.id, NEW.id);
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_audit_log_no_update
        BEFORE UPDATE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
    """)

    op.execute("""
        CREATE TRIGGER trg_audit_log_no_delete
        BEFORE DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
    """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS trg_skill_version_no_content_mutation ON skill_versions;")
    op.execute("DROP TRIGGER IF EXISTS trg_skill_version_no_delete ON skill_versions;")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_logs;")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_skill_version_content_mutation();")
    op.execute("DROP FUNCTION IF EXISTS prevent_skill_version_delete();")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation();")
