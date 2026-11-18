# Plan 006 — Aceptación funcional transversal

- **Estado:** approved (2026-11-18, derivado de la spec; mismo alcance)
- **Spec:** [spec.md](spec.md)
- **Perfil:** `python-service`

## Precondición

`feature/006-cross-module-acceptance` parte de `feature/005-units-of-measure` (`50efb12`: 005 completa + lock AI-NATIVE v4.0.1), porque necesita los cinco catálogos. Se mergea **después** de #10 (005); hasta entonces su diff contra `develop` incluye 005.

## Diseño

| Decisión | Elección | Motivo |
|---|---|---|
| D1 Caja negra | CLIs y `alembic` como subprocesos; API real con uvicorn; Postgres 16 (testcontainers) | Mismo estándar que las aceptaciones de 004/005; sin mocks. |
| D2 Reutilización | `tests/acceptance/conftest.py` (guard de red, `Evidence`, `Stack`) y builders de `tests/fixtures/*`, **sin modificarlos** | RF-7; datos deterministas ya validados por cada módulo. |
| D3 Coherencia de datos | Currency referencia los `country_id` REALES de Countries (override de `country_id` en el builder de 004) | Prueba la integración real (004 sembraba con SQL). |
| D4 Banderas | Countries con excepciones de bandera declaradas | El paquete no trae SVG (003, S-7). |
| D5 Grafo | `docs/dependency-graph.json` declarativo + `test_02` que lo contrasta con `pg_constraint`, specs, migraciones, `architecture.json` e imports | AI-NATIVE v4.0.1 no tiene comando de grafo; la verdad sale del sistema. |
| D6 Rechazos con motivo | CA-7 exige exit 1, `RECHAZADO`, el motivo esperado y ausencia de «omite» | Evita falsos PASS por rechazos ajenos (detectado al implementar: 3 de 6 casos fallaban por omisión de datos publicados). |
| D7 FK vs. trigger | CA-8 inserta filas NUEVAS clonadas con la referencia rota y exige 23503; cambios/borrados aparte (23001) | Distingue integridad referencial de inmutabilidad. |
| D8 Evidencia | `tools/acceptance/cross_module_acceptance.py` → `acceptance/cross-module/evidence/01–06`, `-text` en `.gitattributes` | Manifiesto sha256 estable entre plataformas (criterio de 004/005). |
| D9 Base del diff (CA-14) | `CROSS_ACCEPTANCE_BASE` o, por defecto, `origin/feature/005-units-of-measure` → `origin/develop` | Mientras 005 no esté en `develop`, la base es su punta. |

## Archivos

- `tests/acceptance/cross_module_support.py`, `tests/acceptance/test_cross_module_acceptance.py` (nuevos)
- `tools/acceptance/cross_module_acceptance.py` (nuevo)
- `docs/dependency-graph.json`, `docs/aceptacion-manual.md` (nuevos); `docs/desarrollo.md`, `README.md` (referencias)
- `acceptance/cross-module/{README.md,evidence/*}` (nuevos), `.gitattributes` (+1 línea)
- `specs/006-cross-module-acceptance/*`

## Verificación

`pytest tests/acceptance/test_cross_module_acceptance.py` (28 casos), runner con evidencia, `ruff`, `mypy`, `sdd validate 006-cross-module-acceptance`, aceptaciones de 004/005 sobre la misma revisión (regresión), revisión independiente.
