# Plan 003 — Countries

- **Estado:** approved (2026-10-30, derivado de la spec aprobada; mismo alcance, sin requisitos nuevos)
- **Spec:** [spec.md](spec.md)
- **Perfil:** `python-service`; sigue la estructura de [001-locales](../001-locales/plan.md) y [002-regions-subregions](../002-regions-subregions/plan.md)

## Precondición (verificada 2026-10-30, PASS)

La rama `feature/003-countries` incorpora `develop` (`ad0762b`, merge `7c15a22`), que contiene 001 y 002 aprobadas e implementadas. Lo que 003 toma de ahí, sin cambiarlo:

- `locale_id` UUID estable (tabla `reference.locale`, sin `DELETE`); `status` = `active` | `inactive`; RF-23–RF-25 de 001 como contrato de las entidades `<Entidad>Locale`.
- `region_id` / `subregion_id` UUID estables (`reference.region`, `reference.subregion`); `UNIQUE (region_id, subregion_id)` en `subregion` como destino de la FK compuesta (D8 de 002); `region`/`subregion` sin `DELETE` (RF-30 de 002).
- Snapshots: `snapshot_version` entera positiva con saltos, digest SHA-256 del JSON canónico sin `content_digest`, clasificación A/B/C/D, incorporación atómica con locks, historial inmutable (D5, D7, D9, D12, D13 de 001/002).
- Locks: `gi-common-reference.locales.incorporation` y `gi-common-reference.regions.incorporation`.
- `architecture.json`, pruebas de frontera y raíz de composición (`bootstrap.py`, `app.py`) ya generalizadas a dos módulos.

## Arquitectura y estrategia

Un módulo nuevo `countries`, hexagonal como `locales` y `regions` (RNF-6, RNF-7):

```text
countries/interfaces (HTTP read-only, CLI de incorporación y diff)
  → countries/application (consultas, incorporación, diff)
     → countries/domain (modelo, códigos, digest, admisión, validación, SVG, puertos)
        ← countries/infrastructure (Postgres, lector de snapshot, política de locales, almacén de banderas)
```

- Toda la validación de un snapshot es una función **pura** del dominio: `(snapshot, estado vigente, vista de Locale, vista de Regions, política) → plan de cambios | violaciones`. La base repite las invariantes como constraints y triggers (RNF-5).
- `countries` no importa código de `locales` ni de `regions` (ni al revés): depende de ellos solo por datos, con FK hacia `reference.locale`, `reference.region` y `reference.subregion`, y por lectura SQL de `reference.locale`, `reference.locale_snapshot`, `reference.region`, `reference.subregion` y `reference.region_snapshot` en el mismo schema (RF-6, RF-36, RF-47, RF-48).
- La verificación del asset SVG (E/S) vive en la capa de aplicación a través de un puerto `FlagStore`; el chequeo del contenido (bien formado, sin contenido activo) es una función pura del dominio.
- `bootstrap.py` sigue siendo la única raíz de composición y cablea también `countries`. `app.py` pasa a despachar por prefijo a tres aplicaciones FastAPI sin cambiar los contratos de Locale ni de Regions.

## Decisiones

| # | Decisión | Alternativa descartada y motivo | Cubre |
|---|---|---|---|
| D1 | `country_id` = UUID que viaja en el snapshot y que el sistema valida y registra sin generarlo ni modificarlo, como `locale_id` y `region_id` | UUIDv5 de `alpha2`: el id dependería de un código recodificable (RF-2) | RF-2, RF-45, D-11 |
| D2 | Snapshot = un único documento JSON, catálogo completo (no delta): `countries`, `country_names`, `flags`, `flag_exceptions`, `recodings`, `code_reassignments`, `region_snapshot_version` y `provenance`. Mismas reglas de digest que 001 (D7) | Un archivo por entidad: identidad atómica más difícil. Delta: no permite detectar omisiones (RF-21) | RF-21, RF-27, RF-41, RF-43 |
| D3 | Todos los campos opcionales viajan como clave presente con `null`; los códigos son siempre `string` en el schema (`type: string`, patrón estricto). El lector rechaza claves duplicadas, floats y tipos no string en códigos; no hay coerción numérica ni de `"NA"` | Omitir claves opcionales: dificulta distinguir ausente de olvidado. Aceptar enteros para `numeric_code`: perdería ceros | RF-5, CL-5, CL-6 |
| D4 | Códigos como texto con CHECK de formato: `alpha2 ~ '^[A-Z]{2}$'`, `alpha3 ~ '^[A-Z]{3}$'`, `numeric_code ~ '^[0-9]{3}$'`, `calling_code ~ '^[1-9][0-9]{0,2}$'`. Unicidad entre `active` con tres `EXCLUDE ... WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED`, evaluada al commit sobre el estado final (RF-44) | Índices únicos parciales: no son diferibles y un intercambio de códigos fallaría a mitad | RF-3, RF-5, RF-44 |
| D5 | Clasificación: `region_id` y `subregion_id` nullable; `CHECK (subregion_id IS NULL OR region_id IS NOT NULL)`; `region_id → reference.region`; FK compuesta `(region_id, subregion_id) → reference.subregion (region_id, subregion_id) DEFERRABLE INITIALLY DEFERRED` (MATCH SIMPLE: no se evalúa sin `subregion_id`). Una reclasificación de 002 que deja un Country incoherente falla al commit salvo que la misma transacción lo corrija | Trigger propio de coherencia: duplica lo que una FK compuesta ya garantiza (D8 de 002) | RF-6, RF-48, CL-17 |
| D6 | `codes_snapshot_version` por país: snapshot en que obtuvo su tripleta vigente. Búsqueda por código: el `active` que lo posee; si no, el `inactive` con mayor `codes_snapshot_version` (desempate por `country_id`); códigos históricos no resuelven (RF-10) | Buscar en el historial de artefactos: costo por request | RF-9, RF-10 |
| D7 | Recodificación = una traza `country_recoding` por (país, snapshot) con la tripleta anterior y la nueva completas (`NOT NULL`, al menos un código distinto) y su provenance. Los códigos históricos para RF-43 salen de esa traza. Reasignación = declaración `code_reassignments` (país, tipo de código, código, provenance) | Una traza por código: una recodificación real (TP/TMP/626 → TL/TLS/626) cambia varios a la vez y la tripleta es indivisible (RF-4) | RF-4, RF-41–RF-43, RF-46 |
| D8 | Estado como 002: `status IN ('active','inactive')`. El reemplazo es **0..N** (`replacement_country_ids`, D21), solo no vacío si `inactive`, sin duplicados ni el propio país, existencia por constraint trigger diferido y sin ciclos en el grafo (validado en dominio) | Atributo `is_active`: prohibido por la convención común (RF-39). Reemplazo singular: no expresa una división (AN → CW/SX/BQ) | RF-39, RF-40, RF-52 |
| D9 | `country_locale (country_id, locale_id, name, official_name)`, PK (`country_id`, `locale_id`), FK a `reference.country` y `reference.locale`, CHECK de recorte en `name` y en `official_name` (si no es `NULL`). Sin ningún texto en `reference.country` | Columnas `name_es`/`name_en`: viola RF-23 de 001 y RF-34 | RF-31–RF-34 |
| D10 | Conjunto obligatorio de locales de Countries = archivo versionado y empaquetado `countries/infrastructure/required-locales.v1.json` (`policy_version` 1, mismos `locale_id` de `en` y `es` que fija la política de Regions, con el código como guarda). Política propia: Countries no importa la de Regions | Reutilizar el archivo de Regions: acopla dos catálogos que versionan por separado (D-17) | RF-35, S-4 |
| D11 | Banderas (el `asset_path` es un nombre de archivo plano, sin subdirectorios, para que `package-data` `flags/*` y `-text` de `.gitattributes` lo cubran exactamente): tabla `country_flag (country_id PK, asset_path, sha256, exception_reason, snapshot_version)` con `CHECK` de exactamente una de (`asset_path` + `sha256`) o `exception_reason`. El asset vive como archivo versionado bajo `src/gi_common_reference/countries/assets/flags/` (se empaqueta como package-data) y se resuelve por el puerto `FlagStore`. Nada binario en `country` ni en la base | Guardar el SVG en la base: duplica la fuente de verdad del repositorio y mezcla blobs con el catálogo (D-3). Servirlo desde una ruta de configuración: el DB y el archivo servido podrían diferir | RF-19, RF-49, RF-50 |
| D12 | Seguridad del SVG: se rechaza todo asset con `DOCTYPE`/`ENTITY`, raíz distinta de `svg`, elementos `script`/`foreignObject`/`iframe`/`object`/`embed` y de animación SMIL (`set`/`animate`/`animateTransform`/`animateMotion`/`discard`, que pueden escribir un `href` peligroso por `to` o `values`; una bandera es arte estático), atributos `on*` y referencias (`href`, `xlink:href`, `src`, `url(...)`) que no sean fragmentos locales `#id`; tamaño máximo de 512 KiB. Parseo con `xml.etree` tras rechazar DTD/entidades por inspección de bytes | Agregar `defusedxml`/`lxml`: dependencia nueva evitable para un chequeo de lista cerrada | RF-49 |
| D13 | Contrato público = API HTTP read-only versionada `/v1/countries*` (FastAPI), OpenAPI propio en `contracts/countries-api.v1.openapi.json` | Agregar rutas al OpenAPI de Locale o Regions: cambiaría contratos ya publicados | RF-8–RF-18, RF-50, RNF-6 |
| D14 | `app.py` despacha por prefijo a tres aplicaciones: `/v1/countries*` y `/v1/openapi/countries.json` → Countries; `/v1/regions*`, `/v1/subregions*` y `/v1/openapi/regions.json` → Regions; el resto → Locale, intactas | Montar sub-apps de Starlette: cambia paths y `root_path`. Procesos separados: duplica la operación | D13, RNF-6 |
| D15 | Locks: `gi-common-reference.countries.incorporation` (exclusivo) + locks **compartidos** sobre los de Locale y Regions durante la incorporación: ni Locale ni Regions cambian mientras se valida contra ellos | Sin locks compartidos: un locale o una subregión podría pasar a `inactive` entre la validación y el commit | RF-24, RF-36, RF-47, RF-48 |
| D16 | `countries` replica los helpers chicos que necesita (JSON canónico, `describe_error`, validación de conninfo); una prueba compara el JSON canónico con los vectores de 001 | Kernel compartido: obliga a reestructurar 001 y 002 y sus pruebas de frontera | RNF-7, D2 |
| D17 | Una violación de constraint detectada al forzar `SET CONSTRAINTS ALL IMMEDIATE` antes del commit es un **rechazo** (salida 1) con la constraint nombrada; una FK compuesta violada se informa como incoherencia de clasificación (RF-6, CL-17) | Error operativo (salida 2): un snapshot incoherente con otro catálogo no es una falla del entorno | RF-24, RF-6 |
| D18 | Diff (RF-30): comando de solo lectura `diff <archivo>` que carga el estado vigente y reutiliza el plan de cambios del dominio; no toma el lock exclusivo ni escribe. No verifica los assets (eso ocurre al incorporar) | Dry-run dentro de `incorporate`: mezcla revisión con escritura | RF-30 |
| D19 | Errores con códigos estables en inglés minúscula (`country_not_found`, `invalid_country_id`, `invalid_code`, `invalid_locale_id`, `unknown_locale`, `flag_not_declared`, `flag_integrity_error`) y sin mensajes localizados | Mensajes traducidos en el catálogo: pertenecen a la capa consumidora (D-19 de la spec) | RNF-9 |
| D20 | La coherencia de clasificación contra `active` de 002 (RF-48) se valida al incorporar, bajo los locks compartidos, no con constraint: depende de estado de otro catálogo en el tiempo y 002 puede inactivar después | Trigger entre catálogos: haría depender a 002 de 003 (RNF-7) | RF-48 |
| D21 | Reemplazo 0..N como columna `replacement_country_ids uuid[] NOT NULL DEFAULT '{}'` en `country`, con CHECKs (sin `NULL` ni duplicados, sin el propio `country_id`, no vacío solo si `inactive`) y un constraint trigger diferido que exige que cada sucesor exista (una FK no aplica a un arreglo). El dominio ordena el conjunto ascendente por `country_id` al leerlo del snapshot, así comparar contra el vigente ignora el orden y la lectura es determinista. Como la columna cambia de tipo y `0003` no se mergeó ni se desplegó, se modifica `0003` en su lugar: una `0004` dejaría una columna singular creada y eliminada en la misma entrega. Los sucesores de una división no necesitan un tipo de relación: la semántica de la sucesión queda fuera de alcance (spec) | Tabla puente `country_replacement (country_id, successor_id)`: dos FK reales, pero obliga a borrar filas al reactivar un país y choca con la regla de no borrar físicamente (RF-7); un arreglo se limpia con un `UPDATE` permitido. Mantener `replacement_country_id` y agregar otro campo: dos formas de decir lo mismo | RF-40, RF-52, RNF-5 |

## Archivos probables

```text
architecture.json                       # capas con rutas de countries; módulo countries público en interfaces/http
contracts/country-snapshot.v1.schema.json, country-snapshot.v1.example.json
contracts/countries-api.v1.openapi.json
migrations/versions/0003_countries.py
pyproject.toml                          # package-data de countries (schema, política, assets/flags/*.svg)
src/gi_common_reference/
  app.py, bootstrap.py                  # composición de las tres APIs y adaptadores
  countries/domain/{model,codes,digest,snapshot,catalog,policy,svg,ports,errors}.py
  countries/application/{incorporate,queries,diff}.py
  countries/infrastructure/{postgres_repository,postgres_reader,snapshot_reader,policy_reader,flag_store,conninfo}.py
  countries/infrastructure/{country-snapshot.v1.schema.json,required-locales.v1.json}
  countries/assets/flags/             # vacío hasta que el dataset de PREP aporte los SVG; README.md describe el contrato
  countries/interfaces/{http,cli}.py
tests/{unit,integration,contract}/…countries…, tests/fixtures/{countries,country_fakes}.py, tests/fixtures/flags/*.svg
docs/operacion.md, docs/desarrollo.md, README.md
```

## Datos (schema `reference`, migración 0003)

Todas las columnas son `NOT NULL` salvo las marcadas opcionales. Ninguna `tenant_id` ni texto dependiente del idioma en `country` (RF-1, RF-34). Ninguna FK hacia Currency ni consumidores (RNF-7).

- **`country_snapshot`:** `snapshot_version bigint PK CHECK > 0`, `content_digest`, `locale_snapshot_version bigint REFERENCES locale_snapshot`, `region_snapshot_version bigint REFERENCES region_snapshot` (declarada, RF-47), `region_current_snapshot_version bigint REFERENCES region_snapshot` (vigente al incorporar), `required_locales_version integer`, `provenance jsonb`, `artifact jsonb`, `incorporated_at`. Sin `UPDATE`/`DELETE`/`TRUNCATE` (RNF-2). `region_current_snapshot_version >= region_snapshot_version`.
- **`country`:** `country_id uuid PK`, `alpha2`, `alpha3`, `numeric_code` (con sus CHECK), `region_id` y `subregion_id` (opcionales, con D5), `calling_code` (opcional), `status CHECK IN ('active','inactive')`, `replacement_country_ids uuid[] NOT NULL DEFAULT '{}'` (0..N, D21), `first_snapshot_version`, `codes_snapshot_version`, `last_changed_snapshot_version`.
  - CHECKs: `replacement_country_ids` sin `NULL`, sin duplicados y sin el propio `country_id`, no vacío solo si `inactive`, y cada sucesor existente (constraint trigger diferido, D21); `subregion_id` implica `region_id`.
  - `EXCLUDE USING btree (alpha2 WITH =) WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED`, e igual para `alpha3` y `numeric_code` (RF-3).
- **`country_locale`:** D9.
- **`country_flag`:** D11, con FK a `country` y a `country_snapshot`.
- **`country_recoding`:** PK (`country_id`, `snapshot_version`); `previous_alpha2`, `previous_alpha3`, `previous_numeric_code`, `new_alpha2`, `new_alpha3`, `new_numeric_code` (todos `NOT NULL`, con formato), `provenance jsonb`; CHECK de que la tripleta anterior difiere de la nueva. Inmutable.
- **Triggers:** sin `DELETE` ni `TRUNCATE` en `country`, `country_locale`, `country_flag`, `country_snapshot` y `country_recoding` (RF-7, RF-21); `country_id`, `first_snapshot_version` y el par (`country_id`, `locale_id`) inmutables. Mutables solo: códigos y `codes_snapshot_version` (un trigger rechaza cambiar la tripleta si no existe la fila de `country_recoding` del mismo `codes_snapshot_version`; el dominio valida su contenido), `status`, reemplazo, `region_id`, `subregion_id`, `calling_code`, `last_changed_snapshot_version`, nombres, bandera.
- **Privilegios** (D10 de 001): `reference_reader` solo `SELECT`; `reference_loader` `SELECT`, `INSERT` y `UPDATE` de las columnas mutables. Nada para `PUBLIC`, `anon`, `authenticated`. Condicionales a que los roles existan, como 0001 y 0002.
- La versión vigente es `max(country_snapshot.snapshot_version)`, independiente de Locale, Regions y Currency (D-17).

## Formato del snapshot (contrato con PREP)

```json
{ "snapshot_version": 1, "content_digest": "sha256:…", "region_snapshot_version": 1,
  "provenance": {
    "sources": [{"role": "identity", "name": "ISO 3166-1", "edition": "…", "retrieved_at": "2026-10-30",
                 "location": "…", "checksum": "sha256:…", "license": "…"}],
    "unresolved_conflicts": [] },
  "countries": [{"country_id": "uuid", "alpha2": "NA", "alpha3": "NAM", "numeric_code": "516",
                 "region_id": "uuid", "subregion_id": "uuid", "calling_code": "264",
                 "status": "active", "replacement_country_ids": []}],
  "country_names": [{"country_id": "uuid", "locale_id": "uuid", "name": "Namibia", "official_name": "Republic of Namibia"}],
  "flags": [{"country_id": "uuid", "asset_path": "na.svg", "sha256": "sha256:…", "media_type": "image/svg+xml", "source": "flags"}],
  "flag_exceptions": [{"country_id": "uuid", "reason": "…"}],
  "recodings": [{"country_id": "uuid",
                 "previous": {"alpha2": "TP", "alpha3": "TMP", "numeric_code": "626"},
                 "new": {"alpha2": "TL", "alpha3": "TLS", "numeric_code": "626"},
                 "provenance": {"source": "…"}}],
  "code_reassignments": [{"country_id": "uuid", "code_kind": "alpha2", "code": "XX", "provenance": {"source": "…"}}] }
```

Roles de fuente (`role`): `identity`, `names`, `calling_code`, `classification`, `flags`. `identity` y `names` son siempre obligatorios; los demás lo son si el contenido usa ese dato (algún `calling_code`, algún `region_id`, alguna bandera). Cada bandera referencia por `source` el `role` que declara su licencia. El JSON Schema (estructura y tipos) se publica en `contracts/` con un ejemplo sellado; la copia empaquetada debe ser equivalente.

## Incorporación (CLI `python -m gi_common_reference.countries.interfaces.cli incorporate <archivo>` y `diff <archivo>`)

Una transacción con los locks de D15. Ante el primer paso que falla se informan todas sus violaciones, rollback y salida 1 (RF-24). Salida 0 incorporado o no-op; 2 error operativo.

1. Schema (lector) y digest de contenido (RF-27).
2. Clasificación contra el historial: A no-op (RF-23, RF-25), B/C rechazo, D continúa; sin historial, D.
3. Contexto: hay una versión vigente de Locale; cada `locale_id` obligatorio existe, es `active` y su código coincide con la política (RF-35, RF-36); `region_snapshot_version` declarada está incorporada y es ≤ la vigente (RF-47).
4. Identidad y completitud: `country_id` UUID, sin repetir; ningún país, nombre ni bandera publicado ausente (RF-21); ids nuevos nunca usados (RF-45).
5. Códigos: formato (RF-5); cambio de tripleta sin recodificación declarada rechazado (RF-4, RF-42); cada recodificación es de un país publicado con tripleta anterior = vigente, tripleta nueva = la del snapshot, provenance y al menos un código distinto (RF-41, RF-42); un código vigente o histórico de **otro** id exige reasignación declarada y una reasignación que no corresponde se rechaza (RF-43); RF-3 sobre el estado final (RF-44).
6. Ciclo de vida: `status` válido; reemplazos (0..N) solo en `inactive`, sin duplicados, existentes, ninguno a sí mismo y sin ciclos en el grafo (RF-40, RF-52); `calling_code` con formato (RF-5).
7. Clasificación: `region_id`/`subregion_id` existentes en Regions vigente, `subregion_id` solo con `region_id`, par coherente, `active` solo con clasificación `active` (RF-6, RF-48).
8. Localizaciones: país y `locale_id` existentes; a lo sumo una por par; `name`/`official_name` sin vacío ni espacios en los bordes; nombre **nuevo** con locale `inactive` rechazado, los publicados se conservan; cada país tiene `name` en cada locale obligatorio (RF-31–RF-36).
9. Procedencia: fuentes con todos sus campos, roles requeridos presentes, `unresolved_conflicts` vacío (RF-28, RF-29).
10. Banderas: cada país `active` tiene bandera o excepción con motivo, no ambas (RF-19); para cada bandera, el `FlagStore` entrega el asset, la suma coincide, el contenido pasa D12 (RF-49).
11. Escritura, en este orden: `country_snapshot` (con versiones de Locale, de Regions declarada y vigente, y de la política) → países nuevos → países actualizados → recodificaciones → nombres nuevos → nombres actualizados → banderas → `SET CONSTRAINTS ALL IMMEDIATE` (D17) → commit. Una recodificación solo toca códigos y `codes_snapshot_version` (RF-41).

`diff`: lee el estado vigente y calcula el plan (pasos 1–9) sin escribir ni tomar el lock exclusivo; imprime altas, cambios de atributos, códigos, clasificación, nombres, estado y bandera, y las violaciones si las hay (RF-30).

## API pública (read-only, D13)

| Endpoint | Respuesta | Cubre |
|---|---|---|
| `GET /v1/countries?status=&region_id=&subregion_id=&locale_id=` | 200 lista ordenada por (`alpha2` `COLLATE "C"`, `country_id`); por defecto solo `active` | RF-13, RF-38 |
| `GET /v1/countries/by-alpha2/{code}?locale_id=` | `^[A-Za-z]{2}$` o 422; 200 según D6 · 404 | RF-9, RF-10 |
| `GET /v1/countries/by-alpha3/{code}?locale_id=` | `^[A-Za-z]{3}$` o 422; 200 según D6 · 404 | RF-9, RF-10 |
| `GET /v1/countries/by-numeric/{code}?locale_id=` | `^[0-9]{3}$` o 422; 200 según D6 · 404 | RF-9, RF-10 |
| `GET /v1/countries/{country_id}?locale_id=` | 200 con `status` (activo o inactivo) · 404 (id mal formado también es 404, como 002) | RF-8, RF-14 |
| `GET /v1/countries/{country_id}/flag` | 200 `image/svg+xml` con `ETag` = suma; 404 `country_not_found` o `flag_not_declared`; 500 `flag_integrity_error` si el archivo no coincide | RF-50 |
| Otros métodos | 405 | RF-18 |

- Las rutas `by-*` se declaran antes que `{country_id}` y `{country_id}/flag`; una prueba cubre el solapamiento (`/by-alpha2/flag`, `/by-numeric/na`).
- Forma: `{snapshot_version, data}` o `{snapshot_version, error}`; `snapshot_version` es la versión vigente de Countries y `null` con catálogo vacío; nunca 500 por catálogo vacío (RF-16).
- `Country` = `{country_id, alpha2, alpha3, numeric_code, status, replacement_country_ids, region_id, subregion_id, calling_code, name, official_name}`. `name` y `official_name` son los del `locale_id` pedido, o `null` si no se pidió locale o no hay traducción: sin fallback (RF-38). No se devuelven nombres ni códigos de región: el consumidor resuelve `region_id` por el contrato de Regions.
- `locale_id` mal formado o inexistente → 422 (`invalid_locale_id`, `unknown_locale`), distinto de 404. `status`, `region_id` y `subregion_id` inválidos → 422.
- Los códigos de error son los de D19; ninguna respuesta lleva mensajes localizados.

## Estrategia de pruebas (TDD por requisito)

- **Sin red** en todas las suites (RNF-8), como 001 y 002: `pytest-socket` y el guard de red en CLI y API.
- **Unit, dominio puro:** formato de códigos y casos borde (`NA`, `004`, `4`, `na`, `" AR"`, `AR1`, `calling_code` con `+`); digest y paridad con los vectores de 001; clasificación A–D; cada regla de los pasos 3–10 con los casos borde de la spec (recodificación TP→TL, cambio parcial no declarado, recodificación sin provenance o con tripleta incorrecta, intercambio de códigos declarado y no declarado, código histórico reutilizado con y sin declaración, división, fusión con reemplazo, reemplazo inválido o en ciclo, `active` con clasificación `inactive`, par región/subregión incoherente, nombre faltante en locale obligatorio, locale `inactive` nuevo y heredado, bandera o excepción faltante, SVG con script/`href` externo/DTD); plan de cambios y diff.
- **Unit, aplicación e interfaces:** incorporación con repositorio y `FlagStore` en memoria (no-op, rechazo sin escrituras, orden de escritura); consultas con lector en memoria; CLI (códigos de salida, `diff` sin escrituras, sin credenciales en la salida).
- **Integración (Postgres en testcontainers):**
  - SQL directo contra cada constraint y trigger de 0003 (RNF-5), incluidos `NULL`, formatos, `NA` y ceros iniciales, unicidad `active` diferida con intercambio de códigos, FK compuesta de clasificación, `DELETE`/`TRUNCATE`, privilegios y allowlist de columnas sin `tenant_id` ni textos en `country`.
  - **Integración con 002:** la reclasificación de una Subregion que dejaría incoherente a un Country es rechazada por la incorporación de Regions (salida 1, RF-35 de 002) y aceptada si la misma transacción corrige al Country; Countries no impide cambios no relacionados de Regions.
  - Incorporación de punta a punta: primer snapshot con versiones de Locale, Regions y política registradas; reenvío no-op; rechazo con dump idéntico; recodificación trazada que conserva `country_id`, `status` y nombres; división/fusión; mismo estado lógico en dos bases (RNF-1); `upgrade`/`downgrade` de 0003 sin tocar 0001 ni 0002.
- **Contrato:** API con datos incorporados (todos los endpoints, 404 vs 422, `na`/`NA`, `004`, sin fallback, bandera 200/404/500, 405, catálogo vacío, `reference_reader`); OpenAPI generado = `contracts/countries-api.v1.openapi.json`; los OpenAPI de Locale y Regions no cambian; ejemplo de snapshot válido contra el schema y con digest correcto; schema publicado = empaquetado; el wheel instalado trae schema, política y el directorio de assets; check `architecture` de AI-NATIVE y pruebas de frontera extendidas a `countries` (no importa `locales`/`regions`/Currency y nadie lo importa salvo la raíz de composición) (CA-19).
- **Datos de prueba:** fixtures sintéticos y deterministas (`tests/fixtures/countries.py`, `tests/fixtures/flags/`), marcados como no productivos (S-7). Incluyen AR, NA, AQ, TW, US/CA/PR (calling code `1`), BV, TL (recodificación desde TP), CW/SX/BQ (división desde AN) y un `inactive`.

## Cobertura de requisitos

| Requisito | Dónde |
|---|---|
| RF-1, RF-34, CA-1 | Datos, allowlist de columnas |
| RF-2, RF-45 | D1, paso 4, triggers de identidad |
| RF-3, RF-4, RF-5, RF-44 | D4, D7, pasos 1 y 5 |
| RF-6, RF-48 | D5, D20, paso 7, integración con 002 |
| RF-7, RF-21 | Triggers sin `DELETE`, paso 4 |
| RF-8–RF-15 (incl. RF-11 "no encontrado" y RF-12 validación, D19) | API, D6, D13, D14 |
| RF-16, RF-17, RF-18 | API, `country_snapshot`, versionado de contrato, sin escritura |
| RF-19, RF-49, RF-50 | D11, D12, paso 10, endpoint de bandera |
| RF-20, RF-22–RF-25, RF-27 | D2, pasos 1–2 y 11, D15, D17, rollback |
| RF-26, RNF-8 | Sin red en runtime ni en pruebas |
| RF-28, RF-29 | Paso 9, formato del snapshot |
| RF-30 | D18, `diff` |
| RF-31–RF-33, RF-35–RF-38 (incl. RF-32 recorte por CHECK, D9, y RF-37 solo textos persistidos) | D9, D10, paso 8, API |
| RF-39, RF-40, RF-52 | D8, D21, paso 6 |
| RF-41–RF-43, RF-46 | D7, paso 5, `country_recoding` |
| RF-47, RF-51 | `country_snapshot` (versiones declarada, vigente y de política), columnas de versión de `country`, paso 3 |
| RNF-1 | Orden determinístico, prueba en dos bases |
| RNF-2 | `country_snapshot`, inmutabilidad |
| RNF-3, RNF-4 | Privilegios, sin RLS por tenant |
| RNF-5 | Datos, pruebas SQL directas |
| RNF-6, RNF-7 | D13, D14, privilegios, `architecture.json`, sin imports ni FKs hacia Currency |
| RNF-9 | D19 |
| RNF-10 | Tablas y contratos nuevos, aditivos |

## Riesgos

- **Política con ids de gi-dev (D10):** si otro entorno publica `en`/`es` con otros ids, la incorporación se rechaza en el paso 3 con mensaje explícito; cambiarla requiere decisión explícita (RF-35).
- **Assets de bandera:** el repositorio solo contiene fixtures; los ~249 SVG reales y su licencia llegan con el dataset de PREP (S-7). Hasta entonces `countries/assets/flags/` está vacío y no existe snapshot productivo.
- **Reclasificaciones de Regions (S-8):** una reclasificación de 002 que afecta a un Country exige incorporación conjunta; el mecanismo es del pipeline. Countries solo garantiza la FK y que su snapshot pueda corregir el par.
- **Solapamiento de rutas** `by-*` / `{country_id}` (D13): cubierto por prueba.
- **Constraint triggers y FK diferidas:** su costo crece con las filas modificadas; el catálogo ISO tiene ~250 filas.

## Rollout y rollback

- **Rollout:** roles ya existentes (001) → `alembic upgrade head` (0003) → desplegar la API (misma URL de `reference_reader`) con el paquete que trae los assets → incorporar el snapshot de Regions requerido → incorporar el primer snapshot de PREP con `reference_loader` y la CLI de `countries`. Comandos y SQL en `docs/operacion.md`.
- **Rollback:** antes del primer consumidor, `alembic downgrade 0002` borra solo lo de 0003. Después no hay rollback de datos: se corrige hacia adelante con un snapshot nuevo.

## Fuera de este plan

- Currency y CountryCurrency (004), región intermedia, diseño del pipeline de PREP y dataset inicial (S-7, S-8).
- Migración de consumidores a `country_id`.
