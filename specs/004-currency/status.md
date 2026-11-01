# Status 004 — Currency

Estado vivo y verificable (AGENTS.md). Sin memoria conversacional: el estado sale de este archivo, `tasks.md`, git y los comandos citados.

- Rama: `feature/004-currency` · base `origin/develop` `eadad94` (001–003 aprobadas) · AI-NATIVE CLI v3.4.3 / PLATFORM v3.4.3
- Línea base antes de 004: `pytest -q` = 1699 passed (2026-11-01).
- Gates: SPEC_READY PASS · PLAN_READY PASS · TASKS_READY PASS (`sdd validate 004-currency` PASS).

## Evidencia por task

### T1 — esqueleto y fronteras (done)
- `pytest tests/contract/{test_architecture_contract,test_layer_imports,test_module_contract,test_composition_root}.py`: 92 passed (incluye el check `architecture` de AI-NATIVE sobre el repo y árboles sintéticos que prueban que `currencies` no puede importar 001–003 ni 001–003 importar `currencies`).
- `ruff format --check .`, `ruff check .`, `mypy`: PASS.
- `git diff origin/develop -- src/gi_common_reference/{locales,regions,countries} migrations specs/00[123]-*`: vacío.

### T2 — migración 0004 (done)
- `migrations/versions/0004_currencies.py`: `btree_gist`, `currency_snapshot`, `currency`, `currency_locale`, `country_currency` (`validity daterange` generada, exclusión GiST parcial diferible por par), triggers de reemplazo (existencia y ciclos), RF-19 (en `country_currency` y en `currency`), inmutabilidad de identidad/códigos/extremos de vigencia, sin `DELETE`/`TRUNCATE`, vista `country_currency_integrity_violation`, privilegios, `downgrade 0003`.
- `pytest tests/integration/currencies/test_migration_0004.py`: 90 passed (Postgres 16 en testcontainers; incluye dos conexiones concurrentes con períodos solapados → exactamente un commit, y `upgrade`/`downgrade 0003`).
- Hallazgo corregido durante T2: con inicio > fin la columna generada lanzaba `data_exception` antes del CHECK; ahora mapea a rango vacío y rechaza `country_currency_validity_ordered`.
- Ajuste de prueba (no funcional) en `tests/integration/test_migration_0003.py::test_locale_and_regions_do_not_depend_on_countries`: admite como únicas dependencias nuevas hacia Countries las tablas `country_currency` y `currency_snapshot` (D-16); Locale y Regions siguen sin poder depender de Countries. 001–003 sin cambios en `src/`, `migrations/` ni `specs/`.
- Regresión: `test_migration_0001/0002/0003/env` pasan sobre `head`=0004. `ruff format/check` y `mypy`: PASS.

### T3 — contrato del snapshot, digest, lector y política (done)
- Archivos: `contracts/currency-snapshot.v1.{schema,example}.json` (+ copia empaquetada equivalente), `currencies/infrastructure/{snapshot_reader,policy_reader}.py` + `required-locales.v1.json` (`en`/`es` por `locale_id`, versión 1), `currencies/domain/{digest,snapshot,policy,model,errors}.py`, `tests/fixtures/currencies.py` (sintético, no productivo, S-9), `pyproject.toml` (package-data).
- `pytest tests/unit/currencies tests/contract/currencies tests/contract/test_layer_imports.py tests/contract/test_composition_root.py tests/contract/test_installed_package.py`: 188 passed (incluye paridad de digest con los vectores de 001, clasificación A/B/C/D, el wheel instalado con schema y política).
- `ruff format --check`, `ruff check`, `mypy`: PASS.

### T4 — dominio de Currency (done)
- `currencies/domain/{codes,catalog}.py`: pasos 3, 4, 5, 6, 7 y 9 del plan como función pura (`plan_catalog_changes`), parseo de asociaciones y fechas (la validación temporal es T5).
- `pytest tests/unit/currencies/domain`: 104 passed. Cubre: ARS `032`/BOB `068`, unidades 0/2/3/4/N.A. (N.A. ≠ 0), fondos y unidades especiales, formatos inválidos, unicidad alfabética (incluye inactive) y numérica entre active (YUM→CSD), inmutabilidad de códigos publicados, VEF→VES, ISK 2→0 conserva id, reemplazo 0/1/N/repetido/nulo/propio/inexistente/ciclos de 2 y 3/romboide/en active, reactivación que limpia o no, omisiones RF-37, localizaciones en/es, locale inactive nuevo vs publicado, locales obligatorios, procedencia y conflictos sin resolver, orden de los pasos.
- Verificación de que las pruebas pueden fallar: mutando la detección de ciclos y la unicidad del numérico, 3 pruebas fallan; restaurado, 104 passed.

### T5 — dominio temporal de CountryCurrency (done)
- `currencies/domain/temporal.py` (vigencia `[inicio, fin)`, solapamiento por par, inmutabilidad de extremos, selección por fecha e historial) y paso 8 en `catalog.py` (+ omisión RF-37, RF-19/RF-38, procedencia `country_currency`/`validity`).
- `pytest tests/unit/currencies`: 302 passed. Vectores compartidos `tests/fixtures/temporal_vectors.py` comparados con el dominio y con PostgreSQL (`daterange(...,'[)')`, `&&`, `@>`): 23 passed en `tests/integration/currencies/test_temporal_parity.py`.
- Cubre: transición HRK→EUR el mismo día (2022-12-31 → HRK, 2023-01-01 → EUR), monedas simultáneas (PAB+USD), una moneda en varios países, readopción, solapamiento rechazado solo en el mismo par, retirado no participa, fechas no calendario (`2023-02-30`, `2023-W01-1`), cierre/completado único de extremos, corrección por retiro+alta, `status` independiente de la vigencia, omisiones rechazadas, conflicto de vigencia sin resolver.
- Mutación (`day <= end`): 4 pruebas fallan; restaurado, verde.
- Nota de diseño: el orden de historial por código alfabético (RF-49) se compone en T7 (necesita la moneda).

### T6 — incorporación transaccional, repositorio Postgres y CLI (done)
- `currencies/application/{incorporate,diff}.py`, `currencies/domain/{ports,diff}.py`, `currencies/infrastructure/{postgres_repository,conninfo}.py`, `currencies/interfaces/cli.py` (`incorporate`, `diff`, `check-integrity`), cableado en `bootstrap.py` (solo funciones nuevas) y lista fijada de imports permitidos de la raíz de composición.
- Locks: exclusivo `gi-common-reference.currencies.incorporation` + compartidos sobre Locale y Countries; `SET CONSTRAINTS ALL IMMEDIATE` antes del commit; una constraint violada es un rechazo con su requisito (RF-45, RF-19, RF-6, RF-3, RF-44; RNF-5 por defecto).
- Unit: `tests/unit/currencies` (incorporación con repositorio en memoria: orden de escritura, no-op, rechazos sin escrituras, atomicidad ante fallo en cada paso, transición, división, reactivación, List Three, diff sin escrituras, deriva; CLI: códigos de salida 0/1/2, sin credenciales).
- Integración (Postgres 16): `tests/integration/currencies/test_incorporation.py` 21 passed — primer snapshot, round-trip exacto de `032`/`068`/N.A./fechas, no-op con base idéntica, saltos de versión, 5 rechazos con dump idéntico, rollback ante error técnico, HRK→EUR (2022-12-31 → HRK; 2023-01-01 → EUR), historia no reescribible, división CSK, reactivación, List Three posterior, mismo estado lógico en dos bases (RNF-1), deriva por retiro de país y corrección, dos incorporaciones simultáneas serializadas (INCORPORATED + NOOP), rol `reference_loader` con mínimos privilegios, CLI con guard de red.
- Subconjunto de regresión T1–T6: 463 passed. `ruff format/check`, `mypy`: PASS.

### T7 — consultas de aplicación, lector Postgres y reloj (done)
- `currencies/application/queries.py` (resolver por id y por código, listado, validación `active`/`inactive`/`not_found`, monedas de un país y países de una moneda por fecha de referencia, historial, versión), `currencies/infrastructure/{postgres_reader,clock}.py`, puertos de lectura en `domain/ports.py`. El filtrado por fecha reutiliza `domain/temporal.py` (misma semántica que el SQL, RF-44).
- Unit `tests/unit/currencies/test_queries.py`: 52 passed (UUID válido/inexistente/mal formado; ARS/USD/EUR por id y por código; `usd` tolerado, ` USD`/`US`/`US$`/vacío inválidos; nombres `en`/`es`, locale válido sin traducción → nombre `null` sin fallback, locale inválido → validación; moneda retirada resoluble; listado por defecto solo `active` en orden binario; Country sin monedas/una/varias simultáneas; una moneda en varios países; fecha de referencia con límites semiabiertos, fecha mal formada, reloj inyectado; fondos excluibles; futura/histórica; historial; sesión única por consulta; catálogo vacío; falla técnica ≠ not found).
- Integración `tests/integration/currencies/test_reader.py` (Postgres 16, rol `reference_reader`): 26 passed — el lector SQL coincide con el lector en memoria en todas las monedas × locales, todos los países × fechas de borde × `include_inactive`, historiales; transición HR (2022-12-31 → HRK, 2023-01-01 → EUR); base inalcanzable → `ReaderUnavailable` sin credenciales.
- `ruff format/check`, `mypy`: PASS.

### T8 — API pública read-only, OpenAPI y composición (done)
- `currencies/interfaces/http.py` (`/v1/currencies*`, 9 rutas GET, sin escritura), `contracts/currencies-api.v1.openapi.json`, `bootstrap.py` (`postgres_currency_reader`, `system_clock`) y `app.py` (despacho por prefijo `/v1/currencies*` y `/v1/openapi/currencies.json`; los OpenAPI y rutas de Locale, Regions y Countries no cambian). Los parámetros de query mal tipados devuelven 422 `invalid_parameter` con el sobre común; una falla técnica, 503 `technical_error`.
- `pytest tests/contract/currencies/test_currencies_api.py` (Postgres real, rol `reference_reader`): 50 passed — todos los endpoints, 404/422/503 distinguibles, `usd`/`USD`, `032`, sin ruta por código numérico, nombres `en`/`es`/sin fallback, fecha de referencia con límites (HR 2022-12-31 → HRK, 2023-01-01 → EUR), reloj inyectado, historial, validación, rutas fijas vs `{currency_id}`, 405 en POST/PUT/PATCH/DELETE, sin tenant/mercado/atributos de Country en respuestas, catálogo vacío, base inalcanzable sin credenciales, OpenAPI publicado = generado = servido, los otros tres contratos publicados sin cambios.
- `pytest tests/contract` completo: 392 passed (incluye wheel instalado y fronteras de arquitectura). `ruff format/check`, `mypy`: PASS.
- `git diff origin/develop` sobre `src/` de locales/regions/countries, sus contratos OpenAPI, migraciones 0001–0003 y sus specs: vacío (CA-24).
- Compatibilidad: `create_catalog_app(...)` mantiene su firma para los 4 argumentos existentes; `currency_reader` y `clock` son opcionales (si faltan, `/v1/currencies*` no se sirve). Producción (`app_from_environment`) los pasa siempre.

### T9 — aceptación caja negra con evidencia reproducible (done)
- AI-NATIVE v3.4.3 no tiene comando de Native Acceptance (`ai-native help`): se ejecutaron los criterios de la spec como pruebas caja negra (D24). `tests/acceptance` (15 casos), `tools/acceptance/currency_acceptance.py`, `acceptance/currencies/README.md` y `acceptance/currencies/evidence/01`–`06`.
- Comando: `python tools/acceptance/currency_acceptance.py --base origin/develop` → **15 passed**, `pytest exit code: 0`, sobre la revisión `2a3d701` (ver `01-environment.txt`). CLI como subproceso + API real por HTTP + Postgres 16 real, con guard de red en ambos procesos y un canario que demuestra que bloquea.
- Cubre el mínimo del Goal: ARS/USD/EUR, nombres en/es, monedas actuales de un Country, Countries de una Currency, asociación histórica por fecha, múltiples monedas simultáneas, moneda retirada, preservación histórica, ausencia de dependencias runtime hacia ISO/CLDR, 001–003 sin cambios.
- **Declarado como NO ejecutado:** (1) CA-1 contra el dataset real de PREP (S-9): se verificó con un snapshot sintético sellado y no productivo; (2) aceptación contra Supabase `gi-dev` (no hay credenciales ni autorización para escribir en un entorno compartido).

### T10 — documentación, runbook y verificación global (done)
- `docs/operacion.md` (migración 0004, `btree_gist`, grants de monedas, API `/v1/currencies*`, sección 9 de incorporación con `diff` y `check-integrity`, sección 10 de trazabilidad con 4 consultas SQL ejecutables), `docs/desarrollo.md` (schema de Currency, `sdd validate 004-currency`, aceptación), `README.md`. `tests/integration/currencies/test_runbook_currencies.py` ejecuta los bloques SQL documentados; `test_runbook.py` (grants) actualizado por el runbook.
- **Suite global** (`pytest -q`, árbol limpio en `96085a2`): **2359 passed** (línea base de 001–003 = 1699) en 53 min 17 s, sin fallos ni omitidos.
- `ruff format --check .`: PASS · `ruff check .`: PASS · `mypy` (strict, 203 archivos): PASS.
- `node .ai-native/ai-native.mjs sdd validate 004-currency`: PASS · `sdd validate 003-countries`: PASS · `hitl --base develop`: PASS (riesgo high, `human_gate: required`).
- 001–003 sin cambios: `git diff origin/develop` sobre sus `src/`, migraciones, contratos y specs vacío (verificado también por `tests/acceptance` caso 14).
- No ejecutado / pendiente (declarado): CA-1 contra el dataset real de PREP (S-9); aceptación contra Supabase `gi-dev`; revisión independiente (siguiente etapa).
