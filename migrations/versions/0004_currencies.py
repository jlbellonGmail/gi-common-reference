"""Catálogo global de monedas y CountryCurrency temporal (spec 004, plan "Datos").

Revision ID: 0004
Revises: 0003

Requiere la extensión `btree_gist` (exclusión temporal por par país-moneda, D10 del plan) y la
función `reference.is_strictly_ascending(uuid[])` creada por `0003`.
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = (
    "reference.currency_snapshot, reference.currency, reference.currency_locale, "
    "reference.country_currency"
)

UPGRADE = r"""
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE reference.currency_snapshot (
    snapshot_version bigint NOT NULL,
    content_digest text NOT NULL,
    locale_snapshot_version bigint NOT NULL,
    -- Versión de Countries con la que se construyó el snapshot (declarada, RF-41) y la vigente al
    -- incorporarlo.
    country_snapshot_version bigint NOT NULL,
    country_current_snapshot_version bigint NOT NULL,
    required_locales_version integer NOT NULL,
    provenance jsonb NOT NULL,
    artifact jsonb NOT NULL,
    incorporated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT currency_snapshot_pkey PRIMARY KEY (snapshot_version),
    CONSTRAINT currency_snapshot_version_positive CHECK (snapshot_version > 0),
    CONSTRAINT currency_snapshot_required_locales_version_positive
        CHECK (required_locales_version > 0),
    CONSTRAINT currency_snapshot_country_versions_ordered
        CHECK (country_current_snapshot_version >= country_snapshot_version),
    CONSTRAINT currency_snapshot_locale_snapshot_fk FOREIGN KEY (locale_snapshot_version)
        REFERENCES reference.locale_snapshot (snapshot_version),
    CONSTRAINT currency_snapshot_country_declared_fk FOREIGN KEY (country_snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version),
    CONSTRAINT currency_snapshot_country_current_fk
        FOREIGN KEY (country_current_snapshot_version)
        REFERENCES reference.country_snapshot (snapshot_version)
);

-- Sin ningún texto dependiente del idioma (D-4): los nombres viven en `currency_locale`.
-- `minor_units` NULL es "no aplicable" (ISO N.A.), distinto de 0 (D5 del plan).
CREATE TABLE reference.currency (
    currency_id uuid NOT NULL,
    alphabetic_code text NOT NULL,
    numeric_code text NOT NULL,
    minor_units smallint,
    fund_code boolean NOT NULL,
    status text NOT NULL,
    replacement_currency_ids uuid[] NOT NULL DEFAULT '{}',
    first_snapshot_version bigint NOT NULL,
    last_changed_snapshot_version bigint NOT NULL,
    CONSTRAINT currency_pkey PRIMARY KEY (currency_id),
    CONSTRAINT currency_alphabetic_code_format CHECK (alphabetic_code ~ '^[A-Z]{3}$'),
    CONSTRAINT currency_numeric_code_format CHECK (numeric_code ~ '^[0-9]{3}$'),
    CONSTRAINT currency_minor_units_valid CHECK (minor_units IS NULL OR minor_units >= 0),
    CONSTRAINT currency_status_valid CHECK (status IN ('active', 'inactive')),
    -- Reemplazos 0..N (RF-6, D-17): sin nulos, ascendentes y sin repetidos, sin la propia moneda
    -- y solo en una Currency `inactive`. Que cada sucesor exista y que no haya ciclos lo exigen
    -- constraint triggers diferidos.
    CONSTRAINT currency_replacement_no_nulls
        CHECK (array_position(replacement_currency_ids, NULL) IS NULL),
    CONSTRAINT currency_replacement_ascending_unique
        CHECK (reference.is_strictly_ascending(replacement_currency_ids)),
    CONSTRAINT currency_replacement_not_self
        CHECK (NOT (currency_id = ANY (replacement_currency_ids))),
    CONSTRAINT currency_replacement_requires_inactive
        CHECK (cardinality(replacement_currency_ids) = 0 OR status = 'inactive'),
    -- D-15: el código alfabético queda ligado a una única Currency, incluidas las inactivas.
    CONSTRAINT currency_alphabetic_code_unique UNIQUE (alphabetic_code),
    -- D-15, RF-3: el numérico es único solo entre activas, sobre el estado final de la transacción.
    CONSTRAINT currency_numeric_code_active_unique EXCLUDE USING btree (numeric_code WITH =)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT currency_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.currency_snapshot (snapshot_version),
    CONSTRAINT currency_last_changed_snapshot_fk FOREIGN KEY (last_changed_snapshot_version)
        REFERENCES reference.currency_snapshot (snapshot_version)
);

CREATE TABLE reference.currency_locale (
    currency_id uuid NOT NULL,
    locale_id uuid NOT NULL,
    name text NOT NULL,
    CONSTRAINT currency_locale_pkey PRIMARY KEY (currency_id, locale_id),
    CONSTRAINT currency_locale_name_trimmed CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$'),
    CONSTRAINT currency_locale_currency_fk FOREIGN KEY (currency_id)
        REFERENCES reference.currency (currency_id),
    CONSTRAINT currency_locale_locale_fk FOREIGN KEY (locale_id)
        REFERENCES reference.locale (locale_id)
);

-- CountryCurrency (D-16, D-18). `status` es el ciclo de vida del registro; la vigencia temporal
-- (`valid_from`, `valid_to`) es el período real, semiabierto [valid_from, valid_to) y de día
-- calendario; NULL es un extremo no acotado (RF-44). Ninguna columna deriva de la otra (RF-51).
CREATE TABLE reference.country_currency (
    country_currency_id uuid NOT NULL,
    country_id uuid NOT NULL,
    currency_id uuid NOT NULL,
    status text NOT NULL,
    valid_from date,
    valid_to date,
    -- Un inicio posterior al fin daría error de rango antes de que actúe el CHECK; se mapea al
    -- rango vacío para que lo rechace `country_currency_validity_ordered`, con su nombre.
    validity daterange GENERATED ALWAYS AS (
        CASE WHEN valid_from > valid_to THEN 'empty'::daterange
             ELSE daterange(valid_from, valid_to, '[)') END) STORED,
    first_snapshot_version bigint NOT NULL,
    last_changed_snapshot_version bigint NOT NULL,
    CONSTRAINT country_currency_pkey PRIMARY KEY (country_currency_id),
    CONSTRAINT country_currency_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT country_currency_valid_from_finite
        CHECK (valid_from IS NULL OR isfinite(valid_from)),
    CONSTRAINT country_currency_valid_to_finite CHECK (valid_to IS NULL OR isfinite(valid_to)),
    CONSTRAINT country_currency_validity_ordered
        CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to),
    -- RF-45: dos asociaciones `active` del mismo par no se solapan. Monedas distintas del mismo
    -- país, o la misma moneda en países distintos, no se excluyen entre sí (RF-18). Diferida para
    -- que un snapshot pueda reordenar períodos dentro de la misma transacción.
    CONSTRAINT country_currency_active_no_overlap EXCLUDE USING gist (
        country_id WITH =, currency_id WITH =, validity WITH &&)
        WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT country_currency_country_fk FOREIGN KEY (country_id)
        REFERENCES reference.country (country_id),
    CONSTRAINT country_currency_currency_fk FOREIGN KEY (currency_id)
        REFERENCES reference.currency (currency_id),
    CONSTRAINT country_currency_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.currency_snapshot (snapshot_version),
    CONSTRAINT country_currency_last_changed_snapshot_fk
        FOREIGN KEY (last_changed_snapshot_version)
        REFERENCES reference.currency_snapshot (snapshot_version)
);

CREATE INDEX country_currency_country_idx
    ON reference.country_currency (country_id, currency_id);
CREATE INDEX country_currency_currency_idx
    ON reference.country_currency (currency_id, country_id);

-- Historial y trazas: inmutables (RNF-2, RNF-5).
CREATE FUNCTION reference.reject_currency_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reference.% is immutable', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Monedas, localizaciones y asociaciones publicadas nunca se borran (RF-7, RF-37).
CREATE FUNCTION reference.reject_currency_catalog_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published rows of reference.% are never deleted', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Las columnas de identidad que recibe como argumentos no cambian una vez publicadas (RF-2, RF-5).
CREATE FUNCTION reference.reject_currency_identity_change() RETURNS trigger
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

-- RF-47: la historia no se reescribe. Un extremo de vigencia ya fijado no cambia (ni se vacía); uno
-- ausente puede completarse, y desde entonces es inmutable. Corregir un período es retirar el
-- registro (`inactive`) y crear otro.
CREATE FUNCTION reference.check_country_currency_validity_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.valid_from IS NOT NULL AND NEW.valid_from IS DISTINCT FROM OLD.valid_from THEN
        RAISE EXCEPTION 'reference.country_currency.valid_from is immutable once set'
            USING ERRCODE = 'restrict_violation',
                  CONSTRAINT = 'country_currency_valid_from_immutable';
    END IF;
    IF OLD.valid_to IS NOT NULL AND NEW.valid_to IS DISTINCT FROM OLD.valid_to THEN
        RAISE EXCEPTION 'reference.country_currency.valid_to is immutable once set'
            USING ERRCODE = 'restrict_violation',
                  CONSTRAINT = 'country_currency_valid_to_immutable';
    END IF;
    RETURN NEW;
END
$$;

-- RF-6: cada sucesor existe al commit (una FK no aplica a un arreglo). Las monedas no se borran,
-- así que existir al commit basta. `check_violation` lo informa como un rechazo, no como una FK.
CREATE FUNCTION reference.check_currency_replacements_exist() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM unnest(NEW.replacement_currency_ids) AS r(successor_id)
        WHERE NOT EXISTS (
            SELECT 1 FROM reference.currency c WHERE c.currency_id = r.successor_id
        )
    ) THEN
        RAISE EXCEPTION 'a replacement of reference.currency does not exist'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'currency_replacement_exists';
    END IF;
    RETURN NULL;
END
$$;

-- RF-6, CA-3: el grafo de reemplazos no tiene ciclos. Se evalúa al commit sobre el estado final;
-- todo ciclo nuevo pasa por al menos una fila modificada, cuyo trigger lo detecta. `UNION` (no
-- `UNION ALL`) deduplica, así la recursión termina aunque existan otros ciclos.
CREATE FUNCTION reference.check_currency_replacements_acyclic() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        WITH RECURSIVE reach(currency_id) AS (
            SELECT s.successor_id
            FROM reference.currency c, unnest(c.replacement_currency_ids) AS s(successor_id)
            WHERE c.currency_id = NEW.currency_id
            UNION
            SELECT s.successor_id
            FROM reach r
            JOIN reference.currency c ON c.currency_id = r.currency_id,
            unnest(c.replacement_currency_ids) AS s(successor_id)
        )
        SELECT 1 FROM reach WHERE currency_id = NEW.currency_id
    ) THEN
        RAISE EXCEPTION 'the replacement graph of reference.currency has a cycle'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'currency_replacement_acyclic';
    END IF;
    RETURN NULL;
END
$$;

-- RF-19, D12 del plan: una asociación `active` de vigencia abierta (sin fin) exige Country y
-- Currency `active`. Una asociación cerrada es historia y puede referenciar entidades `inactive`.
-- Solo lee `reference.country`: Countries no depende de Currency (S-8, RNF-6).
CREATE FUNCTION reference.check_country_currency_open_targets_active() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'active' AND NEW.valid_to IS NULL AND (
        EXISTS (SELECT 1 FROM reference.country c
                WHERE c.country_id = NEW.country_id AND c.status <> 'active')
        OR EXISTS (SELECT 1 FROM reference.currency u
                   WHERE u.currency_id = NEW.currency_id AND u.status <> 'active')
    ) THEN
        RAISE EXCEPTION 'an open active country_currency needs an active country and currency'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'country_currency_open_requires_active_targets';
    END IF;
    RETURN NULL;
END
$$;

-- RF-19, RF-38: una Currency que pasa a `inactive` no puede conservar asociaciones `active` sin
-- fin; su vigencia se cierra en el mismo snapshot.
CREATE FUNCTION reference.check_currency_inactive_has_no_open_associations() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM reference.country_currency a
        WHERE a.currency_id = NEW.currency_id AND a.status = 'active' AND a.valid_to IS NULL
    ) THEN
        RAISE EXCEPTION 'an inactive currency cannot keep open active country_currency rows'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'currency_inactive_has_open_associations';
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER currency_snapshot_immutable
    BEFORE UPDATE OR DELETE ON reference.currency_snapshot
    FOR EACH ROW EXECUTE FUNCTION reference.reject_currency_history_change();
CREATE TRIGGER currency_snapshot_no_truncate
    BEFORE TRUNCATE ON reference.currency_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_currency_history_change();

CREATE TRIGGER currency_no_delete
    BEFORE DELETE ON reference.currency
    FOR EACH ROW EXECUTE FUNCTION reference.reject_currency_catalog_delete();
CREATE TRIGGER currency_no_truncate
    BEFORE TRUNCATE ON reference.currency
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_currency_catalog_delete();
CREATE TRIGGER currency_identity_immutable
    BEFORE UPDATE ON reference.currency
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_currency_identity_change(
            'currency_id', 'alphabetic_code', 'numeric_code', 'first_snapshot_version');
CREATE CONSTRAINT TRIGGER currency_replacement_exists
    AFTER INSERT OR UPDATE OF replacement_currency_ids ON reference.currency
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_currency_replacements_exist();
CREATE CONSTRAINT TRIGGER currency_replacement_acyclic
    AFTER INSERT OR UPDATE OF replacement_currency_ids ON reference.currency
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_currency_replacements_acyclic();
CREATE CONSTRAINT TRIGGER currency_inactive_has_no_open_associations
    AFTER UPDATE OF status ON reference.currency
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.status <> 'active')
    EXECUTE FUNCTION reference.check_currency_inactive_has_no_open_associations();

CREATE TRIGGER currency_locale_no_delete
    BEFORE DELETE ON reference.currency_locale
    FOR EACH ROW EXECUTE FUNCTION reference.reject_currency_catalog_delete();
CREATE TRIGGER currency_locale_no_truncate
    BEFORE TRUNCATE ON reference.currency_locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_currency_catalog_delete();
CREATE TRIGGER currency_locale_identity_immutable
    BEFORE UPDATE ON reference.currency_locale
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_currency_identity_change('currency_id', 'locale_id');

CREATE TRIGGER country_currency_no_delete
    BEFORE DELETE ON reference.country_currency
    FOR EACH ROW EXECUTE FUNCTION reference.reject_currency_catalog_delete();
CREATE TRIGGER country_currency_no_truncate
    BEFORE TRUNCATE ON reference.country_currency
    FOR EACH STATEMENT EXECUTE FUNCTION reference.reject_currency_catalog_delete();
CREATE TRIGGER country_currency_identity_immutable
    BEFORE UPDATE ON reference.country_currency
    FOR EACH ROW EXECUTE FUNCTION
        reference.reject_currency_identity_change(
            'country_currency_id', 'country_id', 'currency_id', 'first_snapshot_version');
CREATE TRIGGER country_currency_validity_history
    BEFORE UPDATE ON reference.country_currency
    FOR EACH ROW EXECUTE FUNCTION reference.check_country_currency_validity_history();
CREATE CONSTRAINT TRIGGER country_currency_open_requires_active_targets
    AFTER INSERT OR UPDATE ON reference.country_currency
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.check_country_currency_open_targets_active();

-- D12 del plan: detecta la deriva entre catálogos. Un Country retirado por 003 después de que
-- Currency lo asociara no puede bloquearse desde aquí (S-8); la vista y `check-integrity` lo
-- hacen visible. Vacía en un catálogo íntegro.
CREATE VIEW reference.country_currency_integrity_violation AS
SELECT a.country_currency_id,
       a.country_id,
       a.currency_id,
       c.status <> 'active' AS country_not_active,
       u.status <> 'active' AS currency_not_active
FROM reference.country_currency a
JOIN reference.country c ON c.country_id = a.country_id
JOIN reference.currency u ON u.currency_id = a.currency_id
WHERE a.status = 'active' AND a.valid_to IS NULL
  AND (c.status <> 'active' OR u.status <> 'active');
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
        GRANT SELECT ON {TABLES}, reference.country_currency_integrity_violation
            TO reference_reader;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reference_loader') THEN
        GRANT SELECT, INSERT ON {TABLES} TO reference_loader;
        GRANT SELECT ON reference.country_currency_integrity_violation TO reference_loader;
        GRANT UPDATE (minor_units, fund_code, status, replacement_currency_ids,
                      last_changed_snapshot_version)
            ON reference.currency TO reference_loader;
        GRANT UPDATE (name) ON reference.currency_locale TO reference_loader;
        GRANT UPDATE (status, valid_from, valid_to, last_changed_snapshot_version)
            ON reference.country_currency TO reference_loader;
    END IF;
END
$$;
"""

# La extensión `btree_gist` no se elimina: otros objetos de la base pueden usarla.
DOWNGRADE = """
DROP VIEW reference.country_currency_integrity_violation;
DROP TABLE reference.country_currency;
DROP TABLE reference.currency_locale;
DROP TABLE reference.currency;
DROP TABLE reference.currency_snapshot;
DROP FUNCTION reference.check_currency_inactive_has_no_open_associations();
DROP FUNCTION reference.check_country_currency_open_targets_active();
DROP FUNCTION reference.check_currency_replacements_acyclic();
DROP FUNCTION reference.check_currency_replacements_exist();
DROP FUNCTION reference.check_country_currency_validity_history();
DROP FUNCTION reference.reject_currency_identity_change();
DROP FUNCTION reference.reject_currency_catalog_delete();
DROP FUNCTION reference.reject_currency_history_change();
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute(DOWNGRADE)
