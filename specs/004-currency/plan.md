# Plan 004 — Currency

- **Estado:** approved (2026-11-01, derivado de la spec cerrada en clarify 4; mismo alcance, sin requisitos nuevos)
- **Spec:** [spec.md](spec.md)
- **Perfil:** `python-service`; sigue la estructura de [001-locales](../001-locales/plan.md), [002-regions-subregions](../002-regions-subregions/plan.md) y [003-countries](../003-countries/plan.md)

## Precondición (verificada 2026-11-01, PASS)

`feature/004-currency` incorpora `develop` (`eadad94`, merge `2f9b187`) con 001, 002 y 003 aprobadas e implementadas, y la plataforma AI-NATIVE v3.4.3 (CLI v3.4.3, lock v3.4.3, `ai-native init` READY). Lo que 004 toma de ahí, sin cambiarlo:

- `locale_id` UUID estable (`reference.locale`, sin `DELETE`), `status` = `active` | `inactive`, RF-23–RF-25 de 001; `reference.locale_snapshot`.
- `country_id` UUID estable (`reference.country`, sin `DELETE`, `status`), `reference.country_snapshot`; **sin ninguna FK ni referencia de 003 hacia Currency** (RNF-7 de 003).
- Snapshots: `snapshot_version` entera positiva con saltos, digest SHA-256 del JSON canónico sin `content_digest`, clasificación A/B/C/D, incorporación atómica con locks, historial inmutable (D5, D7, D9, D12, D13 de 001/002; D15 de 003).
- La función SQL `reference.is_strictly_ascending(uuid[])` de la migración `0003` (solo se invoca; no se modifica).
- `architecture.json`, pruebas de frontera, `bootstrap.py` y `app.py` ya generalizados a tres módulos.

Ningún archivo de 001, 002 ni 003 se modifica funcionalmente (CA-24). Los únicos archivos compartidos que se extienden son la composición (`architecture.json`, `bootstrap.py`, `app.py`, `pyproject.toml` y las pruebas de frontera que enumeran módulos); se declaran en T1 y T8 y se verifican con el diff de las rutas propias de 001–003 (CA-24).

## Arquitectura y estrategia

Un módulo nuevo `currencies`, hexagonal como `locales`, `regions` y `countries` (RNF-6):

```text
currencies/interfaces (HTTP read-only, CLI de incorporación, diff y check-integrity)
  → currencies/application (consultas, incorporación, diff)
     → currencies/domain (modelo, códigos, temporalidad, digest, admisión, validación, puertos)
        ← currencies/infrastructure (Postgres, lector de snapshot, política de locales, reloj)
```

- Toda la validación de un snapshot es una función **pura** del dominio: `(snapshot, estado vigente, vista de Locale, vista de Countries, política) → plan de cambios | violaciones`. La base repite las invariantes estructurales como constraints y triggers (RNF-5).
- La temporalidad vive en un módulo puro `domain/temporal.py` (intervalos semiabiertos, solapamiento, contención, reglas de inmutabilidad de períodos). El SQL y el dominio implementan la misma semántica y una prueba cruzada los compara con los mismos vectores.
- `currencies` no importa código de `locales`, `regions` ni `countries` (ni al revés): depende de ellos solo por datos, con FK hacia `reference.locale` y `reference.country`, y lectura SQL de `reference.locale`, `reference.locale_snapshot`, `reference.country` y `reference.country_snapshot` en el mismo schema. Sin FK, trigger ni vista desde esas tablas hacia Currency (S-8, D-16).
- `bootstrap.py` sigue siendo la única raíz de composición; `app.py` despacha por prefijo a cuatro aplicaciones FastAPI sin cambiar los contratos de las otras tres.

## Decisiones

| # | Decisión | Alternativa descartada y motivo | Cubre |
|---|---|---|---|
| D1 | `currency_id` y la identidad de cada asociación (`country_currency_id`) son UUID que viajan en el snapshot; el sistema los valida y registra, nunca los genera ni los modifica | UUIDv5 derivado del código: la identidad dependería de un código (RF-2). Clave natural `(country, currency, inicio)` para la asociación: el inicio puede ser ausente y una corrección (RF-47) necesita dos registros distintos para el mismo período | RF-2, RF-17, RF-36, D-5, RF-47 |
| D2 | Snapshot = un único documento JSON, catálogo completo (no delta): `currencies`, `currency_names`, `country_currencies`, `country_snapshot_version` y `provenance`. Mismas reglas de digest que 001 y 003 | Un archivo por entidad: identidad atómica más difícil. Delta: no detecta omisiones (RF-37) | RF-37, RF-39, RF-41, D-2 |
| D3 | Todos los campos opcionales viajan como clave presente con `null`; códigos y fechas son siempre `string` en el schema (`^[A-Z]{3}$`, `^[0-9]{3}$`, `YYYY-MM-DD`). El lector rechaza claves duplicadas, floats y tipos no string en códigos y fechas; sin coerción numérica | Omitir claves opcionales: no distingue ausente de olvidado. Aceptar entero en `numeric_code`: perdería los ceros (`008`) | RF-4, CL-3, CL-23 |
| D4 | Códigos como texto con CHECK de formato. Alfabético: `UNIQUE` en todo el catálogo, incluidas las `inactive` (D-15). Numérico: `EXCLUDE ... WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED`, evaluada al commit sobre el estado final. Ambos inmutables una vez publicados (trigger) | Índice único parcial para el numérico: no es diferible y un intercambio o una reactivación fallaría a mitad de transacción | RF-3, RF-4, RF-5, D-6, D-15 |
| D5 | `minor_units smallint NULL`: `NULL` = "no aplicable" (ISO N.A.), `0` es cero decimales; `CHECK (minor_units IS NULL OR minor_units >= 0)`. En JSON es `integer \| null` (clave siempre presente) y la API devuelve `minor_units` entero o `null` | Centinela `-1` o texto `"N.A."`: mezcla tipos y deja pasar un valor inválido sin CHECK numérico | RF-4, CL-1, CL-2 |
| D6 | `fund_code boolean NOT NULL` (indicador de fondos, ISO lo declara). El nombre evita el prefijo `is_`, reservado a la semántica de estado prohibida por D-14 | `is_fund`: no viola la convención, pero se confunde con la familia `is_active` que los revisores buscan | RF-9, D-14, RF-27 |
| D7 | Estado como 001–003: `status IN ('active','inactive')`. Reemplazo **0..N** como `replacement_currency_ids uuid[] NOT NULL DEFAULT '{}'`, con CHECKs (sin `NULL`, ascendente sin repetidos mediante `reference.is_strictly_ascending`, sin el propio `currency_id`, no vacío solo si `inactive`) y dos constraint triggers diferidos: cada sucesor existe y **no hay ciclos** (CTE recursiva). Reactivar exige limpiar el arreglo en el mismo `UPDATE` (el CHECK lo impone). El dominio ordena el conjunto por `currency_id` al leerlo | Tabla puente `currency_replacement`: choca con la regla de no borrar físicamente al reactivar (RF-7), como en D21 de 003. Ciclos solo en el dominio (como 003): CA-3 exige que el ciclo falle también en la persistencia | RF-6, RF-10, D-17, CA-3, RNF-5 |
| D8 | `currency_locale (currency_id, locale_id, name)`, PK (`currency_id`, `locale_id`), FK a `reference.currency` y `reference.locale`, CHECK de recorte en `name`. Sin ningún texto en `reference.currency`; sin símbolos ni formato (D-11) | Columnas `name_en`/`name_es`: viola RF-23 de 001 y D-4 | RF-12, RF-16, D-4, D-11 |
| D9 | Conjunto obligatorio de locales de Currency v1 = archivo versionado y empaquetado `currencies/infrastructure/required-locales.v1.json` (`policy_version` 1, `locale_id` de `en` y `es`, con el código como guarda). Política propia: Currency no importa la de Countries ni la de Regions | Reutilizar el archivo de Countries: acopla catálogos que versionan por separado (D-13); y D-19 la define como regla de Currency v1 | RF-13, D-19, S-10 |
| D10 | **CountryCurrency temporal.** Tabla `country_currency (country_currency_id PK, country_id, currency_id, status, valid_from date NULL, valid_to date NULL, validity daterange GENERATED ALWAYS AS (daterange(valid_from, valid_to, '[)')) STORED, ...)`. Fechas `date` de día calendario; semiabierto `[valid_from, valid_to)`; `NULL` = extremo no acotado. `CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to)`. `EXCLUDE USING gist (country_id WITH =, currency_id WITH =, validity WITH &&) WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED` (requiere `btree_gist`). Monedas distintas del mismo país no se excluyen entre sí | `timestamptz`/`tstzrange`: la spec define día calendario y evita problemas de zona horaria. Dos fechas inclusivas: el fin inclusivo obliga a sumar un día y produce huecos o solapamientos en la transición HRK→EUR. Solapamiento solo en aplicación o por trigger: RNF-5 y las condiciones de carrera; la exclusión es correcta bajo concurrencia | RF-17, RF-18, RF-44, RF-45, CL-20, CL-21, CL-22, CA-21 |
| D11 | **Historia inmutable (RF-47)** por trigger `BEFORE UPDATE` sobre `country_currency`: `valid_from` y `valid_to` no cambian una vez no nulos (se pueden fijar desde `NULL` una única vez); `country_currency_id`, `country_id`, `currency_id` y `first_snapshot_version` son inmutables. Una corrección es retirar el registro (`status = 'inactive'`) y crear otro. Aplica igual a registros `inactive` | Permitir editar el fin: destruye la historia (RF-47, CA-19). Prohibir también completar un extremo ausente: impide cerrar vigencias abiertas (RF-46) | RF-7, RF-46, RF-47, CA-19, CL-26 |
| D12 | **RF-19 sin dependencia Country→Currency.** Dos constraint triggers diferidos, ambos en tablas de 004: sobre `country_currency` (`AFTER INSERT OR UPDATE`: una asociación `active` con `valid_to IS NULL` exige Country y Currency `active`) y sobre `currency` (`AFTER UPDATE OF status`: una Currency que pasa a `inactive` no puede tener asociaciones `active` abiertas). Un Country retirado **después** por 003 no puede bloquearse desde 004: el dominio valida el estado final contra el Country vigente en cada incorporación, y `check-integrity` + la vista `reference.country_currency_integrity_violation` detectan la deriva entre incorporaciones | Trigger sobre `reference.country`: crearía una dependencia de Countries hacia Currency (S-8, RNF-6, D-18 de 003). Modificar 003: prohibido en este Goal | RF-19, CL-13, CL-27, S-8, RNF-6 |
| D13 | **`status` y vigencia son independientes (RF-51).** Ningún trigger, columna calculada persistida ni tarea programada deriva uno del otro ni del reloj. "Vigente hoy" se calcula al consultar con `validity @> :as_of`. El reloj es un puerto `Clock` inyectable; el único valor dependiente de él es la fecha por defecto (RNF-7) | Columna `is_current` o job que cierra períodos vencidos: el catálogo cambiaría fuera de un snapshot (RF-10, RF-51) | RF-46, RF-48, RF-51, RNF-7, CL-28 |
| D14 | Fecha de referencia por defecto = día calendario **UTC** de la consulta; el consumidor puede pasar `as_of=YYYY-MM-DD` explícita. Formato estricto `^\d{4}-\d{2}-\d{2}$` y fecha real; otra cosa → 422 `invalid_as_of_date` (S-11) | Zona horaria local del servidor: el mismo catálogo daría respuestas distintas según el despliegue | RF-25, RF-48, S-11 |
| D15 | `currency_snapshot (snapshot_version PK, content_digest, locale_snapshot_version, country_snapshot_version [declarada], country_current_snapshot_version [vigente al incorporar], required_locales_version, provenance jsonb, artifact jsonb, incorporated_at)` sin `UPDATE`/`DELETE`/`TRUNCATE`. Versionado independiente de Locale y Countries (D-13); la versión vigente es `max(snapshot_version)` | Versión acoplada a Countries: obligaría a incorporar juntos (S-8) | RF-32, RF-41, RNF-2, D-13 |
| D16 | Locks: `gi-common-reference.currencies.incorporation` (exclusivo) + locks **compartidos** sobre los de Locale y Countries durante la incorporación: ni un locale ni un país cambian mientras se valida contra ellos | Sin locks compartidos: un locale o un país podría pasar a `inactive` entre la validación y el commit | RF-13, RF-14, RF-19, RF-40 |
| D17 | Una violación de constraint detectada al forzar `SET CONSTRAINTS ALL IMMEDIATE` antes del commit es un **rechazo** (salida 1) con la constraint nombrada; el solapamiento se informa como RF-45 y RF-19 como RF-19 | Error operativo (salida 2): un snapshot incoherente no es una falla del entorno | RF-39, RF-45, RF-52 |
| D18 | Contrato público = API HTTP read-only versionada `/v1/currencies*` (FastAPI), OpenAPI propio `contracts/currencies-api.v1.openapi.json`. Las consultas por país viven bajo `/v1/currencies/by-country/{country_id}` y `/v1/currencies/{currency_id}/countries`, porque `/v1/countries*` pertenece a la API de 003 y no se toca | `/v1/countries/{id}/currencies`: obligaría a cambiar el contrato y el despacho de 003 | RF-30, RF-31, RF-33, RF-35, RF-49, RNF-6 |
| D19 | `app.py` despacha por prefijo a cuatro aplicaciones: `/v1/currencies*` y `/v1/openapi/currencies.json` → Currency; el resto, igual que hoy | Sub-apps montadas de Starlette: cambia paths y `root_path` | D18, RNF-6 |
| D20 | Errores con códigos estables en inglés minúscula (`currency_not_found`, `country_not_found`, `invalid_currency_id`, `invalid_country_id`, `invalid_code`, `invalid_locale_id`, `unknown_locale`, `invalid_as_of_date`, `technical_error`), sin mensajes localizados. Cinco resultados distinguibles: 200 `active`, 200 `inactive`, 404, 422, 503 (RF-26). La validación RF-28 devuelve 200 con `result` ∈ {`active`,`inactive`,`not_found`} | Mensajes traducidos en el catálogo: pertenecen al consumidor | RF-24, RF-25, RF-26, RF-28 |
| D21 | `currencies` replica los helpers chicos (JSON canónico, `describe_error`, validación de conninfo, lector del schema); una prueba compara el JSON canónico con los vectores de 001 | Kernel compartido: obliga a reestructurar 001–003 y sus pruebas de frontera | RNF-1, D2 |
| D22 | Diff (RF-41): comando de solo lectura `diff <archivo>` que reutiliza el plan del dominio sin tomar el lock exclusivo ni escribir; incluye cambios de vigencia, altas, retiros, reemplazos y nombres | Dry-run dentro de `incorporate`: mezcla revisión con escritura | RF-41, RF-10 |
| D23 | Provenance por roles de fuente: `identity` (ISO 4217, siempre), `names` (siempre), `country_currency` (si hay asociaciones) y `validity` (si alguna asociación declara una fecha, fuente complementaria CLDR). Cada fuente trae nombre, edición, fecha de obtención, ubicación, checksum y licencia; `unresolved_conflicts` debe ser vacío | Procedencia opcional: viola D-20 y RF-41 | D-20, RF-40, RF-41, RF-52 |
| D24 | Aceptación nativa no existe como comando de AI-NATIVE v3.4.3: se ejecutan los criterios de la spec como pruebas caja negra (HTTP + CLI contra Postgres real) con un runner reproducible que escribe la evidencia en `acceptance/currencies/evidence/` | Afirmar PASS manualmente: prohibido; usar un comando inexistente: prohibido | CA-1, CA-4, CA-7, CA-9, CA-16–CA-24 |

## Archivos probables

```text
architecture.json                       # capas con rutas de currencies; módulo currencies público en interfaces/http
contracts/currency-snapshot.v1.schema.json, currency-snapshot.v1.example.json
contracts/currencies-api.v1.openapi.json
migrations/versions/0004_currencies.py
pyproject.toml                          # package-data de currencies (schema, política); testpaths con tests/acceptance
src/gi_common_reference/
  app.py, bootstrap.py                  # composición de las cuatro APIs y adaptadores
  currencies/domain/{model,codes,temporal,digest,snapshot,catalog,policy,ports,errors,diff}.py
  currencies/application/{incorporate,queries,diff}.py
  currencies/infrastructure/{postgres_repository,postgres_reader,snapshot_reader,policy_reader,clock,conninfo}.py
  currencies/infrastructure/{currency-snapshot.v1.schema.json,required-locales.v1.json}
  currencies/interfaces/{http,cli}.py
tests/{unit,integration,contract,acceptance}/…currencies…, tests/fixtures/currencies.py
tools/acceptance/currency_acceptance.py, acceptance/currencies/{README.md,evidence/}
docs/operacion.md, docs/desarrollo.md, README.md
```

## Datos (schema `reference`, migración 0004)

Todas las columnas son `NOT NULL` salvo las marcadas opcionales. Ninguna `tenant_id` ni `organization_id` ni texto dependiente del idioma en `currency` (RF-1, D-4). Ninguna FK desde 001–003 hacia Currency (RNF-6). La migración crea `CREATE EXTENSION IF NOT EXISTS btree_gist` (D10).

- **`currency_snapshot`:** D15, con FK a `locale_snapshot` y dos a `country_snapshot`; `country_current_snapshot_version >= country_snapshot_version`, `snapshot_version > 0`, `required_locales_version > 0`.
- **`currency`:** `currency_id uuid PK`, `alphabetic_code`, `numeric_code`, `minor_units smallint` (opcional, D5), `fund_code boolean`, `status`, `replacement_currency_ids uuid[]`, `first_snapshot_version`, `last_changed_snapshot_version`.
  - CHECKs: formatos de código (`^[A-Z]{3}$`, `^[0-9]{3}$`), `status`, `minor_units`, reemplazo (D7).
  - `UNIQUE (alphabetic_code)`; `EXCLUDE USING btree (numeric_code WITH =) WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED` (D4).
  - Constraint triggers diferidos: sucesores existentes y sin ciclos (D7); inactivación sin asociaciones abiertas `active` (D12).
- **`currency_locale`:** D8.
- **`country_currency`:** D10. Columnas: `country_currency_id uuid PK`, `country_id`, `currency_id`, `status`, `valid_from date` (opcional), `valid_to date` (opcional), `validity daterange GENERATED`, `first_snapshot_version`, `last_changed_snapshot_version`. FK a `reference.country`, `reference.currency` y a `currency_snapshot`. Índices: `(country_id, currency_id)`, `(currency_id, country_id)` y el GiST de la exclusión (parcial `status = 'active'`, también sirve a `validity @> as_of`).
- **Vista `reference.country_currency_integrity_violation`:** asociaciones `active` con `valid_to IS NULL` sobre un Country o una Currency `inactive`; vacía en un catálogo íntegro (D12). Solo lectura.
- **Triggers:** sin `DELETE` ni `TRUNCATE` en `currency`, `currency_locale`, `country_currency` y `currency_snapshot` (RF-7, RF-37); inmutables: `currency_id`, `alphabetic_code`, `numeric_code`, `first_snapshot_version`, el par (`currency_id`, `locale_id`) y, en `country_currency`, `country_currency_id`, `country_id`, `currency_id`, `first_snapshot_version` y los extremos de vigencia ya no nulos (D11). Mutables: `minor_units`, `fund_code`, `status`, reemplazo y `last_changed_snapshot_version`; `name`; en la asociación, `status`, extremos ausentes (una vez) y `last_changed_snapshot_version`.
- **Privilegios** (D10 de 001): `reference_reader` solo `SELECT` (incluida la vista); `reference_loader` `SELECT`, `INSERT` y `UPDATE` de las columnas mutables listadas. Nada para `PUBLIC`, `anon`, `authenticated`. Condicionales a que los roles existan, como 0001–0003.
- La versión vigente es `max(currency_snapshot.snapshot_version)`, independiente de Locale y Countries (D-13).

## Formato del snapshot (contrato con PREP)

```json
{ "snapshot_version": 1, "content_digest": "sha256:…", "country_snapshot_version": 1,
  "provenance": {
    "sources": [{"role": "identity", "name": "ISO 4217 List One", "edition": "…", "retrieved_at": "2026-11-01",
                 "location": "…", "checksum": "sha256:…", "license": "…"}],
    "unresolved_conflicts": [] },
  "currencies": [{"currency_id": "uuid", "alphabetic_code": "ARS", "numeric_code": "032",
                  "minor_units": 2, "fund_code": false, "status": "active", "replacement_currency_ids": []}],
  "currency_names": [{"currency_id": "uuid", "locale_id": "uuid", "name": "Argentine Peso"}],
  "country_currencies": [{"country_currency_id": "uuid", "country_id": "uuid", "currency_id": "uuid",
                          "status": "active", "valid_from": "2023-01-01", "valid_to": null}] }
```

`minor_units: null` significa "no aplicable". Roles de fuente: `identity`, `names`, `country_currency`, `validity` (D23). El JSON Schema se publica en `contracts/` con un ejemplo sellado y marcado como no productivo (S-9); la copia empaquetada debe ser equivalente.

## Incorporación (CLI `python -m gi_common_reference.currencies.interfaces.cli incorporate <archivo>`, `diff <archivo>` y `check-integrity`)

Una transacción con los locks de D16. Ante el primer paso que falla se informan todas sus violaciones, rollback y salida 1 (RF-39). Salida 0 incorporado o no-op; 2 error operativo.

1. Schema (lector) y digest de contenido recalculado (RF-41).
2. Clasificación contra el historial: A no-op, B/C rechazo, D continúa; sin historial, D (RF-39).
3. Contexto: hay una versión vigente de Locale y de Countries; `en` y `es` de la política existen, son `active` y su código coincide (RF-13); `country_snapshot_version` declarada está incorporada y es ≤ la vigente (RF-41).
4. Identidad y completitud: `currency_id` y `country_currency_id` UUID sin repetir; ninguna Currency, nombre ni asociación publicados ausentes (RF-37); ids nuevos nunca usados; `country_id`/`currency_id` de una asociación publicada sin cambio (RF-2, RF-7).
5. Códigos: formato y unidades menores (RF-4); ningún código de una Currency publicada cambia y un alfabético publicado no pasa a otro `currency_id` (RF-5); RF-3 sobre el estado final.
6. Ciclo de vida: `status` válido; reemplazos (0..N) solo en `inactive`, sin duplicados, existentes, no a sí misma y sin ciclos (RF-6); reactivación con conjunto vacío (RF-10).
7. Localizaciones: Currency y `locale_id` existentes; a lo sumo una por par; nombre sin vacío ni espacios en los bordes; nombre **nuevo** con locale `inactive` rechazado y los publicados se conservan; cada Currency tiene `name` en `en` y `es` (RF-12–RF-16).
8. CountryCurrency: `country_id` existe en el Country vigente (RF-40); inicio < fin; sin solapamiento entre `active` del mismo par (RF-45); extremos publicados sin modificar ni reabrir (RF-47); ninguna `active` con vigencia abierta sobre Country o Currency `inactive` (RF-19, RF-52); coherencia con el retiro de una Currency (RF-38).
9. Procedencia: fuentes con todos sus campos, roles requeridos presentes, `unresolved_conflicts` vacío (RF-40, RF-41, RF-52).
10. Escritura, en este orden: `currency_snapshot` (con versiones de Locale, de Countries declarada y vigente, y de la política) → Currency nuevas → actualizadas → nombres nuevos → actualizados → asociaciones nuevas → actualizadas → `SET CONSTRAINTS ALL IMMEDIATE` (D17) → commit.

`diff`: carga el estado vigente y calcula el plan (pasos 1–9) sin escribir; imprime altas, cambios de atributos, de `status`, reemplazos, nombres, asociaciones y vigencias, y las violaciones si las hay (D22, RF-41). `check-integrity`: lee la vista de D12; salida 0 íntegro, 1 con violaciones.

## API pública (read-only, D18)

| Endpoint | Respuesta | Cubre |
|---|---|---|
| `GET /v1/currencies?include_inactive=&exclude_funds=&locale_id=` | 200 lista ordenada por (`alphabetic_code` `COLLATE "C"`, `currency_id`); por defecto solo `active` | RF-27 |
| `GET /v1/currencies/version` | 200 `{snapshot_version}` (`null` con catálogo vacío) | RF-32 |
| `GET /v1/currencies/by-code/{code}?locale_id=` | `^[A-Za-z]{3}$` o 422 `invalid_code`; 200 sin distinguir mayúsculas · 404 | RF-23, RF-24, RF-25 |
| `GET /v1/currencies/by-country/{country_id}?as_of=&include_inactive=&exclude_funds=&locale_id=` | 200 asociaciones `active` cuya vigencia contiene `as_of`, ordenadas por (código, inicio, id); `[]` si no hay · 404 `country_not_found` · 422 | RF-18, RF-30, RF-48 |
| `GET /v1/currencies/by-country/{country_id}/history?include_inactive=&locale_id=` | 200 todas las asociaciones sin filtrar por fecha, ordenadas por (inicio con ausentes primero, código, id) | RF-49, RF-50 |
| `GET /v1/currencies/{currency_id}?locale_id=` | 200 con `status` (activo o inactivo) · 404 · 422 `invalid_currency_id` | RF-22, RF-24, RF-25, RF-29 |
| `GET /v1/currencies/{currency_id}/validation` | 200 `{result: active\|inactive\|not_found}` · 422 | RF-28 |
| `GET /v1/currencies/{currency_id}/countries?as_of=&include_inactive=` | 200 asociaciones con la misma forma · 404 · 422 | RF-31, RF-48 |
| `GET /v1/currencies/{currency_id}/countries/history?include_inactive=` | 200 historial completo | RF-49 |
| Otros métodos | 405 | RF-34 |

- Las rutas fijas (`version`, `by-code`, `by-country`) se declaran antes que `{currency_id}`; una prueba cubre el solapamiento.
- Forma: `{snapshot_version, data}` o `{snapshot_version, error}`; `snapshot_version` es la versión vigente de Currency y `null` con catálogo vacío; nunca 500 por catálogo vacío (CL-15). Una falla técnica es 503 `technical_error`, distinta de 404 y 422 (RF-26).
- `Currency` = `{currency_id, alphabetic_code, numeric_code, minor_units, fund_code, status, replacement_currency_ids, name}`; `name` es el del `locale_id` pedido o `null` si no se pidió locale o no hay traducción: sin fallback (RF-15). `minor_units` es `null` si no aplica.
- `CountryCurrency` = `{country_currency_id, country_id, currency: Currency, status, valid_from, valid_to}`. No se devuelve ningún dato de Country más que su `country_id`: el consumidor resuelve el resto por el contrato de 003 (RF-20).
- `locale_id` mal formado o inexistente → 422 (`invalid_locale_id`, `unknown_locale`), distinto de 404. Ninguna respuesta lleva mensajes localizados (D20).
- No existe ruta, método ni operación de escritura (RF-34, CA-13).

## Estrategia de pruebas (TDD por requisito)

- **Sin red** en todas las suites (RNF-8 de 003, RF-42), como 001–003: `pytest-socket` y el guard de red en CLI y API.
- **Unit, dominio puro:**
  - Códigos y unidades menores: ARS `032`, `008`, `usd`/`US$`/`" USD"`, unidades 0, 2, 3, 4 y "no aplicable" distinto de 0, fondos, unidades especiales.
  - `temporal.py`: contención con extremos ausentes, límites semiabiertos, transición el mismo día, inicio ≥ fin, solapamiento del mismo par, monedas simultáneas, readopción, reglas de inmutabilidad de extremos y corrección por retiro+alta.
  - Digest y paridad con los vectores de 001; clasificación A–D.
  - Reemplazo: 0, 1, N, repetidos, nulos, propio, ciclo, `active` con reemplazo, reactivación.
  - Cada paso 3–9 de la incorporación: Country inexistente, locales obligatorios faltantes o `inactive`, conflicto de fuentes, asociación `active` abierta sobre un retiro; plan de cambios y diff.
- **Unit, aplicación e interfaces:** incorporación con repositorio en memoria (no-op, rechazo sin escrituras, orden de escritura); consultas con lector y reloj en memoria; CLI (códigos de salida, `diff` sin escrituras, sin credenciales en la salida).
- **Integración (Postgres 16 en testcontainers, imprescindible: lo exige RNF-5):**
  - SQL directo contra cada constraint y trigger de 0004: formatos, `NULL`, unicidad alfabética y numérica `active` diferida, exclusión temporal por par (solapado rechazado, adyacente aceptado, distinta moneda aceptada, readopción aceptada), CHECK inicio < fin, inmutabilidad de extremos y de identidad, ciclo de reemplazo, RF-19 en ambos triggers, `DELETE`/`TRUNCATE`, privilegios, allowlist de columnas sin `tenant_id` ni textos.
  - Una prueba con dos conexiones concurrentes que insertan períodos solapados del mismo par: una falla.
  - Incorporación de punta a punta con datos reales de Locale y Countries (incorporados con sus CLI): primer snapshot, reenvío no-op, rechazo con dump idéntico, transición HRK→EUR, división CSK→CZK+SKK, reactivación, mismo estado lógico en dos bases (RNF-1), `upgrade`/`downgrade` de 0004 sin tocar 0001–0003.
  - Deriva: retirar un país en 003 deja una violación visible en `check-integrity` y la siguiente incorporación de Currency la exige corregida.
- **Contrato:** API con datos incorporados (todos los endpoints, 404 vs 422 vs 503, `usd`/`USD`, `008`, sin fallback, `as_of` límite, historial, validación, 405, catálogo vacío, `reference_reader`); OpenAPI generado = `contracts/currencies-api.v1.openapi.json` y los de Locale, Regions y Countries no cambian; ejemplo de snapshot válido contra el schema y con digest correcto; schema publicado = empaquetado; el wheel instalado trae schema y política; check `architecture` de AI-NATIVE y pruebas de frontera extendidas a `currencies` (no importa `locales`/`regions`/`countries` y Country no importa Currency).
- **Aceptación (D24):** `tests/acceptance` (caja negra por HTTP y CLI) y el runner `tools/acceptance/currency_acceptance.py`, que produce la evidencia reproducible (comandos, resultados, hashes de entradas y artefactos) en `acceptance/currencies/evidence/`.
- **Datos de prueba:** fixtures sintéticos y deterministas (`tests/fixtures/currencies.py`), marcados como no productivos (S-9). Incluyen ARS, USD, EUR, JPY (0), KWD (3), CLF (4), XAU (no aplicable), BOV/CHE/CHW (fondos), XDR (sin países), PAB+USD en PA, EUR en varios países, AQ sin moneda, HRK→EUR (HR), VEF→VES, CSK→CZK+SKK (división) y 891 (YUM→CSD).

## Cobertura de requisitos

| Requisito | Dónde |
|---|---|
| RF-1, RF-2, CA-2 | Datos, allowlist de columnas, D1 |
| RF-3, RF-4, RF-5, CA-3 | D4, D5, pasos 5, triggers de inmutabilidad |
| RF-6, RF-10, RF-11 | D7, pasos 4 y 6 |
| RF-7, RF-37 | Triggers sin `DELETE`, paso 4 |
| RF-8, CA-13 | Sin tablas ni rutas de cotización; API sin escritura |
| RF-9 | D7, CHECK de `status`, D13 |
| RF-12, RF-14, RF-15, RF-16 | D8, paso 7, API |
| RF-13, D-19 | D9, paso 3 y 7 |
| RF-17, RF-18, RF-44, RF-45, CA-21 | D10, paso 8 |
| RF-19, RF-38, RF-52, CL-13, CL-27 | D12, pasos 8 y 10, `check-integrity` |
| RF-20, RF-21, CA-8 | Datos (sin columnas cruzadas), `architecture.json`, API |
| RF-22, RF-23, RF-24, RF-25, RF-26, RF-27, RF-28, RF-29, CA-4, CA-5, CA-6 | API, D20 |
| RF-30, RF-31, RF-48, RF-49, RF-50, CA-7, CA-17, CA-18 | API, D14, D10 |
| RF-32, RF-41, RNF-2, CA-14 | `currency_snapshot` (D15), `GET /version` |
| RF-33, RF-34, RF-35 | D18, D19, API sin escritura |
| RF-36, RF-39, RF-40, CA-10, CA-11 | D2, D16, D17, pasos 1–10 |
| RF-42, RNF-8 | Sin red en runtime ni en pruebas |
| RF-43, CA-15 | Altas aditivas `inactive` con `currency_id` nuevos; prueba de integración |
| RF-46, RF-47, RF-51, CA-19, CA-20, CL-28 | D11, D13 |
| RNF-1, RNF-7 | Orden determinístico, `Clock` inyectable, prueba en dos bases |
| RNF-3, RNF-4 | Privilegios, sin RLS por tenant |
| RNF-5 | Datos, pruebas SQL directas |
| RNF-6, CA-24 | D18, D19, `architecture.json`, diff de 001–003 vacío |
| CA-1, CA-9, CA-12, CA-16, CA-22, CA-23 | Fixtures, aceptación (D24) |
| CL-1 a CL-28 | Un caso de prueba por límite: unit de dominio, SQL directo, integración y contrato (Estrategia de pruebas; CL-4 a CL-12 y CL-16 a CL-19 con los fixtures nombrados; CL-14, CL-24 y CL-25 con las consultas por fecha) |

## Slices y DAG

```text
T1 esqueleto ─┬→ T2 migración 0004 ─────────────┬→ T6 incorporación + repositorio + CLI ─┬→ T9 aceptación
              ├→ T3 snapshot + admisión ─┬→ T4 dominio Currency ┘                        │
              │                          └→ T5 dominio temporal ┘                        │
              └──────────────────────────→ T7 consultas + lector ─→ T8 API + composición ┘
T9 → T10 documentación y cierre
```

Orden de ejecución = orden de `tasks.md`: T1, T2, T3, T4, T5, T6, T7, T8, T9, T10. T2 y T3 son independientes entre sí; T4 y T5 también. T7 necesita la migración (T2) y datos incorporados (T6) para su integración.

## Riesgos

- **`btree_gist` (D10):** la exclusión temporal por par necesita la extensión. Viene con PostgreSQL y Supabase, pero crearla exige privilegio; la migración falla de forma explícita si no se puede y el runbook documenta el comando. Sin esto no hay garantía persistente de RF-45.
- **Deriva por retiro de país (D12, S-8):** 003 puede retirar un país sin saber de Currency; hasta la siguiente incorporación de Currency existirá una asociación `active` abierta sobre un país `inactive`. Es inherente a la restricción de S-8 y se mitiga con `check-integrity`, la vista y el orden de rollout (incorporar Currency en el mismo release). Requiere conocimiento del pipeline (fuera de alcance).
- **Fecha por defecto (D14):** las consultas "actuales" dependen del reloj UTC; los consumidores sensibles deben pasar `as_of` explícita.
- **Datos reales (S-9):** el repositorio solo contiene fixtures sintéticos; la verificación de CA-1 contra el dataset real de PREP queda pendiente y se declara.
- **Solapamiento de rutas** `by-*` / `{currency_id}` (D18): cubierto por prueba.
- **Constraint triggers y exclusiones diferidas:** su costo crece con las filas modificadas; el catálogo ISO tiene ~180 monedas y unos cientos de asociaciones.
- **Historia CLDR incompleta:** extremos ausentes son válidos (CL-23); el consumidor debe tratarlos como no acotados.

## Rollout y rollback

- **Rollout:** roles ya existentes (001) → `alembic upgrade head` (0004; `btree_gist`) → desplegar la API (misma URL de `reference_reader`) → incorporar el snapshot de Countries requerido → incorporar el primer snapshot de PREP con `reference_loader` y la CLI de `currencies` → `check-integrity`. Comandos y SQL en `docs/operacion.md`.
- **Rollback:** antes del primer consumidor, `alembic downgrade 0003` borra solo lo de 0004 (incluida la vista y la extensión no se elimina: puede estar en uso). Después no hay rollback de datos: se corrige hacia adelante con un snapshot nuevo (RF-39).

## Fuera de este plan

- Modificar 001, 002 o 003; una política transversal de locales; pipeline de PREP y dataset real (S-9).
- Búsqueda por código numérico, moneda principal, símbolos y formato (D-10, D-11, D-12).
- Migración de consumidores a `currency_id`.
