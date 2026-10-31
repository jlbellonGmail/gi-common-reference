# Operación

Runbook mínimo para desplegar y operar los catálogos de locales (spec 001), de regiones y subregiones UN M49 (spec 002) y de países (spec 003). Para el entorno de desarrollo y las verificaciones, ver [`desarrollo.md`](desarrollo.md).

Los bloques `sql` que empiezan con `-- runbook:<nombre>` los ejecuta `tests/integration/test_runbook.py` contra un Postgres real: lo que se documenta aquí es lo que se probó.

## Roles y variables de entorno

Cada proceso usa su propio rol y su propia variable. Ninguna URL se versiona ni se escribe en logs.

| Quién | Variable | Rol de base de datos | Privilegios |
|---|---|---|---|
| Migraciones (`alembic`) | `REFERENCE_MIGRATION_DATABASE_URL` | dueño del schema `reference` (administrador) | crear schema y tablas |
| API de lectura | `REFERENCE_READER_DATABASE_URL` | `reference_reader` | solo `SELECT` |
| CLI de incorporación | `REFERENCE_DATABASE_URL` | `reference_loader` | `INSERT` en snapshots y locales, `UPDATE` solo de `status`, `iana_deprecated` y `replacement_locale_id`, `INSERT`/`DELETE` en alias; en regiones y subregiones, `INSERT` y `UPDATE` solo de las columnas mutables (código, `status`, reemplazo, Region padre y nombre), nunca `DELETE`; en países, `INSERT` y `UPDATE` solo de las columnas mutables (códigos, clasificación, `calling_code`, `status`, reemplazo, versiones, nombres y bandera), nunca `DELETE` |

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

`alembic upgrade head` aplica también la migración 0002 (regiones y subregiones: tablas, constraints diferidas, triggers de inmutabilidad y los mismos permisos condicionales) y la migración 0003 (países: tablas `country_snapshot`, `country`, `country_locale`, `country_flag` y `country_recoding`, unicidad entre `active` diferida, FK compuesta hacia la Subregion de 002, trigger que exige la traza de recodificación y los mismos permisos condicionales).

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

-- Países (migración 0003).
GRANT SELECT ON reference.country_snapshot, reference.country, reference.country_locale,
    reference.country_flag, reference.country_recoding TO reference_reader;
GRANT SELECT, INSERT ON reference.country_snapshot, reference.country, reference.country_locale,
    reference.country_flag, reference.country_recoding TO reference_loader;
GRANT UPDATE (alpha2, alpha3, numeric_code, codes_snapshot_version, region_id, subregion_id,
    calling_code, status, replacement_country_id, last_changed_snapshot_version)
    ON reference.country TO reference_loader;
GRANT UPDATE (name, official_name) ON reference.country_locale TO reference_loader;
GRANT UPDATE (asset_path, sha256, exception_reason, snapshot_version)
    ON reference.country_flag TO reference_loader;
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

Antes de que exista un consumidor: `REFERENCE_MIGRATION_DATABASE_URL=... alembic downgrade 0002` elimina solo las tablas y funciones de países (migración 0003); `alembic downgrade 0001` elimina además las de regiones y subregiones (migración 0002); `REFERENCE_MIGRATION_DATABASE_URL=... alembic downgrade base` elimina todas las tablas y funciones (el schema `reference` y su tabla `alembic_version` quedan). Con consumidores no hay rollback de datos: los snapshots son inmutables y se corrige hacia adelante con una `snapshot_version` nueva.

## 3. Arrancar la API

```text
REFERENCE_READER_DATABASE_URL=postgresql://reference_reader:...@host/base \
    uvicorn --factory gi_common_reference.app:app_from_environment --host 0.0.0.0 --port 8000
```

Sin `REFERENCE_READER_DATABASE_URL` el proceso no arranca; con una cadena de conexión mal formada tampoco, y el error no la reproduce. La API solo expone lecturas `GET`:

- Locale: `GET /v1/locales`, `GET /v1/locales/{locale_id}` y `GET /v1/locales/by-code/{code}`; contrato en `contracts/locales-api.v1.openapi.json` (servido en `/v1/openapi.json`).
- Regiones y subregiones: `GET /v1/regions`, `GET /v1/regions/{region_id}`, `GET /v1/regions/by-code/{code}`, `GET /v1/subregions`, `GET /v1/subregions/{subregion_id}` y `GET /v1/subregions/by-code/{code}`, todas con `locale_id` opcional para el nombre (sin fallback); contrato en `contracts/regions-api.v1.openapi.json` (servido en `/v1/openapi/regions.json`).

- Países: `GET /v1/countries` (por defecto solo `active`; `status=all` incluye `inactive`; filtros `region_id` y `subregion_id`), `GET /v1/countries/{country_id}`, `GET /v1/countries/by-alpha2/{code}`, `GET /v1/countries/by-alpha3/{code}`, `GET /v1/countries/by-numeric/{code}` y `GET /v1/countries/{country_id}/flag` (SVG, `image/svg+xml`); `locale_id` opcional para `name` y `official_name` (sin fallback); contrato en `contracts/countries-api.v1.openapi.json` (servido en `/v1/openapi/countries.json`). Los consumidores persisten `country_id`; los códigos son claves de resolución.

Un mismo proceso sirve las tres APIs con la misma URL de `reference_reader`.

Respuestas de error: `503` si la base no responde y `500` ante un fallo inesperado. Al cliente solo llega un mensaje genérico; la causa queda en el log del proceso (loggers `gi_common_reference.locales.interfaces.http`, `gi_common_reference.regions.interfaces.http` y `gi_common_reference.countries.interfaces.http`, nivel `ERROR`). `uvicorn` solo configura sus propios loggers: si el proceso no configura logging, Python igual escribe estos errores por `stderr`, pero sin fecha ni formato; para un log estructurado hay que pasar `--log-config` a `uvicorn` o configurar `logging` en el despliegue. El 503 registra solo el tipo de error y su SQLSTATE; el 500, el traceback completo.

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

## 7. Incorporar un snapshot de países

El snapshot lo produce PREP según `contracts/country-snapshot.v1.schema.json` (ejemplo sintético y **no productivo** en `contracts/country-snapshot.v1.example.json`). Requisitos:

- la migración 0003 aplicada;
- un snapshot de Locale ya incorporado que contenga, `active`, los locales obligatorios de Countries (`required-locales.v1.json` del paquete: `en` y `es`, por `locale_id`);
- un snapshot de Regions incorporado, igual o posterior a la versión que el snapshot de países declara en `region_snapshot_version`;
- el asset SVG de cada bandera que el snapshot referencia, ya presente en el paquete desplegado (ver "Banderas").

Se incorpora con el rol `reference_loader`:

```text
REFERENCE_DATABASE_URL=postgresql://reference_loader:...@host/base \
    python -m gi_common_reference.countries.interfaces.cli incorporate ruta/al/countries.json
```

Antes de aprobar un snapshot se revisa qué cambiaría respecto del catálogo aplicado. Solo lee: no escribe ni toma el lock exclusivo, y no verifica los assets de bandera (eso ocurre al incorporar):

```text
REFERENCE_DATABASE_URL=postgresql://reference_loader:...@host/base \
    python -m gi_common_reference.countries.interfaces.cli diff ruta/al/countries.json
```

Lista altas, cambios de códigos, de clasificación, de atributos, de estado, de nombres y de bandera; si el snapshot sería rechazado, lista las violaciones.

Los códigos de salida son los de la sección 4 (0 `INCORPORADO`, `NO-OP` o diff calculado; 1 `RECHAZADO`; 2 error operativo). La incorporación es atómica y toma su propio lock exclusivo más locks compartidos sobre los de Locale y Regions: mientras dura, ninguno de los dos cambia el catálogo contra el que se valida. Reglas que conviene conocer:

- El snapshot es el catálogo completo: omitir un país, un nombre o una bandera publicados se rechaza; un retiro es `status = inactive`.
- Los códigos `alpha2`, `alpha3` y `numeric_code` forman una tripleta: solo cambian con una recodificación declarada (con referencia de provenance), que conserva el `country_id`. Reutilizar un código vigente o histórico de otro país exige declarar la reasignación.
- Una versión de Regions o una clasificación `inactive` en un país `active` se rechaza (`RF-48`). Una reclasificación de Regions que deje incoherente a un país la rechaza Regions (`RF-35` de 002): hasta que exista un procedimiento de incorporación conjunta, esa reclasificación queda bloqueada.
- Una constraint de la base violada al final de la transacción es un rechazo (salida 1) con el nombre de la constraint, no un error operativo.

### Banderas

Las banderas son archivos SVG del repositorio, en `src/gi_common_reference/countries/assets/flags/` (viajan dentro del paquete instalado como package-data). El snapshot las referencia por `asset_path` relativo, `sha256` de los bytes exactos del archivo (por eso los `.svg` se versionan sin conversión de fin de línea) y `media_type` `image/svg+xml`; un país `active` sin bandera declara una excepción con motivo. Al incorporar se verifica que cada asset exista, que la suma coincida y que el SVG esté bien formado y sin partes activas (sin DTD ni entidades, `script`, `foreignObject`, elementos embebidos, manejadores `on*` ni referencias que no sean `#id`; hasta 512 KiB). Al servirlo (`GET /v1/countries/{country_id}/flag`) se vuelve a verificar la suma y se devuelve con `ETag` igual a ella. Para agregar o cambiar una bandera: agregar el archivo al directorio, desplegar el paquete y recién entonces incorporar el snapshot que lo referencia. Hasta que PREP aporte el dataset real el directorio solo contiene su `README.md`.

## 8. Consultar la trazabilidad de países

Cada snapshot incorporado conserva su artefacto, la versión de Locale contra la que se validaron los nombres, la versión de Regions que declaró y la vigente al incorporarlo, y la versión de la política de locales obligatorios:

```sql
-- runbook:countries_snapshots
SELECT snapshot_version, content_digest, locale_snapshot_version, region_snapshot_version,
    region_current_snapshot_version, required_locales_version, provenance, incorporated_at
FROM reference.country_snapshot ORDER BY snapshot_version;
```

Recodificaciones (mismo `country_id`, otra tripleta ISO), con la referencia de provenance que las justifica:

```sql
-- runbook:countries_recodings
SELECT country_id, snapshot_version, previous_alpha2, previous_alpha3, previous_numeric_code,
    new_alpha2, new_alpha3, new_numeric_code, provenance
FROM reference.country_recoding ORDER BY snapshot_version, country_id;
```

Versiones por país: el snapshot que lo introdujo, el que le dio sus códigos vigentes y el último que cambió su contenido (códigos, clasificación, estado, nombres o bandera):

```sql
-- runbook:countries_versions
SELECT country_id, alpha2, status, first_snapshot_version, codes_snapshot_version,
    last_changed_snapshot_version
FROM reference.country ORDER BY alpha2, country_id;
```

Estas tablas, como el resto del schema `reference`, no son un contrato para los consumidores: los módulos consumidores usan la API y persisten `country_id`.
