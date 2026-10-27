# Operación

Runbook mínimo para desplegar y operar los catálogos de locales (spec 001) y de regiones y subregiones UN M49 (spec 002). Para el entorno de desarrollo y las verificaciones, ver [`desarrollo.md`](desarrollo.md).

Los bloques `sql` que empiezan con `-- runbook:<nombre>` los ejecuta `tests/integration/test_runbook.py` contra un Postgres real: lo que se documenta aquí es lo que se probó.

## Roles y variables de entorno

Cada proceso usa su propio rol y su propia variable. Ninguna URL se versiona ni se escribe en logs.

| Quién | Variable | Rol de base de datos | Privilegios |
|---|---|---|---|
| Migraciones (`alembic`) | `REFERENCE_MIGRATION_DATABASE_URL` | dueño del schema `reference` (administrador) | crear schema y tablas |
| API de lectura | `REFERENCE_READER_DATABASE_URL` | `reference_reader` | solo `SELECT` |
| CLI de incorporación | `REFERENCE_DATABASE_URL` | `reference_loader` | `INSERT` en snapshots y locales, `UPDATE` solo de `status`, `iana_deprecated` y `replacement_locale_id`, `INSERT`/`DELETE` en alias; en regiones y subregiones, `INSERT` y `UPDATE` solo de las columnas mutables (código, `status`, reemplazo, Region padre y nombre), nunca `DELETE` |

Formato de las URLs: `postgresql://usuario:contraseña@host:5432/base`. Ni `anon`, `authenticated` ni `public` reciben ningún privilegio sobre `reference`.

## 1. Crear los roles

Lo ejecuta un administrador de la base compartida, **antes** de migrar. Reemplazar las contraseñas por secretos reales (gestor de secretos, nunca el repositorio).

```sql
-- runbook:roles
CREATE ROLE reference_reader LOGIN PASSWORD 'CAMBIAR_READER';
CREATE ROLE reference_loader LOGIN PASSWORD 'CAMBIAR_LOADER';
```

## 2. Aplicar la migración

Desde la raíz del repositorio, con el rol dueño del schema:

```text
REFERENCE_MIGRATION_DATABASE_URL=postgresql://dueño:...@host/base alembic upgrade head
```

Si la conexión falla, el error muestra solo el tipo y, si el servidor lo informó, el SQLSTATE (`no se pudo conectar para migrar … : OperationalError`), nunca el texto del driver ni la URL; para diagnosticarla, reproducirla con `psql`. Los errores de las propias migraciones (SQL, constraints) sí se muestran completos.

La migración crea el schema `reference`, las tablas, los constraints y los triggers (incluida la protección contra `UPDATE`, `DELETE` y `TRUNCATE` del historial), y otorga los permisos a `reference_reader` y `reference_loader` **solo si esos roles existen en ese momento**.

`alembic upgrade head` aplica también la migración 0002 (regiones y subregiones: tablas, constraints diferidas, triggers de inmutabilidad y los mismos permisos condicionales).

### Si los roles se crearon después de migrar

Los permisos no se aplican retroactivamente. Ejecutar, con el rol dueño del schema:

```sql
-- runbook:grants
GRANT USAGE ON SCHEMA reference TO reference_reader;
GRANT SELECT ON reference.locale_snapshot, reference.locale, reference.locale_alias
    TO reference_reader;

GRANT USAGE ON SCHEMA reference TO reference_loader;
GRANT SELECT ON reference.locale_snapshot, reference.locale, reference.locale_alias
    TO reference_loader;
GRANT INSERT ON reference.locale_snapshot TO reference_loader;
GRANT INSERT ON reference.locale TO reference_loader;
GRANT UPDATE (status, iana_deprecated, replacement_locale_id) ON reference.locale
    TO reference_loader;
GRANT INSERT, DELETE ON reference.locale_alias TO reference_loader;

-- Regiones y subregiones (migración 0002).
GRANT SELECT ON reference.region_snapshot, reference.region, reference.subregion,
    reference.region_locale, reference.subregion_locale, reference.subregion_reclassification,
    reference.region_recoding, reference.subregion_recoding TO reference_reader;
GRANT SELECT, INSERT ON reference.region_snapshot, reference.region, reference.subregion,
    reference.region_locale, reference.subregion_locale, reference.subregion_reclassification,
    reference.region_recoding, reference.subregion_recoding TO reference_loader;
GRANT UPDATE (code, code_snapshot_version, status, replacement_region_id) ON reference.region
    TO reference_loader;
GRANT UPDATE (region_id, code, code_snapshot_version, status, replacement_subregion_id)
    ON reference.subregion TO reference_loader;
GRANT UPDATE (name) ON reference.region_locale, reference.subregion_locale TO reference_loader;
```

### Verificar los permisos

```sql
-- runbook:verify
SELECT
    has_table_privilege('reference_reader', 'reference.locale', 'SELECT') AS reader_select,
    has_table_privilege('reference_reader', 'reference.locale', 'INSERT') AS reader_insert,
    has_table_privilege('reference_loader', 'reference.locale', 'INSERT') AS loader_insert,
    has_table_privilege('reference_loader', 'reference.locale', 'DELETE') AS loader_delete,
    has_schema_privilege('public', 'reference', 'USAGE') AS public_usage;
```

Resultado esperado: `true, false, true, false, false`.

### Supabase

El schema `reference` **no** debe figurar en los schemas expuestos por PostgREST (Settings → API → Exposed schemas). Revisarlo en cada entorno: ningún test del repositorio lo puede comprobar.

### Rollback

Antes de que exista un consumidor: `REFERENCE_MIGRATION_DATABASE_URL=... alembic downgrade 0001` elimina solo las tablas y funciones de regiones y subregiones (migración 0002); `REFERENCE_MIGRATION_DATABASE_URL=... alembic downgrade base` elimina todas las tablas y funciones (el schema `reference` y su tabla `alembic_version` quedan). Con consumidores no hay rollback de datos: los snapshots son inmutables y se corrige hacia adelante con una `snapshot_version` nueva.

## 3. Arrancar la API

```text
REFERENCE_READER_DATABASE_URL=postgresql://reference_reader:...@host/base \
    uvicorn --factory gi_common_reference.app:app_from_environment --host 0.0.0.0 --port 8000
```

Sin `REFERENCE_READER_DATABASE_URL` el proceso no arranca; con una cadena de conexión mal formada tampoco, y el error no la reproduce. La API solo expone lecturas `GET`:

- Locale: `GET /v1/locales`, `GET /v1/locales/{locale_id}` y `GET /v1/locales/by-code/{code}`; contrato en `contracts/locales-api.v1.openapi.json` (servido en `/v1/openapi.json`).
- Regiones y subregiones: `GET /v1/regions`, `GET /v1/regions/{region_id}`, `GET /v1/regions/by-code/{code}`, `GET /v1/subregions`, `GET /v1/subregions/{subregion_id}` y `GET /v1/subregions/by-code/{code}`, todas con `locale_id` opcional para el nombre (sin fallback); contrato en `contracts/regions-api.v1.openapi.json` (servido en `/v1/openapi/regions.json`).

Un mismo proceso sirve ambas APIs con la misma URL de `reference_reader`.

Respuestas de error: `503` si la base no responde y `500` ante un fallo inesperado. Al cliente solo llega un mensaje genérico; la causa queda en el log del proceso (logger `gi_common_reference.locales.interfaces.http`, nivel `ERROR`). `uvicorn` solo configura sus propios loggers: si el proceso no configura logging, Python igual escribe estos errores por `stderr`, pero sin fecha ni formato; para un log estructurado hay que pasar `--log-config` a `uvicorn` o configurar `logging` en el despliegue. El 503 registra solo el tipo de error y su SQLSTATE; el 500, el traceback completo.

## 4. Incorporar un snapshot de locales

El snapshot lo produce PREP (`gi-common-reference-prep`) según `contracts/locale-snapshot.v1.schema.json`. Se incorpora con el rol `reference_loader`:

```text
REFERENCE_DATABASE_URL=postgresql://reference_loader:...@host/base \
    python -m gi_common_reference.locales.interfaces.cli incorporate ruta/al/snapshot.json
```

| Código de salida | Significado |
|---|---|
| 0 | `INCORPORADO` o `NO-OP` (el snapshot ya estaba incorporado) |
| 1 | `RECHAZADO`: el snapshot es inválido; se listan las violaciones y la base queda intacta |
| 2 | error operativo: variable ausente, archivo ilegible, instalación incompleta o falla de base de datos |

Cada incorporación es atómica: o se aplica completa o no cambia nada. Para los errores de base de datos la CLI imprime solo el tipo de error y, si el servidor lo informó, su SQLSTATE, nunca el texto del driver ni la cadena de conexión: un fallo de conexión o de autenticación se ve como `OperationalError` (sin SQLSTATE) y un error de una consulta como `UndefinedTable (SQLSTATE 42P01)`. Para diagnosticar una conexión, reproducirla con `psql` y la misma URL.

## 5. Incorporar un snapshot de regiones y subregiones

El snapshot lo produce PREP según `contracts/region-snapshot.v1.schema.json` (ejemplo en `contracts/region-snapshot.v1.example.json`). Requisitos: la migración 0002 aplicada y un snapshot de Locale ya incorporado que contenga, `active`, los locales obligatorios de `required-locales.v1.json` (`en` y `es`, por `locale_id`). Se incorpora con el rol `reference_loader`:

```text
REFERENCE_DATABASE_URL=postgresql://reference_loader:...@host/base     python -m gi_common_reference.regions.interfaces.cli incorporate ruta/al/regions.json
```

Los códigos de salida son los mismos de la sección 4 (0 `INCORPORADO` o `NO-OP`, 1 `RECHAZADO`, 2 error operativo). La incorporación es atómica, toma su propio lock y bloquea mientras tanto la incorporación de Locale, contra la que valida los nombres. Un snapshot que cambie la Region de una Subregion referenciada por otro catálogo con un par (`region_id`, `subregion_id`) que quedaría incoherente se rechaza como `RF-35` con el nombre de la constraint violada; ese cambio se incorpora en la misma transacción que el snapshot del catálogo dependiente.

## 6. Consultar la trazabilidad de regiones y subregiones

Cada snapshot incorporado conserva su artefacto, la versión de Locale contra la que se validaron sus nombres y la versión de la política de locales obligatorios:

```sql
-- runbook:regions_snapshots
SELECT snapshot_version, content_digest, locale_snapshot_version, required_locales_version,
    provenance, incorporated_at
FROM reference.region_snapshot ORDER BY snapshot_version;
```

Reclasificaciones (cambio de Region padre con el mismo id y código):

```sql
-- runbook:regions_reclassifications
SELECT subregion_id, previous_region_id, new_region_id, snapshot_version
FROM reference.subregion_reclassification ORDER BY snapshot_version, subregion_id;
```

Recodificaciones (mismo id, otro código vigente), con la referencia de provenance que las justifica:

```sql
-- runbook:regions_recodings
SELECT 'region' AS entity_type, region_id AS entity_id, previous_code, new_code,
    snapshot_version, provenance
FROM reference.region_recoding
UNION ALL
SELECT 'subregion', subregion_id, previous_code, new_code, snapshot_version, provenance
FROM reference.subregion_recoding
ORDER BY snapshot_version, entity_type, entity_id;
```

Estas tablas, como el resto del schema `reference`, no son un contrato para los consumidores: los módulos consumidores usan la API.
