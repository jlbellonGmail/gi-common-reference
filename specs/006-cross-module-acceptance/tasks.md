# Tasks 006 — Aceptación funcional transversal

- [x] **T1. Grafo de dependencias declarativo.** RF-4, RF-5, CA-2
  - Done when: `docs/dependency-graph.json` declara los cinco módulos (spec, migración, CLI, tablas, `dependsOn`, orden de incorporación) y `test_02` lo verifica contra FKs reales, specs, migraciones, `architecture.json` e imports; dos mutaciones del grafo (arista inventada, arista omitida) hacen fallar `test_02`.

- [x] **T2. Stack transversal caja negra.** RF-1, RF-2, RF-3, RF-6, RF-7
  - Done when: `tests/acceptance/cross_module_support.py` crea una base nueva, migra con `alembic` por subproceso, incorpora los cinco v1 con sus CLIs en orden, arranca la API real con `reference_reader` y el guard de red; sin modificar `conftest.py` ni fixtures existentes.

- [x] **T3. Casos de aceptación CA-1 a CA-15.** RF-1, RF-2, RF-3, RF-5, RF-6, RF-7, CA-1, CA-2, CA-3, CA-4, CA-5, CA-6, CA-7, CA-8, CA-9, CA-10, CA-11, CA-12, CA-13, CA-14, CA-15
  - Done when: `pytest tests/acceptance/test_cross_module_acceptance.py` → 28 passed sobre Postgres 16 real; CA-7 verifica el motivo de cada rechazo; CA-8 distingue FK (23503) de inmutabilidad (23001).

- [x] **T4. Runner y evidencia reproducible.** RF-8
  - Done when: `python tools/acceptance/cross_module_acceptance.py` deja `acceptance/cross-module/evidence/01–06` con manifiesto sha256, exit 0; `.gitattributes` marca la evidencia `-text`.

- [x] **T5. Manual de aceptación funcional y documentación.** RF-9
  - Done when: `docs/aceptacion-manual.md` con prerrequisitos, datos, pasos exactos, resultado esperado, PASS/FAIL, restauración y checklist por módulo; `docs/desarrollo.md` y `README.md` lo referencian.

- [x] **T6. Verificación y regresión.** RF-7, CA-14
  - Done when: `ruff`, `mypy` strict, `sdd validate 006-cross-module-acceptance` PASS; aceptaciones de 004 y 005 reejecutadas sobre la revisión de 006; evidencia en `status.md`.
