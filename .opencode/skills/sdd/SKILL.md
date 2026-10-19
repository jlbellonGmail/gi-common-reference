---
name: sdd
description: Spec-Driven Development router. Use for /feature, any /sdd-* command, specs/NNN-slug/ folders, or when choosing the SDD level (light, normal, full) for a Task, Feature or Milestone.
---

# SDD — router

Procedure only. Rules live in `AGENTS.md`; state lives in governance and Git; methodology lives in `knowledge/sdd/methodology/` (in a consumer: `ai-native run -- knowledge sdd/methodology/<phase>.md`, resolved from the pinned release) and is loaded on demand, one file per phase.

## Model

```text
Work unit : Task (small)   Feature (one capability)   Milestone (several coherent units)
Level     : light          normal                     full
Mode      : manual (user drives)  guided (system knows next step)  automatic (Coordinator drives)
Roles     : Coordinator  Planner  Implementer  Reviewer     (runtime ids: -, planner, builder, reviewer)
```

Canonical contract: `contracts/sdd-workflow.json`. Executable layer: `runtime/circuit/sdd-workflow.mjs`, `implement-all.mjs`, `coordinator.mjs`.
In a consumer the release is reached only through the launcher `.ai-native/ai-native.mjs` (run it with node; it is `ai-native run -- <command>`): `sdd validate|status|next|mark|budget`, `hitl --base <ref>`, `knowledge <ref>`, `l3`. Never call `runtime/...` or `contracts/...` paths directly.

## Route (load only what the phase needs)

| Need | Command | Load |
|---|---|---|
| Unsure where to start | `/feature "<goal>"` | `levels.md` |
| What and why | `/sdd-spec` | `specification.md` |
| Resolve ambiguity | `/sdd-clarify` | `clarify.md` |
| How | `/sdd-plan` | `planning.md` |
| Break down | `/sdd-tasks` | `tasks.md` |
| One task | `/sdd-implement` | `implementation.md` |
| All tasks | `/sdd-implement-all` | `implementation.md`, `review.md` |
| Check | `/sdd-validate`, `/sdd-analyze` | `validation.md`, `review.md` |
| Requirement changed | `/sdd-change` | `change-management.md` |
| Where am I | `/sdd-status` | none (derive from artifacts) |

Modes and handoffs: `modes.md`. Architecture, modules, contracts: `architecture.md`. Human gate, status, Constitution inheritance: `autonomy.md`. Tests vs review vs CodeQL, TDD: `quality.md`. Renamed or retired names: `migration.md`.

## Capability routing (a silent check, not a phase)

When a phase starts, or the kind of work changes materially (for example implementing turns into debugging), check silently whether the capabilities already in the session are enough. If they are, continue: no message, no artifact, no record, no extra step. Otherwise name the gap by type, never by provider, tool or agent:

* knowledge: specialised domain knowledge or method;
* external information: a claim depends on external or current documentation;
* external system: the work reads or acts on a system outside the repository;
* verification: proving the result needs a tool beyond the project's own checks.

Then:

* Use a matching capability only if it is already available and permitted; load it when it adds concrete value now, never in advance.
* Discovery is not activation: never install, connect, enable or configure anything that needs credentials, permissions, an environment change or a human decision. That follows the existing permission and human-gate rules; this check adds no gate.
* If it is unavailable, say exactly which part could not be done or verified (`NOT_RUN`) and continue with what is safe. Never simulate access, current knowledge or a check.
* Automatic mode: the Coordinator checks before delegating and names any gap in the delegation; a role that meets a new gap reports it instead of improvising. Check again only on a new need, never per task.

## Invariants

* A Task with level light creates no `spec.md`/`plan.md`/`tasks.md`.
* `spec` = what/why, `plan` = how, `tasks` = decomposed execution. Never mix them.
* The Reviewer is read-only and independent; repairs go Reviewer -> Coordinator -> Implementer -> Reviewer.
* Failure handling is bounded convergence (budget in `contracts/sdd-levels.json`); a task that does not converge blocks the work unit. Never fake success.
* Memory is auxiliary context; Git, governance, STATUS, validators and evidence are authoritative.
* Merge is a human decision.
