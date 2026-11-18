# Status 006 — Aceptación funcional transversal

Estado vivo y verificable (AGENTS.md). El estado sale de este archivo, `tasks.md`, git y los comandos citados.

- Rama: `feature/006-cross-module-acceptance` · base `feature/005-units-of-measure` `50efb12` (005 completa + lock AI-NATIVE v4.0.1) · AI-NATIVE CLI v4.0.1 / lock v4.0.1
- Merge: después de #10 (005). Sin cambios de producto.

## Gates
- `node .ai-native/ai-native.mjs sdd validate 006-cross-module-acceptance`: ver «Evidencia».
- AI-NATIVE v4.0.1 no ofrece Native Acceptance, Dependency Graph ni Goal/Loop (subcomandos de `ai-native.mjs`: version, doctor, status, sync, rollback, adapters, l3, hitl, sdd, knowledge, audit, evals). No se inventaron comandos: la aceptación son pruebas caja negra y el grafo un artefacto verificado por prueba.

## Evidencia por task

### T1 — grafo de dependencias (done)
- `docs/dependency-graph.json`: locales → ∅; regions → locales; countries → locales, regions; currencies → locales, countries; units → locales. Orden: locales, regions, countries, currencies, units.
- `test_02` lo contrasta con las FKs reales (`pg_constraint` del schema `reference` migrado), la línea «Depende de» de cada spec, la cadena `down_revision` 0001→0005, `architecture.json` e imports entre paquetes. Acíclico y topológico.
- Mutación 1 (arista inventada `units → countries`): `test_02` FAIL `{'solo declarado': {('units', 'countries')}}`. Mutación 2 (omitir `currencies → countries`): FAIL `{'solo en la base': {('currencies', 'countries')}}`. Restaurado: PASS.

### T2/T3 — stack transversal y casos (done)
- Primera ejecución (RED, supuestos míos, no defectos del sistema): (1) Countries rechazó las banderas: el paquete instalado no trae SVG (003, S-7) → snapshot con excepciones de bandera, como la prueba de CLI de 003; (2) `alembic_version` en el schema `reference` → excluida del inventario; (3) Locale y Regions no exponen `diff` → `diff` solo en countries/currencies/units; (4) la respuesta `by-country` anida la moneda en `currency`.
- CA-7: en la primera versión 3 de 6 rechazos ocurrían por otro motivo (omitir datos publicados, RF-37/RF-43) y la prueba pasaba igual. Se rediseñaron los casos (agregar la referencia rota sin omitir nada) y la prueba exige ahora exit 1, `RECHAZADO`, el motivo esperado y ninguna «omite».
- CA-8: la primera versión usaba `UPDATE` y todas fallaban por inmutabilidad (23001), no por FK. Ahora inserta filas nuevas clonadas con la referencia rota (7 aristas entre módulos + `country.region_id`) y exige 23503; cambios/borrados aparte (23001/23503).
- GREEN: `pytest tests/acceptance/test_cross_module_acceptance.py` → 28 passed (Postgres 16, testcontainers).

### T4 — runner y evidencia (done)
- `python tools/acceptance/cross_module_acceptance.py` sobre `1b682ab` (código de 006 rebasado sobre 005 `212016a`) → `28 passed`, exit 0, dos ejecuciones con evidencia byte a byte idéntica (antes, el orden de un `set` en CA-5 hacía variar `04-http-transcripts.json`; corregido); evidencia en `acceptance/cross-module/evidence/`; sha256 de los blobs commiteados = `06-manifest-sha256.txt` (verificado con `git show :<ruta> | sha256sum`).

### T5 — manual (done)
- `docs/aceptacion-manual.md` (M-01…M-13, restauración, checklist por módulo) y `tools/acceptance/write_acceptance_dataset.py` (mismos builders que la suite; dos ejecuciones → bytes idénticos).
- Ensayado literalmente en PowerShell 7 contra `postgres:16-alpine` en Docker: todas las salidas esperadas del manual son las observadas. Un defecto del propio manual se detectó y corrigió en el ensayo: el bucle de M-09 usaba `$b`, que pisaba `$B` (PowerShell no distingue mayúsculas en variables) y todas las peticiones siguientes salían con `000`.

### T6 — verificación y regresión (done)
- `ruff format --check .`, `ruff check .`, `mypy` strict: PASS. `sdd validate 006-cross-module-acceptance`: PASS. `hitl --base feature/005-units-of-measure`: PASS (riesgo high, `human_gate: required`).
- Regresión sobre la revisión de 006: aceptaciones de 004 y 005 (`tests/acceptance/test_currency_acceptance.py`, `test_units_acceptance.py`, `ACCEPTANCE_BASE=origin/develop`) → 31 passed.
- Suite completa: corrida por la plataforma sobre 005 `50efb12` (3496 passed, 0 failed); 006 solo agrega archivos de prueba/doc nuevos (CA-14).

## Pendientes declarados
- `GET /v1/countries/{id}/flag` en caja negra: NOT_EXECUTED (sin SVG empaquetados hasta PREP).
- Datasets reales y Supabase `gi-dev`: DEFERRED_TO_PREP_DATASET (de 003–005).
- Sin CI en el repositorio.
