# Status 005 — Units of Measure

Estado vivo y verificable (AGENTS.md). El estado sale de este archivo, `tasks.md`, git y los comandos citados.

- Rama: `feature/005-units-of-measure` · base `develop` `0be253d` (001–004 aprobadas) · AI-NATIVE CLI v3.4.3 / lock v3.4.3
- Fuentes verificadas para el diseño (2026-11-02): `ucum-essence.xml` v2.2 rev. 2024-06-17 (`github.com/ucum-org/ucum`, sha256 `dfccea1b5dc284245ebae97edd1dc03c45864da4e87df55bc9851797b4fd0b61`, UCUM License v1.1); UNECE Rec 20 vía `github.com/datasets/unece-units-of-measure` (`units-of-measure.csv`, sha256 `e2d06370cdadf5da1bce705783ff5d0d94d11d70eacba6d592adf401c32fb76e`; copia derivada, no la publicación oficial).

## Gates
- 2026-11-02 `node .ai-native/ai-native.mjs sdd validate 005-units-of-measure`: PASS (SPEC_READY, PLAN_READY, TASKS_READY, nivel normal).
- `hitl --base develop`: PASS, riesgo low, `human_gate: final-only` (sin parada antes de implementar; merge = decisión humana).
- Budget: nivel normal, 4 intentos por task.
- Revisión independiente: AVAILABLE (agente `reviewer` en contexto aislado mediante `sdd review begin/record`).

## Evidencia por task

### T1 — esqueleto, fronteras y tabla UCUM (done)
- RED (antes de implementar): `pytest tests/contract -k "architecture or boundary or composition or layer or module or ucum"` → `14 failed, 109 passed` (units ausente de `architecture.json`, sin `__init__.py`, sin XML/NOTICE/package-data/`-text`).
- GREEN: mismo comando → `123 passed, 300 deselected`; `pytest tests/contract/test_layer_imports.py` → `47 passed` tras `ruff format`.
- `ruff format --check .` (287 archivos) y `ruff check .`: PASS; `mypy` (strict): `Success: no issues found in 213 source files`.
- `ucum-essence.xml` copiado con `cp` (sha256 `dfccea1b…0b61` verificado con `sha256sum` y por prueba), marcado `-text` en `.gitattributes`, `NOTICE.md` con licencia UCUM v1.1 y origen. package-data de `units.infrastructure` declarado (schema, política, `ucum/*`).
- `git diff` sobre `src/gi_common_reference/{locales,regions,countries,currencies}` y `migrations`: vacío. Solo se agregaron `units` a las enumeraciones de módulos de las pruebas de frontera/composición.
- Pendiente declarado: la superficie pública `units/interfaces/http` aún no existe (T8); el check de AI-NATIVE pasa igualmente.

### T2 — migración 0005 (done)
- RED (antes de existir `migrations/versions/0005_units.py`): `pytest tests/integration/units` → `9 failed, 2 passed, 172 errors in 263.15s` (`UndefinedTable: relation "reference.unit_snapshot" does not exist`).
- GREEN: `pytest tests/integration/units` → `183 passed in 305.95s` (tras corregir dos casos mal planteados de mi prueba: `K1` es un UNECE válido y `KGM` ya existía) y, con `test_dependency_direction.py` de Units, 186 pruebas en ese directorio.
- Pruebas de 001–004 afectadas por tener ahora tablas de Units (ejecutadas, PASS): `tests/integration/currencies/test_dependency_direction.py` + `tests/integration/units/test_dependency_direction.py` + `test_btree_gist_precondition.py` + `test_migration_env.py` + `test_migration_0001.py` → `91 passed`; downgrade/earlier/depend de 0002–0004 + `test_runbook*.py` → `14 passed` / `29 passed`.
- `ruff format --check .`, `ruff check .`, `mypy` (strict): PASS.
- Cambios fuera de los archivos permitidos de T2, mínimos y necesarios para no romper pruebas existentes: (1) `tests/integration/currencies/test_dependency_direction.py`: se agregó el conjunto `UNITS` a la enumeración de catálogos ("cada tabla pertenece a un catálogo"); (2) `docs/operacion.md`: el bloque `runbook:grants` incluye los permisos de 0005 (la prueba `test_following_the_runbook_in_either_order_leaves_the_same_privileges` compara el bloque con la migración). T10 documentará el resto.
- Nota de diseño: la composición `ref = (valor + desplazamiento) × factor` (RF-11) y los CHECK/triggers `uom_check_kind`, `uom_linear_offset`, inmutabilidad y `uom_is_canonical_*` están en la migración; `ucum_table_version` es `text` (p. ej. `2.2`).

### T3 — contrato del snapshot, digest, lector y política (done)
- RED (con los módulos de `units/domain` e `infrastructure` de T3 apartados): `pytest tests/unit/units tests/contract/units` → `5 errors` en colección (`ModuleNotFoundError: gi_common_reference.units.domain.digest`).
- GREEN: primer intento `1 failed, 152 passed` (las unidades base del XML no traen `isMetric`; el lector las marca metric, como manda UCUM); luego `pytest tests/unit/units tests/contract/units` → `153 passed`; con `-k "units or ucum or architecture or boundary or composition or layer or module or packaged or installed"` sobre `tests/unit/units` y `tests/contract` → `297 passed`.
- `ruff format --check .` (306 archivos), `ruff check .`, `mypy` (strict, 231 archivos): PASS.
- Entregado: schema publicado y empaquetado idénticos (prueba byte a byte); `contracts/units-snapshot.v1.example.json` sellado, no productivo, generado por `python -m tests.fixtures.units` (única fuente: `tests/fixtures/units.py`; una prueba compara ejemplo = builder) con el catálogo de S-6 (14 magnitudes, 52 unidades distintas); política `en`/`es` v1 con los `locale_id` publicados; digest con paridad contra `contracts/locale-snapshot.v1.vectors.json`; clasificación A/B/C/D (reglas RF-41/RF-42); lector que rechaza claves duplicadas, floats, NaN, números JSON en `factor`/`offset`; lector UCUM (`ucum_reader.py`) con sha256 fijado: adulterado, truncado, otros fines de línea o renombrado → `SchemaLoadError`.
- Pendiente de tareas posteriores (declarado): validación semántica de forma canónica de factor/offset, UCUM y completitud (T4/T5); el schema solo exige `string`.
