"""Catálogo global de regiones y subregiones M49 (spec 002, plan "Datos").

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = (
    "reference.region_snapshot, reference.region, reference.subregion, "
    "reference.region_locale, reference.subregion_locale, "
    "reference.subregion_reclassification, reference.region_recoding, "
    "reference.subregion_recoding"
)

UPGRADE = r"""
CREATE TABLE reference.region_snapshot (
    snapshot_version bigint NOT NULL,
    content_digest text NOT NULL,
    locale_snapshot_version bigint NOT NULL,
    required_locales_version integer NOT NULL,
    provenance jsonb NOT NULL,
    artifact jsonb NOT NULL,
    incorporated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT region_snapshot_pkey PRIMARY KEY (snapshot_version),
    CONSTRAINT region_snapshot_version_positive CHECK (snapshot_version > 0),
    CONSTRAINT region_snapshot_required_locales_version_positive
        CHECK (required_locales_version > 0),
    CONSTRAINT region_snapshot_locale_snapshot_fk FOREIGN KEY (locale_snapshot_version)
        REFERENCES reference.locale_snapshot (snapshot_version)
);

CREATE TABLE reference.region (
    region_id uuid NOT NULL,
    code text,
    code_snapshot_version bigint,
    status text NOT NULL,
    replacement_region_id uuid,
    first_snapshot_version bigint NOT NULL,
    CONSTRAINT region_pkey PRIMARY KEY (region_id),
    CONSTRAINT region_code_format CHECK (code ~ '^[0-9]{3}$'),
    CONSTRAINT region_code_snapshot_consistent
        CHECK ((code IS NULL) = (code_snapshot_version IS NULL)),
    CONSTRAINT region_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT region_replacement_not_self CHECK (replacement_region_id <> region_id),
    CONSTRAINT region_replacement_requires_inactive
        CHECK (replacement_region_id IS NULL OR status = 'inactive'),
    CONSTRAINT region_active_code_unique EXCLUDE USING btree (code WITH =)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT region_replacement_fk FOREIGN KEY (replacement_region_id)
        REFERENCES reference.region (region_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT region_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version),
    CONSTRAINT region_code_snapshot_fk FOREIGN KEY (code_snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version)
);

CREATE TABLE reference.subregion (
    subregion_id uuid NOT NULL,
    region_id uuid NOT NULL,
    code text,
    code_snapshot_version bigint,
    status text NOT NULL,
    replacement_subregion_id uuid,
    first_snapshot_version bigint NOT NULL,
    CONSTRAINT subregion_pkey PRIMARY KEY (subregion_id),
    -- Destino de la FK compuesta (region_id, subregion_id) de otros catálogos (RF-29, D8).
    CONSTRAINT subregion_region_subregion_key UNIQUE (region_id, subregion_id),
    CONSTRAINT subregion_code_format CHECK (code ~ '^[0-9]{3}$'),
    CONSTRAINT subregion_code_snapshot_consistent
        CHECK ((code IS NULL) = (code_snapshot_version IS NULL)),
    CONSTRAINT subregion_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT subregion_replacement_not_self CHECK (replacement_subregion_id <> subregion_id),
    CONSTRAINT subregion_replacement_requires_inactive
        CHECK (replacement_subregion_id IS NULL OR status = 'inactive'),
    CONSTRAINT subregion_active_code_unique EXCLUDE USING btree (code WITH =)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT subregion_region_fk FOREIGN KEY (region_id)
        REFERENCES reference.region (region_id),
    CONSTRAINT subregion_replacement_fk FOREIGN KEY (replacement_subregion_id)
        REFERENCES reference.subregion (subregion_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT subregion_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version),
    CONSTRAINT subregion_code_snapshot_fk FOREIGN KEY (code_snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version)
);

CREATE TABLE reference.region_locale (
    region_id uuid NOT NULL,
    locale_id uuid NOT NULL,
    name text NOT NULL,
    CONSTRAINT region_locale_pkey PRIMARY KEY (region_id, locale_id),
    CONSTRAINT region_locale_name_trimmed CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$'),
    CONSTRAINT region_locale_region_fk FOREIGN KEY (region_id)
        REFERENCES reference.region (region_id),
    CONSTRAINT region_locale_locale_fk FOREIGN KEY (locale_id)
        REFERENCES reference.locale (locale_id)
);

CREATE TABLE reference.subregion_locale (
    subregion_id uuid NOT NULL,
    locale_id uuid NOT NULL,
    name text NOT NULL,
    CONSTRAINT subregion_locale_pkey PRIMARY KEY (subregion_id, locale_id),
    CONSTRAINT subregion_locale_name_trimmed
        CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$'),
    CONSTRAINT subregion_locale_subregion_fk FOREIGN KEY (subregion_id)
        REFERENCES reference.subregion (subregion_id),
    CONSTRAINT subregion_locale_locale_fk FOREIGN KEY (locale_id)
        REFERENCES reference.locale (locale_id)
);

CREATE TABLE reference.subregion_reclassification (
    subregion_id uuid NOT NULL,
    snapshot_version bigint NOT NULL,
    previous_region_id uuid NOT NULL,
    new_region_id uuid NOT NULL,
    CONSTRAINT subregion_reclassification_pkey PRIMARY KEY (subregion_id, snapshot_version),
    CONSTRAINT subregion_reclassification_changes_region
        CHECK (previous_region_id <> new_region_id),
    CONSTRAINT subregion_reclassification_subregion_fk FOREIGN KEY (subregion_id)
        REFERENCES reference.subregion (subregion_id),
    CONSTRAINT subregion_reclassification_snapshot_fk FOREIGN KEY (snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version),
    CONSTRAINT subregion_reclassification_previous_fk FOREIGN KEY (previous_region_id)
        REFERENCES reference.region (region_id),
    CONSTRAINT subregion_reclassification_new_fk FOREIGN KEY (new_region_id)
        REFERENCES reference.region (region_id)
);

CREATE TABLE reference.region_recoding (
    region_id uuid NOT NULL,
    snapshot_version bigint NOT NULL,
    previous_code text,
    new_code text,
    provenance jsonb NOT NULL,
    CONSTRAINT region_recoding_pkey PRIMARY KEY (region_id, snapshot_version),
    CONSTRAINT region_recoding_changes_code CHECK (previous_code IS DISTINCT FROM new_code),
    CONSTRAINT region_recoding_code_format
        CHECK (previous_code ~ '^[0-9]{3}$' AND new_code ~ '^[0-9]{3}$'),
    CONSTRAINT region_recoding_region_fk FOREIGN KEY (region_id)
        REFERENCES reference.region (region_id),
    CONSTRAINT region_recoding_snapshot_fk FOREIGN KEY (snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version)
);

CREATE TABLE reference.subregion_recoding (
    subregion_id uuid NOT NULL,
    snapshot_version bigint NOT NULL,
    previous_code text,
    new_code text,
    provenance jsonb NOT NULL,
    CONSTRAINT subregion_recoding_pkey PRIMARY KEY (subregion_id, snapshot_version),
    CONSTRAINT subregion_recoding_changes_code CHECK (previous_code IS DISTINCT FROM new_code),
    CONSTRAINT subregion_recoding_code_format
        CHECK (previous_code ~ '^[0-9]{3}$' AND new_code ~ '^[0-9]{3}$'),
    CONSTRAINT subregion_recoding_subregion_fk FOREIGN KEY (subregion_id)
        REFERENCES reference.subregion (subregion_id),
    CONSTRAINT subregion_recoding_snapshot_fk FOREIGN KEY (snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version)
);

-- Historial y trazas: inmutables (RNF-5).
CREATE FUNCTION reference.reject_region_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reference.% is immutable', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Entidades y nombres publicados nunca se borran (RF-22, RF-30).
CREATE FUNCTION reference.reject_region_catalog_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published rows of reference.% are never deleted', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Las columnas de identidad que recibe como argumentos no cambian una vez publicadas (RF-2).
CREATE FUNCTION reference.reject_region_identity_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    identity_column text;
BEGIN
    FOREACH identity_column IN ARRAY TG_ARGV LOOP
        IF to_jsonb(NEW) -> identity_column IS DISTINCT FROM to_jsonb(OLD) -> identity_column THEN
            RAISE EXCEPTION 'reference.%.% is immutable once published',
                TG_TABLE_NAME, identity_column
                USING ERRCODE = 'restrict_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END
$$;

-- RF-4: un código no puede ser a la vez el vigente de una Region y de una Subregion `active`. Se
-- evalúa al commit (constraint trigger diferido), sobre el estado final (RF-42).
CREATE FUNCTION reference.check_active_code_disjoint() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM reference.region r
        JOIN reference.subregion s ON s.code = r.code
        WHERE r.status = 'active' AND s.status = 'active'
    ) THEN
        RAISE EXCEPTION 'an active region and an active subregion share a code'
            USING ERRCODE = 'exclusion_violation',
                  CONSTRAINT = 'region_subregion_active_code_disjoint';
    END IF;
    RETURN NULL;
END
$$;

-- RF-36: ninguna Subregion `active` dentro de una Region `inactive`.
CREATE FUNCTION reference.check_active_subregion_region() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM reference.subregion s
        JOIN reference.region r ON r.region_id = s.region_id
        WHERE s.status = 'active' AND r.status = 'inactive'
    ) THEN
        RAISE EXCEPTION 'an active subregion belongs to an inactive region'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'subregion_active_requires_active_region';
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER region_snapshot_immutable
    BEFORE UPDATE OR DELETE ON reference.region_snapshot
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_history_change();
CREATE TRIGGER region_snapshot_no_truncate
    BEFORE TRUNCATE ON reference.region_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_history_change();

CREATE TRIGGER subregion_reclassification_immutable
    BEFORE UPDATE OR DELETE ON reference.subregion_reclassification
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_history_change();
CREATE TRIGGER subregion_reclassification_no_truncate
    BEFORE TRUNCATE ON reference.subregion_reclassification
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_history_change();

CREATE TRIGGER region_recoding_immutable
    BEFORE UPDATE OR DELETE ON reference.region_recoding
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_history_change();
CREATE TRIGGER region_recoding_no_truncate
    BEFORE TRUNCATE ON reference.region_recoding
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_history_change();

CREATE TRIGGER subregion_recoding_immutable
    BEFORE UPDATE OR DELETE ON reference.subregion_recoding
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_history_change();
CREATE TRIGGER subregion_recoding_no_truncate
    BEFORE TRUNCATE ON reference.subregion_recoding
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_history_change();

CREATE TRIGGER region_no_delete
    BEFORE DELETE ON reference.region
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER region_no_truncate
    BEFORE TRUNCATE ON reference.region
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER region_identity_immutable
    BEFORE UPDATE ON reference.region
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_region_identity_change('region_id', 'first_snapshot_version');

CREATE TRIGGER subregion_no_delete
    BEFORE DELETE ON reference.subregion
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER subregion_no_truncate
    BEFORE TRUNCATE ON reference.subregion
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER subregion_identity_immutable
    BEFORE UPDATE ON reference.subregion
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_region_identity_change('subregion_id', 'first_snapshot_version');

CREATE TRIGGER region_locale_no_delete
    BEFORE DELETE ON reference.region_locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER region_locale_no_truncate
    BEFORE TRUNCATE ON reference.region_locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER region_locale_identity_immutable
    BEFORE UPDATE ON reference.region_locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_identity_change('region_id', 'locale_id');

CREATE TRIGGER subregion_locale_no_delete
    BEFORE DELETE ON reference.subregion_locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER subregion_locale_no_truncate
    BEFORE TRUNCATE ON reference.subregion_locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_region_catalog_delete();
CREATE TRIGGER subregion_locale_identity_immutable
    BEFORE UPDATE ON reference.subregion_locale
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_region_identity_change('subregion_id', 'locale_id');

CREATE CONSTRAINT TRIGGER region_active_code_disjoint
    AFTER INSERT OR UPDATE ON reference.region DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_active_code_disjoint();
CREATE CONSTRAINT TRIGGER subregion_active_code_disjoint
    AFTER INSERT OR UPDATE ON reference.subregion DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_active_code_disjoint();

CREATE CONSTRAINT TRIGGER region_active_subregions
    AFTER UPDATE ON reference.region DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_active_subregion_region();
CREATE CONSTRAINT TRIGGER subregion_active_region
    AFTER INSERT OR UPDATE ON reference.subregion DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_active_subregion_region();
"""

# Aislamiento (D10 de 001): nada para PUBLIC ni para los roles de la API de Supabase. Los permisos
# se otorgan solo a los roles que ya existen; el runbook documenta el bloque para después.
GRANTS = f"""
REVOKE ALL ON ALL TABLES IN SCHEMA reference FROM PUBLIC;

DO $$
DECLARE
    api_role text;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA reference FROM %I', api_role);
        END IF;
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reference_reader') THEN
        GRANT SELECT ON {TABLES} TO reference_reader;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reference_loader') THEN
        GRANT SELECT, INSERT ON {TABLES} TO reference_loader;
        GRANT UPDATE (code, code_snapshot_version, status, replacement_region_id)
            ON reference.region TO reference_loader;
        GRANT UPDATE (region_id, code, code_snapshot_version, status, replacement_subregion_id)
            ON reference.subregion TO reference_loader;
        GRANT UPDATE (name) ON reference.region_locale, reference.subregion_locale
            TO reference_loader;
    END IF;
END
$$;
"""

DOWNGRADE = """
DROP TABLE reference.subregion_recoding;
DROP TABLE reference.region_recoding;
DROP TABLE reference.subregion_reclassification;
DROP TABLE reference.subregion_locale;
DROP TABLE reference.region_locale;
DROP TABLE reference.subregion;
DROP TABLE reference.region;
DROP TABLE reference.region_snapshot;
DROP FUNCTION reference.check_active_subregion_region();
DROP FUNCTION reference.check_active_code_disjoint();
DROP FUNCTION reference.reject_region_identity_change();
DROP FUNCTION reference.reject_region_catalog_delete();
DROP FUNCTION reference.reject_region_history_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute(DOWNGRADE)
