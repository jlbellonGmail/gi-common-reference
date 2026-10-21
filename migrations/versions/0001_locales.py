"""Catálogo global de locales: snapshots, locales y alias (spec 001, plan "Datos").

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = "reference.locale_snapshot, reference.locale, reference.locale_alias"

UPGRADE = f"""
CREATE TABLE reference.locale_snapshot (
    snapshot_version bigint NOT NULL,
    content_digest text NOT NULL,
    iana_file_date date NOT NULL,
    iana_digest text NOT NULL,
    provenance jsonb NOT NULL,
    artifact jsonb NOT NULL,
    incorporated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT locale_snapshot_pkey PRIMARY KEY (snapshot_version),
    CONSTRAINT locale_snapshot_version_positive CHECK (snapshot_version > 0)
);

CREATE TABLE reference.locale (
    locale_id uuid NOT NULL,
    code text NOT NULL,
    status text NOT NULL,
    iana_deprecated boolean NOT NULL,
    replacement_locale_id uuid,
    first_snapshot_version bigint NOT NULL,
    CONSTRAINT locale_pkey PRIMARY KEY (locale_id),
    CONSTRAINT locale_code_key UNIQUE (code),
    CONSTRAINT locale_code_format CHECK (code ~ '^[a-z]{{2,3}}$'),
    CONSTRAINT locale_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT locale_replacement_not_self CHECK (replacement_locale_id <> locale_id),
    CONSTRAINT locale_replacement_requires_deprecation
        CHECK (replacement_locale_id IS NULL OR iana_deprecated),
    CONSTRAINT locale_deprecated_is_inactive CHECK (NOT iana_deprecated OR status = 'inactive'),
    CONSTRAINT locale_replacement_fk FOREIGN KEY (replacement_locale_id)
        REFERENCES reference.locale (locale_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT locale_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.locale_snapshot (snapshot_version)
);

CREATE TABLE reference.locale_alias (
    subtag text NOT NULL,
    preferred_value text NOT NULL,
    CONSTRAINT locale_alias_pkey PRIMARY KEY (subtag)
);

CREATE FUNCTION reference.reject_locale_snapshot_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reference.locale_snapshot is immutable'
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE FUNCTION reference.reject_locale_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published locales are never deleted'
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE FUNCTION reference.reject_locale_identity_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.locale_id IS DISTINCT FROM OLD.locale_id OR NEW.code IS DISTINCT FROM OLD.code THEN
        RAISE EXCEPTION 'locale_id and code are immutable once published'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER locale_snapshot_immutable
    BEFORE UPDATE OR DELETE ON reference.locale_snapshot
    FOR EACH ROW EXECUTE FUNCTION reference.reject_locale_snapshot_change();

CREATE TRIGGER locale_no_delete
    BEFORE DELETE ON reference.locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_locale_delete();

CREATE TRIGGER locale_identity_immutable
    BEFORE UPDATE ON reference.locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_locale_identity_change();

-- TRUNCATE no dispara los triggers por fila: sin estos vaciaría las tablas sin pasar por ellos.
CREATE TRIGGER locale_snapshot_no_truncate
    BEFORE TRUNCATE ON reference.locale_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_locale_snapshot_change();

CREATE TRIGGER locale_no_truncate
    BEFORE TRUNCATE ON reference.locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_locale_delete();

-- Aislamiento (D10): nada para PUBLIC ni para los roles de la API de Supabase.
REVOKE ALL ON SCHEMA reference FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA reference FROM PUBLIC;

DO $$
DECLARE
    api_role text;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA reference FROM %I', api_role);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA reference FROM %I', api_role);
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reference_reader') THEN
        GRANT USAGE ON SCHEMA reference TO reference_reader;
        GRANT SELECT ON {TABLES} TO reference_reader;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reference_loader') THEN
        GRANT USAGE ON SCHEMA reference TO reference_loader;
        GRANT SELECT ON {TABLES} TO reference_loader;
        GRANT INSERT ON reference.locale_snapshot TO reference_loader;
        GRANT INSERT ON reference.locale TO reference_loader;
        GRANT UPDATE (status, iana_deprecated, replacement_locale_id)
            ON reference.locale TO reference_loader;
        GRANT INSERT, DELETE ON reference.locale_alias TO reference_loader;
    END IF;
END
$$;
"""

DOWNGRADE = """
DROP TABLE reference.locale_alias;
DROP TABLE reference.locale;
DROP TABLE reference.locale_snapshot;
DROP FUNCTION reference.reject_locale_identity_change();
DROP FUNCTION reference.reject_locale_delete();
DROP FUNCTION reference.reject_locale_snapshot_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
