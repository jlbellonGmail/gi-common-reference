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
