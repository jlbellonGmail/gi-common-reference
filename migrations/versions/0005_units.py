"""Catálogo global de unidades de medida y magnitudes (spec 005, plan "Datos").

Revision ID: 0005
Revises: 0004

Magnitudes (`quantity_kind`), unidades (`unit`) y su asociación con factor y desplazamiento
(`quantity_kind_unit`), más las localizaciones y la historia de snapshots. Factores y
desplazamientos son texto en forma canónica (D3): `numeric` no representa 5/9 y `float` es inexacto.
Depende solo de `reference.locale` y `reference.locale_snapshot` (RNF-5).
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TABLES = (
    "reference.unit_snapshot, reference.quantity_kind, reference.unit, "
    "reference.quantity_kind_unit, reference.quantity_kind_locale, reference.unit_locale"
)

UPGRADE = r"""
-- D3: decimal canónico sin signo `+`, sin ceros a la izquierda ni a la derecha del punto, sin `-0`.
CREATE FUNCTION reference.uom_is_canonical_decimal(value text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT value IS NOT NULL
       AND value ~ '^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$'
       AND value <> '-0'
$$;

-- D3: factor positivo, decimal canónico o fracción `p/q` irreducible cuya expansión decimal no
-- termina (si termina, debe escribirse como decimal): `q > 1` y con algún primo distinto de 2 y 5.
CREATE FUNCTION reference.uom_is_canonical_factor(value text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    numerator numeric;
    denominator numeric;
    rest numeric;
BEGIN
    IF value IS NULL THEN
        RETURN false;
    END IF;
    IF value ~ '^[1-9][0-9]*/[1-9][0-9]*$' THEN
        numerator := split_part(value, '/', 1)::numeric;
        denominator := split_part(value, '/', 2)::numeric;
        IF denominator <= 1 OR gcd(numerator, denominator) <> 1 THEN
            RETURN false;
        END IF;
        rest := denominator;
        WHILE mod(rest, 2) = 0 LOOP
            rest := div(rest, 2);
        END LOOP;
        WHILE mod(rest, 5) = 0 LOOP
            rest := div(rest, 5);
        END LOOP;
        RETURN rest <> 1;
    END IF;
    RETURN reference.uom_is_canonical_decimal(value) AND value !~ '^-' AND value <> '0';
END
$$;

CREATE TABLE reference.unit_snapshot (
    snapshot_version bigint NOT NULL,
    content_digest text NOT NULL,
    locale_snapshot_version bigint NOT NULL,
    required_locales_version integer NOT NULL,
    ucum_table_version text NOT NULL,
    provenance jsonb NOT NULL,
    artifact jsonb NOT NULL,
    incorporated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT unit_snapshot_pkey PRIMARY KEY (snapshot_version),
    CONSTRAINT unit_snapshot_version_positive CHECK (snapshot_version > 0),
    CONSTRAINT unit_snapshot_required_locales_version_positive
        CHECK (required_locales_version > 0),
    CONSTRAINT unit_snapshot_ucum_table_version_present CHECK (ucum_table_version <> ''),
    CONSTRAINT unit_snapshot_locale_snapshot_fk FOREIGN KEY (locale_snapshot_version)
        REFERENCES reference.locale_snapshot (snapshot_version)
);

-- `reference_unit_id` es la unidad de referencia; su FK compuesta (diferida) exige que exista la
-- asociación (magnitud, unidad) y, por la clave primaria de la asociación, que sea única (D5).
CREATE TABLE reference.quantity_kind (
    quantity_kind_id uuid NOT NULL,
    code text NOT NULL,
    conversion_type text NOT NULL,
    reference_unit_id uuid NOT NULL,
    status text NOT NULL,
    first_snapshot_version bigint NOT NULL,
    last_changed_snapshot_version bigint NOT NULL,
    CONSTRAINT quantity_kind_pkey PRIMARY KEY (quantity_kind_id),
    CONSTRAINT quantity_kind_code_format CHECK (code ~ '^[a-z][a-z0-9_]{1,63}$'),
    -- D-14: el código queda ligado a una única magnitud, incluidas las `inactive`.
    CONSTRAINT quantity_kind_code_unique UNIQUE (code),
    CONSTRAINT quantity_kind_conversion_type_valid CHECK (conversion_type IN ('linear', 'affine')),
    CONSTRAINT quantity_kind_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT quantity_kind_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.unit_snapshot (snapshot_version),
    CONSTRAINT quantity_kind_last_changed_snapshot_fk FOREIGN KEY (last_changed_snapshot_version)
        REFERENCES reference.unit_snapshot (snapshot_version)
);

-- Sin ningún texto dependiente del idioma: nombres en `unit_locale`. El símbolo es un texto
-- neutral (kg, m², °C), no una traducción.
CREATE TABLE reference.unit (
    unit_id uuid NOT NULL,
    ucum_code text,
    unece_code text,
    symbol text NOT NULL,
    status text NOT NULL,
    first_snapshot_version bigint NOT NULL,
    last_changed_snapshot_version bigint NOT NULL,
    CONSTRAINT unit_pkey PRIMARY KEY (unit_id),
    CONSTRAINT unit_ucum_code_format CHECK (ucum_code IS NULL OR ucum_code ~ '^\S+$'),
    CONSTRAINT unit_unece_code_format CHECK (unece_code IS NULL OR unece_code ~ '^[A-Z0-9]{2,3}$'),
    CONSTRAINT unit_symbol_trimmed CHECK (symbol <> '' AND symbol !~ '^\s' AND symbol !~ '\s$'),
    CONSTRAINT unit_status_valid CHECK (status IN ('active', 'inactive')),
    -- D-14, RF-3, RF-4: los códigos quedan ligados a una única unidad, incluidas las `inactive`.
    CONSTRAINT unit_ucum_code_unique UNIQUE (ucum_code),
    CONSTRAINT unit_unece_code_unique UNIQUE (unece_code),
    CONSTRAINT unit_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.unit_snapshot (snapshot_version),
    CONSTRAINT unit_last_changed_snapshot_fk FOREIGN KEY (last_changed_snapshot_version)
        REFERENCES reference.unit_snapshot (snapshot_version)
);

-- ref = (valor + desplazamiento) * factor (RF-11).
CREATE TABLE reference.quantity_kind_unit (
    quantity_kind_id uuid NOT NULL,
    unit_id uuid NOT NULL,
    factor text NOT NULL,
    "offset" text NOT NULL,
    status text NOT NULL,
    first_snapshot_version bigint NOT NULL,
    last_changed_snapshot_version bigint NOT NULL,
    CONSTRAINT quantity_kind_unit_pkey PRIMARY KEY (quantity_kind_id, unit_id),
    CONSTRAINT quantity_kind_unit_factor_canonical
        CHECK (reference.uom_is_canonical_factor(factor)),
    CONSTRAINT quantity_kind_unit_offset_canonical
        CHECK (reference.uom_is_canonical_decimal("offset")),
    CONSTRAINT quantity_kind_unit_status_valid CHECK (status IN ('active', 'inactive')),
    CONSTRAINT quantity_kind_unit_quantity_kind_fk FOREIGN KEY (quantity_kind_id)
        REFERENCES reference.quantity_kind (quantity_kind_id),
    CONSTRAINT quantity_kind_unit_unit_fk FOREIGN KEY (unit_id)
        REFERENCES reference.unit (unit_id),
    CONSTRAINT quantity_kind_unit_first_snapshot_fk FOREIGN KEY (first_snapshot_version)
        REFERENCES reference.unit_snapshot (snapshot_version),
    CONSTRAINT quantity_kind_unit_last_changed_snapshot_fk
        FOREIGN KEY (last_changed_snapshot_version)
        REFERENCES reference.unit_snapshot (snapshot_version)
);

CREATE INDEX quantity_kind_unit_unit_idx ON reference.quantity_kind_unit (unit_id);

-- D5: la unidad de referencia es una asociación de la propia magnitud. Diferida: la magnitud y su
-- asociación de referencia se crean en la misma transacción.
ALTER TABLE reference.quantity_kind
    ADD CONSTRAINT quantity_kind_reference_fk FOREIGN KEY (quantity_kind_id, reference_unit_id)
        REFERENCES reference.quantity_kind_unit (quantity_kind_id, unit_id)
        DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE reference.quantity_kind_locale (
    quantity_kind_id uuid NOT NULL,
    locale_id uuid NOT NULL,
    name text NOT NULL,
    CONSTRAINT quantity_kind_locale_pkey PRIMARY KEY (quantity_kind_id, locale_id),
    CONSTRAINT quantity_kind_locale_name_trimmed
        CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$'),
    CONSTRAINT quantity_kind_locale_quantity_kind_fk FOREIGN KEY (quantity_kind_id)
        REFERENCES reference.quantity_kind (quantity_kind_id),
    CONSTRAINT quantity_kind_locale_locale_fk FOREIGN KEY (locale_id)
        REFERENCES reference.locale (locale_id)
);

CREATE TABLE reference.unit_locale (
    unit_id uuid NOT NULL,
    locale_id uuid NOT NULL,
    name text NOT NULL,
    plural text,
    CONSTRAINT unit_locale_pkey PRIMARY KEY (unit_id, locale_id),
    CONSTRAINT unit_locale_name_trimmed CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$'),
    CONSTRAINT unit_locale_plural_trimmed
        CHECK (plural IS NULL OR (plural <> '' AND plural !~ '^\s' AND plural !~ '\s$')),
    CONSTRAINT unit_locale_unit_fk FOREIGN KEY (unit_id) REFERENCES reference.unit (unit_id),
    CONSTRAINT unit_locale_locale_fk FOREIGN KEY (locale_id)
        REFERENCES reference.locale (locale_id)
);

-- Historia: inmutable (RNF-2).
CREATE FUNCTION reference.uom_reject_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reference.% is immutable', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Magnitudes, unidades, asociaciones y localizaciones publicadas nunca se borran (RF-7).
CREATE FUNCTION reference.uom_reject_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'published rows of reference.% are never deleted', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$;

-- Las columnas de identidad que recibe como argumentos no cambian una vez publicadas (RF-2).
CREATE FUNCTION reference.uom_reject_identity_change() RETURNS trigger
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

-- RF-5: un código ausente puede completarse una vez; ya fijado, es inmutable (ni se vacía).
CREATE FUNCTION reference.uom_check_unit_codes_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.ucum_code IS NOT NULL AND NEW.ucum_code IS DISTINCT FROM OLD.ucum_code THEN
        RAISE EXCEPTION 'reference.unit.ucum_code is immutable once set'
            USING ERRCODE = 'restrict_violation', CONSTRAINT = 'unit_ucum_code_immutable';
    END IF;
    IF OLD.unece_code IS NOT NULL AND NEW.unece_code IS DISTINCT FROM OLD.unece_code THEN
        RAISE EXCEPTION 'reference.unit.unece_code is immutable once set'
            USING ERRCODE = 'restrict_violation', CONSTRAINT = 'unit_unece_code_immutable';
    END IF;
    RETURN NEW;
END
$$;

-- RF-12, D4: una asociación de una magnitud `linear` no tiene desplazamiento. `conversion_type` es
-- inmutable, así que basta con evaluarlo al escribir la asociación.
CREATE FUNCTION reference.uom_check_linear_offset() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW."offset" <> '0' AND EXISTS (
        SELECT 1 FROM reference.quantity_kind k
        WHERE k.quantity_kind_id = NEW.quantity_kind_id AND k.conversion_type = 'linear'
    ) THEN
        RAISE EXCEPTION 'a linear quantity kind admits only offset 0'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'quantity_kind_unit_linear_offset';
    END IF;
    RETURN NEW;
END
$$;

-- RF-8, D5: la asociación de referencia tiene factor 1 y desplazamiento 0; una magnitud `active`
-- tiene activas su asociación de referencia y su unidad de referencia. Si la asociación de
-- referencia no existe, lo informa la FK diferida `quantity_kind_reference_fk`.
CREATE FUNCTION reference.uom_assert_kind(kind_id uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    kind reference.quantity_kind;
    link reference.quantity_kind_unit;
    unit_status text;
BEGIN
    SELECT * INTO kind FROM reference.quantity_kind WHERE quantity_kind_id = kind_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT * INTO link FROM reference.quantity_kind_unit
    WHERE quantity_kind_id = kind.quantity_kind_id AND unit_id = kind.reference_unit_id;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF link.factor <> '1' OR link."offset" <> '0' THEN
        RAISE EXCEPTION 'the reference association of a quantity kind has factor 1 and offset 0'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'quantity_kind_reference_neutral';
    END IF;
    SELECT status INTO unit_status FROM reference.unit WHERE unit_id = kind.reference_unit_id;
    IF kind.status = 'active' AND (link.status <> 'active' OR unit_status <> 'active') THEN
        RAISE EXCEPTION 'an active quantity kind needs an active reference association and unit'
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'quantity_kind_active_requires_active_reference';
    END IF;
END
$$;

CREATE FUNCTION reference.uom_check_kind() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    affected uuid;
BEGIN
    IF TG_TABLE_NAME = 'unit' THEN
        FOR affected IN
            SELECT quantity_kind_id FROM reference.quantity_kind
            WHERE reference_unit_id = NEW.unit_id
        LOOP
            PERFORM reference.uom_assert_kind(affected);
        END LOOP;
    ELSE
        PERFORM reference.uom_assert_kind(NEW.quantity_kind_id);
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER unit_snapshot_immutable
    BEFORE UPDATE OR DELETE ON reference.unit_snapshot
    FOR EACH ROW EXECUTE FUNCTION reference.uom_reject_history_change();
CREATE TRIGGER unit_snapshot_no_truncate
    BEFORE TRUNCATE ON reference.unit_snapshot
    FOR EACH STATEMENT EXECUTE FUNCTION reference.uom_reject_history_change();

CREATE TRIGGER quantity_kind_no_delete
    BEFORE DELETE ON reference.quantity_kind
    FOR EACH ROW EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER quantity_kind_no_truncate
    BEFORE TRUNCATE ON reference.quantity_kind
    FOR EACH STATEMENT EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER quantity_kind_identity_immutable
    BEFORE UPDATE ON reference.quantity_kind
    FOR EACH ROW EXECUTE FUNCTION
        reference.uom_reject_identity_change(
            'quantity_kind_id', 'code', 'conversion_type', 'reference_unit_id',
            'first_snapshot_version');
CREATE CONSTRAINT TRIGGER uom_check_kind
    AFTER INSERT OR UPDATE ON reference.quantity_kind
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.uom_check_kind();

CREATE TRIGGER unit_no_delete
    BEFORE DELETE ON reference.unit
    FOR EACH ROW EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER unit_no_truncate
    BEFORE TRUNCATE ON reference.unit
    FOR EACH STATEMENT EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER unit_identity_immutable
    BEFORE UPDATE ON reference.unit
    FOR EACH ROW EXECUTE FUNCTION
        reference.uom_reject_identity_change('unit_id', 'first_snapshot_version');
CREATE TRIGGER unit_codes_history
    BEFORE UPDATE ON reference.unit
    FOR EACH ROW EXECUTE FUNCTION reference.uom_check_unit_codes_history();
CREATE CONSTRAINT TRIGGER uom_check_kind
    AFTER UPDATE OF status ON reference.unit
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.uom_check_kind();

CREATE TRIGGER quantity_kind_unit_no_delete
    BEFORE DELETE ON reference.quantity_kind_unit
    FOR EACH ROW EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER quantity_kind_unit_no_truncate
    BEFORE TRUNCATE ON reference.quantity_kind_unit
    FOR EACH STATEMENT EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER quantity_kind_unit_identity_immutable
    BEFORE UPDATE ON reference.quantity_kind_unit
    FOR EACH ROW EXECUTE FUNCTION
        reference.uom_reject_identity_change(
            'quantity_kind_id', 'unit_id', 'first_snapshot_version');
CREATE TRIGGER uom_linear_offset
    BEFORE INSERT OR UPDATE ON reference.quantity_kind_unit
    FOR EACH ROW EXECUTE FUNCTION reference.uom_check_linear_offset();
CREATE CONSTRAINT TRIGGER uom_check_kind
    AFTER INSERT OR UPDATE ON reference.quantity_kind_unit
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION reference.uom_check_kind();

CREATE TRIGGER quantity_kind_locale_no_delete
    BEFORE DELETE ON reference.quantity_kind_locale
    FOR EACH ROW EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER quantity_kind_locale_no_truncate
    BEFORE TRUNCATE ON reference.quantity_kind_locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER quantity_kind_locale_identity_immutable
    BEFORE UPDATE ON reference.quantity_kind_locale
    FOR EACH ROW EXECUTE FUNCTION
        reference.uom_reject_identity_change('quantity_kind_id', 'locale_id');

CREATE TRIGGER unit_locale_no_delete
    BEFORE DELETE ON reference.unit_locale
    FOR EACH ROW EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER unit_locale_no_truncate
    BEFORE TRUNCATE ON reference.unit_locale
    FOR EACH STATEMENT EXECUTE FUNCTION reference.uom_reject_delete();
CREATE TRIGGER unit_locale_identity_immutable
    BEFORE UPDATE ON reference.unit_locale
    FOR EACH ROW EXECUTE FUNCTION
        reference.uom_reject_identity_change('unit_id', 'locale_id');
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
        GRANT UPDATE (status, last_changed_snapshot_version)
            ON reference.quantity_kind TO reference_loader;
        GRANT UPDATE (ucum_code, unece_code, symbol, status, last_changed_snapshot_version)
            ON reference.unit TO reference_loader;
        GRANT UPDATE (factor, "offset", status, last_changed_snapshot_version)
            ON reference.quantity_kind_unit TO reference_loader;
        GRANT UPDATE (name) ON reference.quantity_kind_locale TO reference_loader;
        GRANT UPDATE (name, plural) ON reference.unit_locale TO reference_loader;
    END IF;
END
$$;
"""

# La FK compuesta de referencia cierra un ciclo entre magnitud y asociación: se suelta primero.
DOWNGRADE = """
ALTER TABLE reference.quantity_kind DROP CONSTRAINT quantity_kind_reference_fk;
DROP TABLE reference.unit_locale;
DROP TABLE reference.quantity_kind_locale;
DROP TABLE reference.quantity_kind_unit;
DROP TABLE reference.unit;
DROP TABLE reference.quantity_kind;
DROP TABLE reference.unit_snapshot;
DROP FUNCTION reference.uom_check_kind();
DROP FUNCTION reference.uom_assert_kind(uuid);
DROP FUNCTION reference.uom_check_linear_offset();
DROP FUNCTION reference.uom_check_unit_codes_history();
DROP FUNCTION reference.uom_reject_identity_change();
DROP FUNCTION reference.uom_reject_delete();
DROP FUNCTION reference.uom_reject_history_change();
DROP FUNCTION reference.uom_is_canonical_factor(text);
DROP FUNCTION reference.uom_is_canonical_decimal(text);
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute(DOWNGRADE)
