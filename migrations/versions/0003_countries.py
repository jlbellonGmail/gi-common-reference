"""Catálogo global de países (spec 003, plan "Datos").

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = (
    "reference.country_snapshot, reference.country, reference.country_locale, "
    "reference.country_flag, reference.country_recoding"
)

UPGRADE = r"""
CREATE TABLE reference.country_snapshot (
    snapshot_version bigint NOT NULL,
    content_digest text NOT NULL,
    locale_snapshot_version bigint NOT NULL,
    -- Versión de Region/Subregion con la que se construyó el snapshot (declarada, RF-47) y la
    -- vigente al incorporarlo.
    region_snapshot_version bigint NOT NULL,
    region_current_snapshot_version bigint NOT NULL,
    required_locales_version integer NOT NULL,
    provenance jsonb NOT NULL,
    artifact jsonb NOT NULL,
    incorporated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT country_snapshot_pkey PRIMARY KEY (snapshot_version),
    CONSTRAINT country_snapshot_version_positive CHECK (snapshot_version > 0),
    CONSTRAINT country_snapshot_required_locales_version_positive
        CHECK (required_locales_version > 0),
    CONSTRAINT country_snapshot_region_versions_ordered
        CHECK (region_current_snapshot_version >= region_snapshot_version),
    CONSTRAINT country_snapshot_locale_snapshot_fk FOREIGN KEY (locale_snapshot_version)
        REFERENCES reference.locale_snapshot (snapshot_version),
    CONSTRAINT country_snapshot_region_declared_fk FOREIGN KEY (region_snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version),
    CONSTRAINT country_snapshot_region_current_fk FOREIGN KEY (region_current_snapshot_version)
        REFERENCES reference.region_snapshot (snapshot_version)
);

-- Sin ningún texto dependiente del idioma (RF-34): los nombres viven en `country_locale`.
CREATE TABLE reference.country (
    country_id uuid NOT NULL,
    alpha2 text NOT NULL,
    alpha3 text NOT NULL,
    numeric_code text NOT NULL,
    region_id uuid,
    subregion_id uuid,
    calling_code text,
    status text NOT NULL,
    replacement_country_id uuid,
    first_snapshot_version bigint NOT NULL,
    codes_snapshot_version bigint NOT NULL,
    last_changed_snapshot_version bigint NOT NULL,
    CONSTRAINT country_pkey PRIMARY KEY (country_id),
    CONSTRAINT country_alpha2_format CHECK (alpha2 ~ '^[A-Z]{2}$'),
    CONSTRAINT country_alpha3_format CHECK (alpha3 ~ '^[A-Z]{3}$'),
    CONSTRAINT country_numeric_code_format CHECK (numeric_code ~ '^[0-9]{3}$'),
    CONSTRAINT country_calling_code_format CHECK (calling_code ~ '^[1-9][0-9]{0,2}$'),
    CONSTRAINT country_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT country_replacement_not_self CHECK (replacement_country_id <> country_id),
    CONSTRAINT country_replacement_requires_inactive
        CHECK (replacement_country_id IS NULL OR status = 'inactive'),
    CONSTRAINT country_subregion_requires_region
        CHECK (subregion_id IS NULL OR region_id IS NOT NULL),
    -- RF-3, RF-44: unicidad entre `active` sobre el estado final de la transacción.
    CONSTRAINT country_alpha2_active_unique EXCLUDE USING btree (alpha2 WITH =)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT country_alpha3_active_unique EXCLUDE USING btree (alpha3 WITH =)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT country_numeric_code_active_unique EXCLUDE USING btree (numeric_code WITH =)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT country_replacement_fk FOREIGN KEY (replacement_country_id)
        REFERENCES reference.country (country_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT country_region_fk FOREIGN KEY (region_id)
        REFERENCES reference.region (region_id),
    -- RF-6, RF-29 de 002: el par pertenece a una Subregion de esa Region. MATCH SIMPLE: sin
    -- `subregion_id` no se evalúa. Diferida para que una reclasificación de 002 y la corrección
    -- de este catálogo puedan ir en la misma transacción (RF-35 de 002).
    CONSTRAINT country_classification_fk FOREIGN KEY (region_id, subregion_id)
        REFERENCES reference.subregion (region_id, subregion_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT country_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version),
    CONSTRAINT country_codes_snapshot_fk FOREIGN KEY (codes_snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version),
    CONSTRAINT country_last_changed_snapshot_fk FOREIGN KEY (last_changed_snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version)
);

CREATE TABLE reference.country_locale (
    country_id uuid NOT NULL,
    locale_id uuid NOT NULL,
    name text NOT NULL,
    official_name text,
    CONSTRAINT country_locale_pkey PRIMARY KEY (country_id, locale_id),
    CONSTRAINT country_locale_name_trimmed CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$'),
    CONSTRAINT country_locale_official_name_trimmed
        CHECK (official_name IS NULL
               OR (official_name <> '' AND official_name !~ '^\s' AND official_name !~ '\s$')),
    CONSTRAINT country_locale_country_fk FOREIGN KEY (country_id)
        REFERENCES reference.country (country_id),
    CONSTRAINT country_locale_locale_fk FOREIGN KEY (locale_id)
        REFERENCES reference.locale (locale_id)
);

-- Referencia al asset SVG (nunca el binario, D-3) o excepción declarada con motivo (RF-19).
CREATE TABLE reference.country_flag (
    country_id uuid NOT NULL,
    asset_path text,
    sha256 text,
    exception_reason text,
    snapshot_version bigint NOT NULL,
    CONSTRAINT country_flag_pkey PRIMARY KEY (country_id),
    CONSTRAINT country_flag_asset_path_format
        CHECK (asset_path ~ '^[A-Za-z0-9_-]+\.svg$'),
    CONSTRAINT country_flag_sha256_format CHECK (sha256 ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT country_flag_exception_reason_trimmed
        CHECK (exception_reason IS NULL
               OR (exception_reason <> '' AND exception_reason !~ '^\s'
                   AND exception_reason !~ '\s$')),
    CONSTRAINT country_flag_declaration_exclusive CHECK (
        (asset_path IS NOT NULL AND sha256 IS NOT NULL AND exception_reason IS NULL)
        OR (asset_path IS NULL AND sha256 IS NULL AND exception_reason IS NOT NULL)),
    CONSTRAINT country_flag_country_fk FOREIGN KEY (country_id)
        REFERENCES reference.country (country_id),
    CONSTRAINT country_flag_snapshot_fk FOREIGN KEY (snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version)
);

-- Una recodificación cambia la tripleta ISO completa de la misma entidad (RF-4, RF-41, RF-46).
CREATE TABLE reference.country_recoding (
    country_id uuid NOT NULL,
    snapshot_version bigint NOT NULL,
    previous_alpha2 text NOT NULL,
    previous_alpha3 text NOT NULL,
    previous_numeric_code text NOT NULL,
    new_alpha2 text NOT NULL,
    new_alpha3 text NOT NULL,
    new_numeric_code text NOT NULL,
    provenance jsonb NOT NULL,
    CONSTRAINT country_recoding_pkey PRIMARY KEY (country_id, snapshot_version),
    CONSTRAINT country_recoding_code_format CHECK (
        previous_alpha2 ~ '^[A-Z]{2}$' AND new_alpha2 ~ '^[A-Z]{2}$'
        AND previous_alpha3 ~ '^[A-Z]{3}$' AND new_alpha3 ~ '^[A-Z]{3}$'
        AND previous_numeric_code ~ '^[0-9]{3}$' AND new_numeric_code ~ '^[0-9]{3}$'),
    CONSTRAINT country_recoding_changes_code CHECK (
        (previous_alpha2, previous_alpha3, previous_numeric_code)
        IS DISTINCT FROM (new_alpha2, new_alpha3, new_numeric_code)),
    CONSTRAINT country_recoding_country_fk FOREIGN KEY (country_id)
        REFERENCES reference.country (country_id),
    CONSTRAINT country_recoding_snapshot_fk FOREIGN KEY (snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version)
);

-- Historial y trazas: inmutables (RNF-2, RNF-5).
CREATE FUNCTION reference.reject_country_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reference.% is immutable', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Países, localizaciones y banderas publicados nunca se borran (RF-7, RF-21).
CREATE FUNCTION reference.reject_country_catalog_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published rows of reference.% are never deleted', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Las columnas de identidad que recibe como argumentos no cambian una vez publicadas (RF-2).
CREATE FUNCTION reference.reject_country_identity_change() RETURNS trigger
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

-- `codes_snapshot_version` avanza si y solo si cambia la tripleta ISO (RF-51).
CREATE FUNCTION reference.check_country_codes_snapshot_coupled() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    triple_changed boolean :=
        (NEW.alpha2, NEW.alpha3, NEW.numeric_code)
        IS DISTINCT FROM (OLD.alpha2, OLD.alpha3, OLD.numeric_code);
    version_changed boolean :=
        NEW.codes_snapshot_version IS DISTINCT FROM OLD.codes_snapshot_version;
BEGIN
    IF triple_changed <> version_changed THEN
        RAISE EXCEPTION 'reference.country.codes_snapshot_version must change with the code triple'
            USING ERRCODE = 'restrict_violation',
                  CONSTRAINT = 'country_codes_snapshot_coupled';
    END IF;
    RETURN NEW;
END
$$;

-- RF-4, RF-41: la tripleta solo cambia con la traza de recodificación del mismo snapshot que
-- describe exactamente el cambio. Se evalúa al commit: la traza puede escribirse después.
CREATE FUNCTION reference.check_country_codes_require_recoding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM reference.country_recoding r
        WHERE r.country_id = NEW.country_id
          AND r.snapshot_version = NEW.codes_snapshot_version
          AND (r.previous_alpha2, r.previous_alpha3, r.previous_numeric_code)
              = (OLD.alpha2, OLD.alpha3, OLD.numeric_code)
          AND (r.new_alpha2, r.new_alpha3, r.new_numeric_code)
              = (NEW.alpha2, NEW.alpha3, NEW.numeric_code)
    ) THEN
        RAISE EXCEPTION 'a country code change needs its recoding trace in the same snapshot'
            USING ERRCODE = 'restrict_violation',
                  CONSTRAINT = 'country_codes_require_recoding';
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER country_snapshot_immutable
    BEFORE UPDATE OR DELETE ON reference.country_snapshot
    FOR EACH ROW EXECUTE FUNCTION reference.reject_country_history_change();
CREATE TRIGGER country_snapshot_no_truncate
    BEFORE TRUNCATE ON reference.country_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_country_history_change();

CREATE TRIGGER country_recoding_immutable
    BEFORE UPDATE OR DELETE ON reference.country_recoding
    FOR EACH ROW EXECUTE FUNCTION reference.reject_country_history_change();
CREATE TRIGGER country_recoding_no_truncate
    BEFORE TRUNCATE ON reference.country_recoding
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_country_history_change();

CREATE TRIGGER country_no_delete
    BEFORE DELETE ON reference.country
    FOR EACH ROW EXECUTE FUNCTION reference.reject_country_catalog_delete();
CREATE TRIGGER country_no_truncate
    BEFORE TRUNCATE ON reference.country
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_country_catalog_delete();
CREATE TRIGGER country_identity_immutable
    BEFORE UPDATE ON reference.country
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_country_identity_change('country_id', 'first_snapshot_version');
CREATE TRIGGER country_codes_snapshot_coupled
    BEFORE UPDATE ON reference.country
    FOR EACH ROW EXECUTE FUNCTION reference.check_country_codes_snapshot_coupled();
CREATE CONSTRAINT TRIGGER country_codes_require_recoding
    AFTER UPDATE ON reference.country DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    WHEN ((OLD.alpha2, OLD.alpha3, OLD.numeric_code)
          IS DISTINCT FROM (NEW.alpha2, NEW.alpha3, NEW.numeric_code))
    EXECUTE FUNCTION reference.check_country_codes_require_recoding();

CREATE TRIGGER country_locale_no_delete
    BEFORE DELETE ON reference.country_locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_country_catalog_delete();
CREATE TRIGGER country_locale_no_truncate
    BEFORE TRUNCATE ON reference.country_locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_country_catalog_delete();
CREATE TRIGGER country_locale_identity_immutable
    BEFORE UPDATE ON reference.country_locale
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_country_identity_change('country_id', 'locale_id');

CREATE TRIGGER country_flag_no_delete
    BEFORE DELETE ON reference.country_flag
    FOR EACH ROW EXECUTE FUNCTION reference.reject_country_catalog_delete();
CREATE TRIGGER country_flag_no_truncate
    BEFORE TRUNCATE ON reference.country_flag
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_country_catalog_delete();
CREATE TRIGGER country_flag_identity_immutable
    BEFORE UPDATE ON reference.country_flag
    FOR EACH ROW EXECUTE FUNCTION reference.reject_country_identity_change('country_id');
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
        GRANT UPDATE (alpha2, alpha3, numeric_code, codes_snapshot_version, region_id,
                      subregion_id, calling_code, status, replacement_country_id,
                      last_changed_snapshot_version)
            ON reference.country TO reference_loader;
        GRANT UPDATE (name, official_name) ON reference.country_locale TO reference_loader;
        GRANT UPDATE (asset_path, sha256, exception_reason, snapshot_version)
            ON reference.country_flag TO reference_loader;
    END IF;
END
$$;
"""

DOWNGRADE = """
DROP TABLE reference.country_recoding;
DROP TABLE reference.country_flag;
DROP TABLE reference.country_locale;
DROP TABLE reference.country;
DROP TABLE reference.country_snapshot;
DROP FUNCTION reference.check_country_codes_require_recoding();
DROP FUNCTION reference.check_country_codes_snapshot_coupled();
DROP FUNCTION reference.reject_country_identity_change();
DROP FUNCTION reference.reject_country_catalog_delete();
DROP FUNCTION reference.reject_country_history_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute(DOWNGRADE)
