# Operación

Runbook mínimo para desplegar y operar el catálogo de locales (spec 001). Para el entorno de desarrollo y las verificaciones, ver [`desarrollo.md`](desarrollo.md).

Los bloques `sql` que empiezan con `-- runbook:<nombre>` los ejecuta `tests/integration/test_runbook.py` contra un Postgres real: lo que se documenta aquí es lo que se probó.

## Roles y variables de entorno

Cada proceso usa su propio rol y su propia variable. Ninguna URL se versiona ni se escribe en logs.

| Quién | Variable | Rol de base de datos | Privilegios |
|---|---|---|---|
| Migraciones (`alembic`) | `REFERENCE_MIGRATION_DATABASE_URL` | dueño del schema `reference` (administrador) | crear schema y tablas |
| API de lectura | `REFERENCE_READER_DATABASE_URL` | `reference_reader` | solo `SELECT` |
| CLI de incorporación | `REFERENCE_DATABASE_URL` | `reference_loader` | `INSERT` en snapshots y locales, `UPDATE` solo de `status`, `iana_deprecated` y `replacement_locale_id`, `INSERT`/`DELETE` en alias |

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

Antes de que exista un consumidor: `REFERENCE_MIGRATION_DATABASE_URL=... alembic downgrade base` elimina las tablas y funciones (el schema `reference` y su tabla `alembic_version` quedan). Con consumidores no hay rollback de datos: los snapshots son inmutables y se corrige hacia adelante con una `snapshot_version` nueva.

## 3. Arrancar la API

```text
REFERENCE_READER_DATABASE_URL=postgresql://reference_reader:...@host/base \
    uvicorn --factory gi_common_reference.app:app_from_environment --host 0.0.0.0 --port 8000
```

Sin `REFERENCE_READER_DATABASE_URL` el proceso no arranca; con una cadena de conexión mal formada tampoco, y el error no la reproduce. La API solo expone `GET /v1/locales`, `GET /v1/locales/{locale_id}` y `GET /v1/locales/by-code/{code}`; el contrato está en `contracts/locales-api.v1.openapi.json`.

Respuestas de error: `503` si la base no responde y `500` ante un fallo inesperado. Al cliente solo llega un mensaje genérico; la causa queda en el log del proceso (logger `gi_common_reference.locales.interfaces.http`, nivel `ERROR`). `uvicorn` solo configura sus propios loggers: si el proceso no configura logging, Python igual escribe estos errores por `stderr`, pero sin fecha ni formato; para un log estructurado hay que pasar `--log-config` a `uvicorn` o configurar `logging` en el despliegue. El 503 registra solo el tipo de error y su SQLSTATE; el 500, el traceback completo.

## 4. Incorporar un snapshot

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
