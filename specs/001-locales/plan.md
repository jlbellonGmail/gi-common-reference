# Plan 001 — Locales

- **Estado:** approved
- **Spec:** [spec.md](spec.md) (approved)
- **Perfil:** `python-service` (repositorio sin código previo: este plan define la estructura inicial)
- **Enmiendas:** `sdd-change` 2026-10-20 — D13, paso 4 de la incorporación (RF-33), Datos (triggers `TRUNCATE`), pruebas, cobertura, Riesgos y Rollout (los roles se crean antes de migrar); revisión final 2026-10-20 (raíz de composición, `bootstrap.py`)

## Terminología (cierra hallazgo LOW-3)

- **Registro IANA:** el estándar y su versión, identificada por `File-Date`. Solo se usa para hablar de versiones (RF-29, S-18).
- **Artefacto IANA de referencia:** el contenido incluido en el snapshot (`iana.registry_text`, copia literal del archivo publicado para una versión del registro IANA). Es lo único que `gi-common-reference` lee, parsea y usa para validar y derivar alias (RF-8, RF-26, RF-30).

## Arquitectura y estrategia

Hexagonal, un solo módulo `locales` (RNF-4, RNF-6):

```text
interfaces (HTTP read-only, CLI de incorporación)
   → application (consultas, incorporación)
      → domain (modelo, reglas de código, parser del artefacto IANA, validación de snapshot, puertos)
         ← infrastructure (Postgres, lector de snapshot)
```

- Toda la validación de un snapshot es una función **pura** del dominio: `(snapshot, estado vigente, historial) → clasificación | lista de violaciones`. Se prueba sin base de datos.
- La base de datos repite las invariantes estructurales como constraints y triggers, como red de seguridad (RNF-3).
- La incorporación es un único comando operativo (CLI), no un endpoint. La API solo lee (RF-12).
- **Raíz de composición:** `src/gi_common_reference/bootstrap.py` es la raíz de composición. Es el único módulo fuera de `locales` que puede importar sus internos (los puertos del dominio y los adaptadores de infraestructura), porque su función es ensamblar la aplicación; `app.py` y la CLI reciben los adaptadores solo a través de ella. Esa excepción no amplía el contrato público: la superficie pública de `locales` sigue siendo `interfaces/http` (RNF-4) y ningún otro código externo puede importar sus internos. `architecture.json` no cambia: el check `architecture` de AI-NATIVE solo resuelve imports relativos y no puede expresar esta excepción, así que la frontera la controla explícitamente `tests/contract/test_composition_root.py`, que prohíbe los imports internos de cualquier otro módulo externo y fija la lista exacta de módulos que la raíz puede importar.

## Decisiones

| # | Decisión | Alternativa descartada y motivo | Cubre |
|---|---|---|---|
| D1 | Contrato público = API HTTP read-only versionada `/v1/locales` (FastAPI), con OpenAPI publicado en `contracts/` | Librería Python in-process: acopla consumidores a Python y a la versión del paquete. Vistas SQL en la base compartida: acopla a persistencia (RNF-4) | RF-7–RF-13, RNF-4 |
| D2 | psycopg 3 con SQL explícito | ORM (SQLAlchemy): capa extra para tres tablas | RF-14, RNF-3 |
| D3 | Migraciones con Alembic usando `op.execute` (SQL plano), en el schema propio `reference` | Supabase CLI: ata los tests a tooling de Supabase. Runner propio: herramienta a mantener | RNF-3, RNF-5 |
| D4 | `locale_id` = UUID generado por PREP en la primera publicación y arrastrado en cada snapshot; aquí solo se valida el formato | UUIDv5 derivado del código: el id dependería del texto del código (RF-2). Entero secuencial: exige coordinar contadores en PREP | RF-2, RF-17, S-16 |
| D5 | `snapshot_version` = entero positivo; orden numérico; se admiten saltos | SemVer o fechas: parseo y comparación más complejos sin semántica que lo justifique | RF-32, S-20 |
| D6 | Snapshot = un único documento JSON con el artefacto IANA **literal** (`iana.registry_text`) | Artefacto IANA preparseado por PREP (entradas ya convertidas): no se puede contrastar con el archivo oficial. Varios archivos: la identidad atómica es más difícil | RF-30, RF-31, S-19 |
| D7 | Digests SHA-256. Contenido: JSON canónico (claves ordenadas, sin espacios, UTF-8, sin floats) del documento **sin** el campo `content_digest`. IANA: bytes UTF-8 de `registry_text` | Digest de los bytes del archivo: sensible al formato y autorreferente | RF-30, RF-31, S-21 |
| D8 | Alias *Preferred-Value* del artefacto vigente materializados al incorporar (`locale_alias`) | Parsear el artefacto en cada consulta: costo por request. Conservar alias históricos: RF-8 usa solo el snapshot vigente | RF-8, RNF-2 |
| D9 | Historial = tabla `locale_snapshot` con el artefacto completo (`jsonb`) y triggers que impiden `UPDATE`/`DELETE` | Object storage: otro sistema fuera del stack | RNF-5, RF-21, RF-32 |
| D10 | Dos roles de base: `reference_reader` (API, solo `SELECT`) y `reference_loader` (CLI). Sin grants a `anon`, `authenticated` ni `public` | Endpoint admin de carga: abre escritura pública (RF-12) | RF-12, RF-14, RNF-4 |
| D11 | Listado ordenado por `code` ascendente | Orden por `locale_id`: estable pero inútil para humanos | RF-11, RNF-1 |
| D12 | Concurrencia: `pg_advisory_xact_lock` durante la incorporación, en una sola transacción | Sin lock: dos incorporaciones podrían pasar la misma clasificación | RF-20, RF-32 |
| D13 | Triggers `BEFORE TRUNCATE FOR EACH STATEMENT` sobre `locale_snapshot` y `locale`, además de los triggers por fila. La migración 0001 se edita en su lugar: no hay despliegue ni snapshot incorporado | Confiar solo en no otorgar el privilegio `TRUNCATE`: no protege del dueño del schema ni de un rol mal configurado. Una migración 0002: complejidad sin beneficio mientras nada se haya desplegado | RNF-5, RNF-8 |

## Archivos probables

```text
pyproject.toml                      # python>=3.12; fastapi, uvicorn, psycopg[binary], alembic; dev: pytest, httpx, testcontainers[postgres], pytest-socket, ruff, mypy
architecture.json                   # capas y módulo locales (check AI-NATIVE `architecture`)
contracts/locale-snapshot.v1.schema.json   # contrato con PREP (JSON Schema + reglas de digest)
contracts/locales-api.v1.openapi.json      # OpenAPI generado y versionado
migrations/env.py, migrations/versions/0001_locales.py
src/gi_common_reference/
  app.py                            # FastAPI
  bootstrap.py                      # raíz de composición: cablea puertos con adaptadores
  locales/domain/{model,codes,iana,snapshot,ports}.py
  locales/application/{queries,incorporate}.py
  locales/infrastructure/{postgres_repository,snapshot_reader}.py
  locales/interfaces/{http,cli}.py
tests/{unit,integration,contract}/, tests/fixtures/
```

## Datos (schema `reference`, migración 0001)

Las PK implican `NOT NULL`. Todas las demás columnas son `NOT NULL` salvo `replacement_locale_id`.

- **`locale_snapshot`:** `snapshot_version bigint PK CHECK > 0`, `content_digest text NOT NULL`, `iana_file_date date NOT NULL`, `iana_digest text NOT NULL`, `provenance jsonb NOT NULL`, `artifact jsonb NOT NULL` (documento completo), `incorporated_at timestamptz NOT NULL DEFAULT now()` (metadata operacional, depende del entorno). Triggers que rechazan `UPDATE`/`DELETE` (por fila) y `TRUNCATE` (por sentencia). (RNF-5, RNF-8, RF-13)
- **`locale`:**
  - `locale_id uuid PK`
  - `code text NOT NULL UNIQUE CHECK (code ~ '^[a-z]{2,3}$')`
  - `status text NOT NULL CHECK IN ('active','inactive')`
  - `iana_deprecated boolean NOT NULL`
  - `replacement_locale_id uuid NULL REFERENCES locale DEFERRABLE INITIALLY DEFERRED` (diferida porque un `replacement` puede apuntar a un locale nuevo del mismo snapshot)
  - `first_snapshot_version bigint NOT NULL REFERENCES locale_snapshot` (no diferida: el orden de escritura del paso 10 la satisface)
  - `CHECK (replacement_locale_id <> locale_id)`
  - `CHECK (replacement_locale_id IS NULL OR iana_deprecated)`
  - `CHECK (NOT iana_deprecated OR status = 'inactive')`
  - Triggers: rechazan `DELETE`, `TRUNCATE` (por sentencia, porque `TRUNCATE` no dispara los triggers por fila) y cualquier cambio de `locale_id` o `code`.
  - Cubre RF-1, RF-2, RF-3, RF-5, RF-6, RF-15, RF-16, RF-22, RF-27, RNF-3 y RNF-8.
- **`locale_alias`:** `subtag text PK`, `preferred_value text NOT NULL`. Se reemplaza entero en cada incorporación con las entradas `Type: language` del artefacto IANA que tienen *Preferred-Value*. (RF-8) No lleva triggers de inmutabilidad: es un dato derivado del snapshot vigente, no historia.
- Ninguna columna `tenant_id`, `name` ni textos (RF-1, RF-6). Ninguna FK hacia otros catálogos (RNF-6).
- La versión vigente es `max(snapshot_version)`. El caso A no inserta filas, así que la versión vigente no retrocede (RF-13, RF-21).

## Formato del snapshot (contrato con PREP)

```json
{ "snapshot_version": 3, "content_digest": "sha256:…",
  "iana": { "file_date": "2026-09-01", "digest": "sha256:…", "provenance": {…}, "registry_text": "File-Date: 2026-09-01\n%%\n…" },
  "provenance": {…},
  "locales": [ { "locale_id": "uuid", "code": "he", "status": "active", "iana_deprecated": false, "replacement_locale_id": null } ] }
```

El JSON Schema y las reglas de canonicalización del digest se publican en `contracts/` con vectores de prueba para que PREP produzca digests idénticos.

## Incorporación (CLI `python -m gi_common_reference.locales.interfaces.cli incorporate <archivo>`)

Una transacción con lock (D12). Ante la primera violación de un paso, se reporta la lista de violaciones de ese paso, se hace rollback y la salida es distinta de cero (RF-20). El orden respeta la precedencia de la spec: RF-31, luego RF-32 y recién después RF-30, RF-29 y las demás reglas.

1. Leer el documento y validarlo contra el schema: campos obligatorios presentes (RF-31).
2. Recalcular el digest de contenido y compararlo con el declarado (RF-31). Es lo mínimo para identificar el snapshot.
3. Clasificar contra el historial (RF-32), antes de tocar el artefacto IANA:
   - A → no-op y salida 0 (RF-21);
   - B o C → rechazo;
   - D → continúa.
   - **Sin historial (primer snapshot) = caso D con cualquier `snapshot_version` válida** (cierra LOW-1).
4. Recalcular el digest IANA y compararlo con el declarado. Parsear el artefacto IANA (formato record-jar, RFC 5646 §3.1.1, incluidos rangos `qaa..qtz`). Exigir `Type`, `Subtag` y `File-Date` presentes, y `File-Date` del artefacto igual a `iana.file_date` (RF-30). `Deprecated` y `Preferred-Value` son opcionales por entrada, pero si están no pueden estar vacíos: un campo presente sin valor (también tras unir las líneas de continuación) hace el artefacto inválido, y se reporta como RF-30 (RF-33). Así `Deprecated` presente es la única definición de "deprecado" para todo el código. El artefacto se lee solo del snapshot, nunca de la red (RNF-2).
5. `File-Date` mayor o igual al del último snapshot incorporado; sin historial, cualquiera (RF-29).
6. Todos los códigos en minúsculas, sin normalizar (RF-28).
7. Diferencias contra el estado vigente:
   - ningún locale publicado falta (RF-15);
   - el mapeo id↔código se conserva (RF-16);
   - los ids nuevos son UUID, no se usaron antes y no se repiten (RF-17);
   - los códigos nuevos cumplen las reglas de publicación 1–6 contra el artefacto, sin duplicados (RF-4, RF-3).
8. Contra el artefacto, para cada locale (RF-26, RF-19):
   - su código está registrado como `language`;
   - `iana_deprecated` coincide con `Deprecated`;
   - `replacement_locale_id` es el id del locale cuyo código es el *Preferred-Value*, o `null` si no lo hay;
   - deprecado implica `inactive` (RF-27).
9. `replacement`: debe existir en el estado resultante, no apuntar a sí mismo y no formar ciclos (RF-22).
10. Escribir en la misma transacción, en este orden (RF-18, RF-14, RF-21):
    1. insertar la fila `locale_snapshot` con el artefacto, para que exista antes que la FK `first_snapshot_version`;
    2. insertar los locales nuevos con `first_snapshot_version` igual a esa versión;
    3. actualizar solo la metadata de los locales existentes;
    4. reemplazar `locale_alias`;
    5. commit.
    - Si cualquier paso falla, el rollback deshace toda la transacción, incluida la fila `locale_snapshot` (RF-20). Se descartó hacer diferida la FK `first_snapshot_version`: el orden anterior basta y no hay razón técnica para diferirla.

## API pública (read-only, D1)

| Endpoint | Respuesta | Cubre |
|---|---|---|
| `GET /v1/locales/{locale_id}` | 200 `{snapshot_version, data: Locale}` · 404 `{snapshot_version, error}` | RF-7, RF-13 |
| `GET /v1/locales/by-code/{code}` | Valida `^[A-Za-z]{2,3}$` (422 `{snapshot_version, error}` si no cumple), pasa a minúsculas, busca por código publicado; si no lo encuentra, busca en `locale_alias` y luego por el *Preferred-Value*. 200 `{snapshot_version, data: Locale}` · 404 `{snapshot_version, error}`, sin fallback | RF-8, RF-9, RF-10, RF-13 |
| `GET /v1/locales?status=active` | 200 `{snapshot_version, data: [Locale]}`, ordenada por `code` (`status` opcional) | RF-11, RF-13 |
| Otros métodos | 405 | RF-12 |

- **Forma única de respuesta:** `snapshot_version` (la vigente) va en todas las respuestas de los tres endpoints, incluidos 404 y 422.
- `Locale` = `{locale_id, code, status, iana_deprecated, replacement_locale_id}`.
- **Catálogo vacío:** `snapshot_version: null`, con `data: []` o 404 según el endpoint; nunca 500.

## Estrategia de pruebas (TDD por requisito)

- **Sin red en todas las suites (RNF-2, CA-16):**
  - `pytest-socket` está activo para unit, integración y contrato: `--disable-socket`, con `--allow-hosts` limitado a 127.0.0.1/localhost (host del Postgres de testcontainers) y `--allow-unix-socket` para el socket de Docker.
  - El contenedor se arranca en un fixture de sesión con socket habilitado solo para Docker.
  - Pruebas dedicadas: la CLI de incorporación y la API HTTP completan sus flujos con un guard que hace fallar cualquier `connect`/`getaddrinfo` a hosts que no sean el de Postgres. Así se verifica que el artefacto IANA se lee solo del snapshot.
- **Unit, dominio puro:**
  - reglas de código y casos borde de la spec (RF-3, RF-4, RF-9, RF-28);
  - parser del artefacto IANA;
  - digests con vectores fijos (RF-30, RF-31);
  - clasificación A–D, incluido el primer snapshot, y precedencia: un caso B con artefacto IANA inválido se rechaza como caso B, no por RF-30 (RF-32, RF-21);
  - validación contra el artefacto: deprecación, `replacement`, cadena A → B → C, `iw`/`he` (RF-15–RF-19, RF-22, RF-26, RF-27, RF-29);
  - campos opcionales del artefacto: `Deprecated:` y `Preferred-Value:` vacíos rechazan el snapshot por RF-30 (RF-33); con valor en una línea de continuación, ausentes o con valor, no; un caso B o C con un campo vacío sigue siendo B o C (RF-32).
  - Fixtures: un fixture de artefacto IANA sintético mínimo y un fixture de artefacto IANA real para el parser.
- **Integración, Postgres en testcontainers:**
  - **RNF-3:** inserts y updates SQL directos que violan cada constraint o trigger fallan, sin pasar por la aplicación. Incluye `NULL` en cada columna `NOT NULL` y un `locale` cuyo `first_snapshot_version` no existe.
  - **Paso 10:** la incorporación escribe primero `locale_snapshot`; si falla un paso posterior, la fila `locale_snapshot` tampoco queda (RF-20).
  - **RF-20:** un snapshot inválido deja el estado idéntico; se compara un dump antes y después.
  - **RF-21:** reincorporar N después de N+1 es un no-op.
  - **RNF-5:** el artefacto guardado recalcula el mismo digest, y `UPDATE`/`DELETE` sobre el historial fallan.
  - **RNF-8:** `TRUNCATE` sobre `locale_snapshot` y sobre `locale` falla (con y sin `CASCADE`, con tabla vacía y con datos); `pg_trigger` confirma un trigger `BEFORE TRUNCATE` por sentencia en cada una; `reference_loader` no tiene el privilegio; `locale_alias` sigue pudiendo vaciarse y reemplazarse.
  - **RNF-1:** no se comparan dumps físicos, porque `incorporated_at` es metadata operacional y difiere entre bases. Se incorpora el mismo snapshot en dos bases nuevas y se compara:
    - el estado lógico del catálogo (`locale` y `locale_alias` ordenados);
    - las filas de `locale_snapshot` sin `incorporated_at` ni otra metadata del entorno;
    - las respuestas de los tres endpoints.
    - Además, consultas repetidas devuelven lo mismo.
- **Contrato:**
  - API con `httpx`: respuestas, códigos de estado, 405 y `snapshot_version` presente en los tres endpoints, también con catálogo vacío (RF-7–RF-13);
  - el OpenAPI generado coincide con `contracts/locales-api.v1.openapi.json`;
  - un snapshot de ejemplo valida contra el JSON Schema.
- **Aislamiento, RNF-4:**
  - `has_schema_privilege` es falso para `anon`, `authenticated` y `public`;
  - `reference_reader` no puede escribir;
  - el check `architecture` de AI-NATIVE con `architecture.json`: el dominio no importa infraestructura ni frameworks, `locales` no importa otros catálogos (RNF-6) y los consumidores solo ven `interfaces/http`.
- **CA-18, RF-6, RF-1:** test con la allowlist de columnas de `locale` y de campos del DTO.

## Cobertura de requisitos

| Requisito | Dónde |
|---|---|
| RF-1, RF-6 | Datos, test de allowlist |
| RF-2, RF-3, RF-16, RF-17 | D4, Datos, Incorporación 7 |
| RF-4, RF-26, RF-27, RF-19 | Incorporación 7–8, CHECKs |
| RF-5, RF-18 | Datos, Incorporación 10 |
| RF-7–RF-13 | API (forma única con `snapshot_version`), D1, D8, D11 |
| RF-14, RF-20 | D10, D12, Incorporación (paso 10, rollback total) |
| RF-15, RF-22 | Incorporación 7 y 9, FK y triggers |
| RF-21, RF-32 | D5, D9, Incorporación 2–3 |
| RF-28, RF-29, RF-30, RF-31 | D6, D7, Incorporación 1–2 y 4–6 |
| RF-23, RF-24, RF-25 | Contrato para dependientes: sin implementación en 001 (CA-19); lo adoptan 002/003 |
| RNF-1 | D11, test de determinismo lógico (sin `incorporated_at`) |
| RNF-2 | D6, D8, `pytest-socket` en todas las suites, guard de red para CLI y API |
| RNF-3 | Datos (incluye `NOT NULL`), tests SQL directos |
| RNF-4 | D1, D10, tests de privilegios y `architecture.json` |
| RNF-5 | D9, tests de inmutabilidad |
| RNF-8 | D13, Datos (triggers `TRUNCATE`), tests SQL directos |
| RF-33 | Incorporación 4, tests de parser y de admisión, contrato para PREP |
| RNF-6 | Sin FKs ni imports hacia otros catálogos, `architecture.json` |
| RNF-7 | El CHECK de formato se relajará con una migración compatible si se amplía el subconjunto |

## Riesgos

- **Digest divergente entre PREP y este repositorio:** se mitiga con reglas de canonicalización y vectores de prueba en `contracts/`.
- **Supabase expone schemas por PostgREST:** hay que verificar que `reference` no figure en los schemas expuestos; el test de privilegios lo cubre.
- **Roles `reference_reader`/`reference_loader`:** pueden requerir un administrador de la base compartida. La migración otorga permisos solo si los roles existen en ese momento y no los otorga retroactivamente: por eso el Rollout los crea **antes** de migrar. Si se crearon después, hay que aplicar a mano el bloque de permisos de `docs/operacion.md`; si no, `reference_reader` y `reference_loader` quedan sin ningún privilegio.
- **Tamaño del artefacto (~1 MB por snapshot) en el historial:** aceptable al ritmo esperado de publicaciones.

## Rollout y rollback

- **Rollout:**
  1. crear los roles `reference_reader` y `reference_loader` (administrador de la base);
  2. aplicar la migración 0001, que otorga los permisos a los roles existentes;
  3. verificar los permisos (bloque de verificación de `docs/operacion.md`); si los roles se crearon después de migrar, aplicar antes el bloque de permisos de respaldo;
  4. desplegar la API con `reference_reader`;
  5. incorporar el primer snapshot de PREP con `reference_loader`.
  - Los comandos, el SQL y las variables de entorno de cada paso están en [`docs/operacion.md`](../../docs/operacion.md); las pruebas de integración ejecutan ese SQL contra un Postgres real, en ambos órdenes.
- **Rollback:**
  - Antes del primer consumidor, la migración tiene `downgrade` (drop del schema).
  - Después del primer consumidor no hay rollback de datos: los snapshots son inmutables y se corrige hacia adelante con una `snapshot_version` nueva. Un despliegue defectuoso de la API se revierte desplegando la versión anterior, porque los datos no cambian.

## Fuera de este plan

- La gobernanza transversal de `AGENTS.md` sigue pendiente de decisión aparte: dónde viven `status` y `<Entidad>Locale`, y el conflicto de `status.md`.
- El dataset inicial lo produce PREP (S-7).
