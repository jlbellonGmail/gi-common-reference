# Status 006 — Aceptación funcional transversal

Estado vivo y verificable (AGENTS.md). El estado sale de este archivo, `tasks.md`, git y los comandos citados.

- Rama: `feature/006-cross-module-acceptance` · base `feature/005-units-of-measure` `50efb12` (005 completa + lock AI-NATIVE v4.0.1) · AI-NATIVE CLI v4.0.1 / lock v4.0.1
- Merge: después de #10 (005). Sin cambios de producto.

## Gates
- `node .ai-native/ai-native.mjs sdd validate 006-cross-module-acceptance`: ver «Evidencia».
- AI-NATIVE v4.0.1 no ofrece Native Acceptance, Dependency Graph ni Goal/Loop (subcomandos de `ai-native.mjs`: version, doctor, status, sync, rollback, adapters, l3, hitl, sdd, knowledge, audit, evals). No se inventaron comandos: la aceptación son pruebas caja negra y el grafo un artefacto verificado por prueba.

## Evidencia
(se completa con los resultados reales; ver más abajo)
