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
