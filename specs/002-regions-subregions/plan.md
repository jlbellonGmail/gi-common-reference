# Plan 002 — Regions / Subregions

- **Estado:** draft (pendiente de aprobación humana en el gate final)
- **Spec:** [spec.md](spec.md) (draft; continuación pedida por el responsable el 2026-10-27)
- **Perfil:** `python-service`; sigue la estructura que fijó [001-locales](../001-locales/plan.md)

## Precondición (verificada 2026-10-27, PASS)

`develop` (`fb5dc2d`) contiene 001 aprobada e implementada. Lo que 002 toma de ahí, sin cambiarlo:

- `locale_id` = UUID estable asignado por PREP (D4 de 001); tabla `reference.locale` con FK posible y sin `DELETE` (trigger).
- `status` = `active` | `inactive`, misma semántica; el reemplazo es información aparte (S-10, S-11 de 001).
- RF-23–RF-25 de 001: textos en `<Entidad>Locale` con FK a `locale_id` y a lo sumo una fila por par.
- Un locale `inactive` sigue resoluble y no se recomienda para nuevas referencias.
- Snapshots: `snapshot_version` entera positiva con saltos (D5), digest SHA-256 del JSON canónico sin `content_digest` (D7), clasificación A/B/C/D contra el historial, incorporación atómica con lock (D12) e historial inmutable (D9, D13).

## Arquitectura y estrategia

Un módulo nuevo `regions`, hexagonal como `locales` (RNF-4, RNF-6):

```text
regions/interfaces (HTTP read-only, CLI de incorporación)
  → regions/application (consultas, incorporación)
     → regions/domain (modelo, códigos M49, digest, admisión, validación del catálogo, puertos)
        ← regions/infrastructure (Postgres, lector de snapshot, política de locales obligatorios)
```

- Toda la validación de un snapshot es una función **pura** del dominio: `(snapshot, estado vigente, vista de Locale, política) → plan de cambios | violaciones`. La base repite las invariantes como constraints y triggers (RNF-3).
- `regions` no importa código de `locales` (ni al revés): la dependencia hacia Locale es solo de datos, por FK a `reference.locale` y por lectura SQL de `reference.locale`/`reference.locale_snapshot` en el mismo schema que posee este repositorio (RF-10, RF-28, RF-33, RF-38).
- `bootstrap.py` sigue siendo la única raíz de composición y pasa a cablear también `regions`. `app.py` compone una sola aplicación ASGI con las dos APIs sin cambiar el contrato de Locale.

## Decisiones

| # | Decisión | Alternativa descartada y motivo | Cubre |
|---|---|---|---|
| D1 | `region_id`/`subregion_id` = UUID asignado por PREP en la primera publicación y arrastrado en cada snapshot, como `locale_id` (S-4) | UUIDv5 del código M49: el id dependería del código y una recodificación lo rompería (RF-2) | RF-2, RF-23 |
| D2 | Los ids de Region y de Subregion son disjuntos: un snapshot que use el mismo UUID en ambos tipos se rechaza (RF-23) | Permitir solapamiento: «reemplazo de otro tipo» (RF-27) sería ambiguo | RF-23, RF-27 |
| D3 | Snapshot = un único documento JSON, catálogo completo (no delta) con regiones, subregiones, nombres, y las declaraciones de **este** snapshot: `recodings` y `code_reassignments` (listas, posiblemente vacías). Mismas reglas de digest que 001 (D7) | Un archivo por entidad: identidad atómica más difícil. Delta: no permite detectar omisiones (RF-22) | RF-21, RF-22, RF-39, RF-41 |
| D4 | Contrato público = API HTTP read-only versionada `/v1/regions` y `/v1/subregions` (FastAPI), OpenAPI propio en `contracts/regions-api.v1.openapi.json` | Agregar las rutas al OpenAPI de Locale: cambiaría `contracts/locales-api.v1.openapi.json`, contrato ya publicado | RF-14–RF-20, RNF-4 |
| D5 | `app.py` despacha por prefijo a dos aplicaciones FastAPI: `/v1/regions*`, `/v1/subregions*` y `/v1/openapi/regions.json` → Regions; el resto → Locale, intacta | Montar sub-apps de Starlette: cambia paths y root_path. Dos procesos: duplica la operación | D4, RNF-4 |
| D6 | Código M49 = texto `^[0-9]{3}$`, opcional. Unicidad entre `active` del mismo tipo con `EXCLUDE ... WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED`; disjunción Region/Subregion `active` con constraint triggers diferidos. Todo se evalúa al commit (estado final, RF-42) | Índices únicos parciales: no son diferibles y un intercambio de códigos fallaría a mitad | RF-3, RF-4, RF-42 |
| D7 | `code_snapshot_version` por entidad: snapshot en que obtuvo su código vigente. Búsqueda por código: la `active` que lo tiene; si no, la `inactive` con mayor `code_snapshot_version` (desempate por id) | Buscar en el historial de artefactos: costo por request | RF-17 |
| D8 | Subregion con `UNIQUE (region_id, subregion_id)` para que otros catálogos usen una FK compuesta `(region_id, subregion_id) REFERENCES reference.subregion (region_id, subregion_id) DEFERRABLE INITIALLY DEFERRED`. Una reclasificación que deja un dependiente incoherente falla al commit salvo que la misma transacción lo corrija | Trigger propio de coherencia: duplica lo que una FK compuesta ya garantiza | RF-29, RF-30, RF-35 |
| D9 | Conjunto obligatorio de locales = archivo versionado y empaquetado `required-locales.v1.json` (`policy_version` 1, `locale_id` de `en` y `es`, con el código solo como guarda). Los `locale_id` son la identidad publicada en gi-dev (`acceptance/locales/gi-dev`), que PREP debe reutilizar | Tabla sembrada por migración: la FK a `reference.locale` no existe al migrar. Códigos de texto en la política: S-7 exige `locale_id` | RF-31, RF-13, S-7 |
| D10 | Historial: `region_snapshot` (artefacto completo, versión de Locale usada y versión de política) y trazas `subregion_reclassification`, `region_recoding`, `subregion_recoding`, inmutables. «Consultable» = tablas legibles por `reference_reader` y SQL documentado en `docs/operacion.md` | Endpoints HTTP de trazas: más contrato público sin un consumidor que lo pida; agregarlos después es aditivo | RF-34, RF-38, RF-39, RNF-5 |
| D11 | Lock propio `gi-common-reference.regions.incorporation` (exclusivo) + lock **compartido** sobre el de Locale durante la incorporación: Locale no cambia mientras se valida contra él | Sin lock compartido: un locale podría pasar a `inactive` entre la validación y el commit | RF-25, RF-33, RF-38 |
| D12 | `regions` replica los helpers chicos de `locales` que necesita (JSON canónico, `describe_error`, validación de conninfo); una prueba compara el JSON canónico con los vectores de 001 | Kernel compartido: obliga a reestructurar 001 y sus pruebas de frontera | RNF-6, D3 |
| D13 | Una violación de constraint detectada al forzar `SET CONSTRAINTS ALL IMMEDIATE` antes del commit es un **rechazo** (salida 1) con la constraint nombrada; las FK violadas se informan como RF-35 | Tratarla como error operativo (salida 2): un snapshot incoherente con otro catálogo no es una falla del entorno | RF-25, RF-35 |

## Archivos probables

```text
architecture.json                       # capas con rutas de locales y regions; módulo regions público en interfaces/http
contracts/region-snapshot.v1.schema.json, region-snapshot.v1.example.json
contracts/regions-api.v1.openapi.json
migrations/versions/0002_regions.py
src/gi_common_reference/
  app.py, bootstrap.py                  # composición de ambas APIs y adaptadores
  regions/domain/{model,codes,digest,snapshot,catalog,policy,ports,errors}.py
  regions/application/{incorporate,queries}.py
  regions/infrastructure/{postgres_repository,postgres_reader,snapshot_reader,policy_reader,conninfo}.py
  regions/infrastructure/{region-snapshot.v1.schema.json,required-locales.v1.json}
  regions/interfaces/{http,cli}.py
tests/{unit,integration,contract}/…regions…, tests/fixtures/regions.py
docs/operacion.md, docs/desarrollo.md, README.md
```

## Datos (schema `reference`, migración 0002)

Todas las columnas son `NOT NULL` salvo `code`, `code_snapshot_version` y los reemplazos. Ninguna `tenant_id` ni texto en Region/Subregion (RF-1, RF-8). Ninguna FK hacia Country, Currency ni consumidores (RNF-6).

- **`region_snapshot`:** `snapshot_version bigint PK CHECK > 0`, `content_digest`, `locale_snapshot_version bigint REFERENCES locale_snapshot` (RF-38), `required_locales_version integer`, `provenance jsonb`, `artifact jsonb`, `incorporated_at`. Sin `UPDATE`/`DELETE`/`TRUNCATE` (RNF-5).
- **`region`:** `region_id uuid PK`, `code text CHECK (code ~ '^[0-9]{3}$')`, `code_snapshot_version bigint REFERENCES region_snapshot`, `status CHECK IN ('active','inactive')`, `replacement_region_id uuid REFERENCES region DEFERRABLE INITIALLY DEFERRED`, `first_snapshot_version bigint REFERENCES region_snapshot`.
  - CHECKs: `(code IS NULL) = (code_snapshot_version IS NULL)`; reemplazo distinto de sí mismo; reemplazo solo si `inactive` (RF-7, RF-27).
  - `EXCLUDE USING btree (code WITH =) WHERE (status = 'active') DEFERRABLE INITIALLY DEFERRED` (RF-3).
- **`subregion`:** igual que `region` con `subregion_id`, `replacement_subregion_id` y `region_id uuid REFERENCES region` (RF-5), más `UNIQUE (region_id, subregion_id)` (D8).
- **Constraint triggers diferidos** (releen la fila al commit): ningún código `active` compartido entre Region y Subregion (RF-4); ninguna Subregion `active` en una Region `inactive` (RF-36).
- **`region_locale` / `subregion_locale`:** PK (`region_id`|`subregion_id`, `locale_id`), FK a la entidad y a `reference.locale`, `name text CHECK (name <> '' AND name !~ '^\s' AND name !~ '\s$')` (RF-9–RF-12).
- **Trazas:** `subregion_reclassification` (PK `subregion_id, snapshot_version`; `previous_region_id`, `new_region_id`) (RF-34); `region_recoding` y `subregion_recoding` (PK `id, snapshot_version`; `previous_code`, `new_code`, `provenance jsonb`) (RF-39). Inmutables.
- **Triggers:** sin `DELETE` ni `TRUNCATE` en `region`, `subregion` y nombres (RF-22, RF-30); ids, `first_snapshot_version` y los pares (entidad, locale) inmutables. Son mutables solo `code`, `code_snapshot_version`, `status`, reemplazo, `region_id` de Subregion y `name`.
- **Privilegios** (D10 de 001): `reference_reader` solo `SELECT`; `reference_loader` `SELECT`, `INSERT` y `UPDATE` de las columnas mutables. Nada para `PUBLIC`, `anon`, `authenticated`. Condicionales a que los roles existan, como 0001.
- La versión vigente es `max(region_snapshot.snapshot_version)`, independiente de Locale y de Countries (RF-37).

## Formato del snapshot (contrato con PREP)

```json
{ "snapshot_version": 1, "content_digest": "sha256:…", "provenance": {"source": "UN M49", …},
  "regions":    [{"region_id": "uuid", "code": "019", "status": "active", "replacement_region_id": null}],
  "subregions": [{"subregion_id": "uuid", "region_id": "uuid", "code": "419", "status": "active", "replacement_subregion_id": null}],
  "region_names":    [{"region_id": "uuid", "locale_id": "uuid", "name": "Americas"}],
  "subregion_names": [{"subregion_id": "uuid", "locale_id": "uuid", "name": "Latin America and the Caribbean"}],
  "recodings":          [{"entity_type": "subregion", "entity_id": "uuid", "previous_code": "123", "new_code": "456", "provenance": {"source": "…"}}],
  "code_reassignments": [{"entity_type": "subregion", "entity_id": "uuid", "code": "456", "provenance": {"source": "…"}}] }
```

El JSON Schema (estructura y tipos) se publica en `contracts/` con un ejemplo sellado; la copia empaquetada debe ser equivalente.

## Incorporación (CLI `python -m gi_common_reference.regions.interfaces.cli incorporate <archivo>`)

Una transacción con los locks de D11. Ante el primer paso que falla se informan todas sus violaciones, rollback y salida 1 (RF-25). Salida 0 incorporado o no-op; 2 error operativo.

1. Schema (lector) y digest de contenido.
2. Clasificación contra el historial: A no-op (RF-26), B/C rechazo, D continúa; sin historial, D.
3. Contexto de Locale: hay una versión vigente de Locale; cada `locale_id` obligatorio existe, es `active` y su código coincide con la política (RF-31, RF-33).
4. Identidad y completitud: ids UUID, sin repetir, disjuntos entre tipos (D2); toda Region, Subregion y nombre publicado sigue presente (RF-22); ids nuevos nunca usados (RF-23).
5. Códigos: formato (RF-3); un cambio de código vigente sin recodificación declarada se rechaza (RF-22); cada recodificación es de un id publicado, con `previous_code` = código vigente y `new_code` = código del snapshot (RF-39, RF-40); un código vigente o histórico de **otro** id exige una reasignación declarada y una reasignación que no corresponde se rechaza (RF-41); RF-3 y RF-4 sobre el estado final (RF-42).
6. Jerarquía y ciclo de vida: `region_id` de cada Subregion existe en el snapshot (RF-5); `status` válido (RF-7); reemplazo solo en `inactive`, del mismo tipo, existente, no a sí mismo y sin ciclos (RF-27); ninguna Subregion `active` en Region `inactive` (RF-36).
7. Localizaciones: entidad y `locale_id` existentes (RF-10, RF-28); a lo sumo una por par (RF-9); `name` sin vacío ni espacios en los bordes (RF-11); una localización **nueva** con locale `inactive` se rechaza, las publicadas se conservan (RF-33); cada entidad tiene nombre en cada locale obligatorio (RF-13, RF-32).
8. Escritura, en este orden: `region_snapshot` (con la versión vigente de Locale y de la política) → regiones nuevas → regiones actualizadas → subregiones nuevas → subregiones actualizadas → reclasificaciones (RF-6, RF-34) → recodificaciones (RF-39) → nombres nuevos → nombres actualizados → `SET CONSTRAINTS ALL IMMEDIATE` (D13) → commit. Una recodificación solo toca `code`/`code_snapshot_version` (RF-24).

## API pública (read-only, D4)

| Endpoint | Respuesta | Cubre |
|---|---|---|
| `GET /v1/regions?status=&locale_id=` | 200 lista ordenada por (`code` NULLS LAST, id) | RF-14, RF-18 |
| `GET /v1/regions/{region_id}?locale_id=` | 200 · 404 (id mal formado también es 404, como 001) | RF-16 |
| `GET /v1/regions/by-code/{code}?locale_id=` | `^[0-9]{3}$` o 422; 200 según D7 · 404 | RF-17 |
| `GET /v1/subregions?region_id=&status=&locale_id=` | 200 lista; `region_id` mal formado 422 | RF-15 |
| `GET /v1/subregions/{subregion_id}`, `/v1/subregions/by-code/{code}` | como Region, con `region_id` | RF-16, RF-17 |
| Otros métodos | 405 | RF-20 |

- Forma: `{snapshot_version, data}` o `{snapshot_version, error}`; `snapshot_version` es la versión vigente de Regions (RF-20, RF-37) y `null` con catálogo vacío; nunca 500 por catálogo vacío.
- `Region` = `{region_id, code, status, replacement_region_id, name}`; `Subregion` agrega `region_id`. `name` es el nombre en `locale_id`, o `null` si no se pidió locale o no hay traducción: sin fallback (RF-18).
- `locale_id` mal formado o inexistente en Locale → 422 (`invalid_locale_id`, `unknown_locale`), distinto de 404 (RF-19). `status` inválido → 422.

## Estrategia de pruebas (TDD por requisito)

- **Sin red** en todas las suites (RNF-2), como 001: `pytest-socket` y el guard de red en CLI y API.
- **Unit, dominio puro:** formato de código y casos borde (`19`, `0019`, `019`); digest y paridad con los vectores de 001; clasificación A–D; cada regla de los pasos 3–7 con los casos borde de la spec (reclasificación, división, fusión, recodificación, intercambio de códigos, código histórico reutilizado, reemplazo inválido o en ciclo, Region `inactive` con Subregion `active`, nombre faltante en locale obligatorio, locale `inactive` nuevo y heredado); plan de cambios.
- **Unit, aplicación e interfaces:** incorporación con repositorio en memoria (no-op, rechazo sin escrituras, orden de escritura); consultas con lector en memoria; CLI (códigos de salida, sin credenciales en la salida).
- **Integración (Postgres en testcontainers):**
  - SQL directo contra cada constraint y trigger de 0002 (RNF-3), incluidos `NULL`, RF-3/RF-4 diferidos con intercambio de códigos en una transacción, RF-36, `TRUNCATE`, privilegios y allowlist de columnas sin `tenant_id` ni textos (CA-1).
  - **RF-29/RF-35:** tabla de prueba con FK compuesta: par incoherente rechazado; reclasificación rechazada por la incorporación (salida 1, RF-35) y aceptada si la misma transacción corrige al dependiente.
  - Incorporación de punta a punta: primer snapshot, idempotencia, rechazo atómico con dump idéntico, reclasificación y recodificación trazadas, versión de Locale registrada, determinismo en dos bases (RNF-1), `upgrade`/`downgrade`.
- **Contrato:** API con datos incorporados (todos los endpoints, 404 vs 422, sin fallback, 405, catálogo vacío, `reference_reader`); OpenAPI generado = `contracts/regions-api.v1.openapi.json`; el OpenAPI de Locale no cambia; ejemplo de snapshot válido contra el schema y con digest correcto; schema publicado = empaquetado; check `architecture` de AI-NATIVE y pruebas de frontera extendidas a `regions` (no importa `locales`, ni Country/Currency) (CA-8).

## Cobertura de requisitos

| Requisito | Dónde |
|---|---|
| RF-1, RF-8, RF-12, CA-1 | Datos, allowlist de columnas |
| RF-2, RF-23 | D1, D2, paso 4, triggers de identidad |
| RF-3, RF-4, RF-42 | D6, paso 5 |
| RF-5, RF-6, RF-34 | Datos, pasos 6 y 8, `subregion_reclassification` |
| RF-7, RF-27, RF-36 | Datos, paso 6, constraint triggers |
| RF-9–RF-11, RF-13, RF-28, RF-31–RF-33 | D9, Datos, pasos 3 y 7 |
| RF-14–RF-20 | API, D4, D5, D7 |
| RF-21, RF-22, RF-24–RF-26 | D3, pasos 1–2 y 4–5, D11, D13, rollback |
| RF-29, RF-30, RF-35 | D8, D13, triggers sin `DELETE` |
| RF-37, RF-38 | `region_snapshot`, API |
| RF-39–RF-41 | D3, paso 5, trazas de recodificación |
| RNF-1 | Orden determinístico, prueba en dos bases |
| RNF-2 | Sin red en runtime ni en pruebas |
| RNF-3 | Datos, pruebas SQL directas |
| RNF-4 | D4, D5, privilegios, `architecture.json` |
| RNF-5 | D10, inmutabilidad |
| RNF-6 | Sin imports ni FKs hacia Country/Currency; `regions` solo depende de datos de Locale |
| RNF-7 | Región intermedia futura: tabla y contrato nuevos, aditivos; no cambia ids ni endpoints existentes |

## Riesgos

- **Política con ids de gi-dev (D9):** si otro entorno publica `en`/`es` con otros ids, la incorporación se rechaza en el paso 3 con mensaje explícito; cambiar la política es una decisión explícita (RF-31).
- **Constraint triggers diferidos:** su costo crece con las filas modificadas; el catálogo M49 tiene decenas de filas.
- **Región intermedia M49:** fuera de alcance (spec); RNF-7 la deja como cambio aditivo.

## Rollout y rollback

- **Rollout:** roles ya existentes (001) → `alembic upgrade head` (0002) → desplegar la API (misma URL de `reference_reader`) → incorporar el primer snapshot de PREP con `reference_loader` y la CLI de `regions`. Comandos y SQL en `docs/operacion.md`.
- **Rollback:** antes del primer consumidor, `alembic downgrade 0001` borra solo lo de 0002. Después no hay rollback de datos: se corrige hacia adelante con un snapshot nuevo.

## Fuera de este plan

- Región intermedia, Countries (003) y Currency (004).
- Diseño del pipeline de PREP y dataset inicial.
