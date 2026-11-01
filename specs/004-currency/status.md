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
