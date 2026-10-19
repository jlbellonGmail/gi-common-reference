---
name: task-execution
description: Execute exactly one task using governance, SDD, Builder + Inspector, real validations, auditable commits and human approval discipline.
---

---

# AI-NATIVE Task Execution Skill

## Scope

This is the single canonical skill for both the AI-NATIVE factory repository and generated projects (it replaces the former duplicated `factory-*` / `project-*` pair; PAR-CANONICAL-SOURCE).

Where the text below says "the factory" or "the workspace", read it as the repository that contains this skill and its own governance. A generated project is operable from its own repository: it must not assume the factory workspace exists locally or depend on factory workspace paths.

---

## Purpose

Use this skill to execute exactly one task inside the AI-NATIVE factory.

This skill applies to the factory workspace that contains:

```text
governance/
foundation/
knowledge/
template/
```


---

## Required Operating Contract

Before using this skill, read and obey:

```text
AGENTS.md
```

AGENTS.md defines the stable operating rules.

This skill defines the repeatable task execution procedure.

Governance defines the active task and state.

---

## Hard Rules

The agent must obey:

```text
- Execute one task only.
- Do not batch tasks.
- Do not open the next task.
- Do not reimplement closed tasks.
- Do not modify files outside scope.
- Do not infer task state from memory.
- Do not claim validation PASS without command evidence.
- Do not record human approval without explicit user approval.
```

---

## Phase 0 — Preflight

Before changing files, inspect the factory state.

From the factory root, inspect governance:

```text
governance/roadmaps/
governance/SESSION-CONTEXT.md
governance/execution/current/
governance/execution/archive/
```

Determine:

```text
- active roadmap
- current task
- eligible task
- closed tasks
- blocked tasks
- expected validation gates
- required governance updates
- human approval requirements
```

Inspect git state in every relevant repository.

Minimum per relevant repository:

```bash
git status --short
git branch --show-current
git log --oneline --decorate -5
```

If scope is unclear, inspect all factory repositories:

```text
governance/
foundation/
knowledge/
template/
```

Do not implement anything until task eligibility is confirmed from governance.

If governance is inconsistent, stop and report the inconsistency.

---

## Phase 1 — Specify

Create a compact SPEC before implementation.

The SPEC must include:

```text
TASK:
OBJECTIVE:
ENGINEERING PURPOSE:
AFFECTED REPOSITORIES:
EXPECTED FILES OR AREAS:
NON-GOALS:
ACCEPTANCE CRITERIA:
EXPECTED VALIDATIONS:
RISKS:
```

Rules:

```text
- The SPEC must be based on governance and repository evidence.
- The SPEC must not expand the task.
- The SPEC must explicitly define what will not be done.
- No file modification is allowed in this phase unless the user explicitly requested a planning artifact.
```

---

## Phase 2 — Plan

Create a compact PLAN.

The PLAN must include:

```text
CHANGE STRATEGY:
REPOSITORY SCOPE:
FILES ALLOWED TO CHANGE:
VALIDATORS TO RUN:
GOVERNANCE UPDATE STRATEGY:
COMMIT STRATEGY:
RECOVERY CONSIDERATIONS:
```

Rules:

```text
- Plan the minimum viable change.
- Avoid broad repository traversal.
- Avoid unrelated cleanup.
- Avoid generated junk.
- Avoid touching unrelated repositories.
- Cross-repository work requires explicit justification.
```

---

## Phase 3 — Implement

Implement only the planned change.

Rules:

```text
- No hardcoded shortcuts.
- No unrelated formatting.
- No broad rewrites.
- No dependency additions unless justified.
- No silent deletion of legacy assets.
- No VERSION changes unless explicitly required.
- No destructive remote operations.
- No next-task preparation unless explicitly part of the current task.
```

For generated project behavior, distinguish between:

```text
factory operating files
template assets
generator behavior
generated project output
```

If the task affects generated project behavior, verify the template and generator path.

---

## Phase 4 — Verify

Run real validations.

Minimum per affected repository:

```bash
git status --short
git branch --show-current
git log --oneline --decorate -5
git diff --check
```

Then run task-specific validators discovered from:

```text
package.json
scripts/
validation/
tests/
governance/
README files
task-specific documentation
```

Validation reporting must use only these states:

```text
PASS
FAIL
NOT_RUN
NOT_APPLICABLE
CONTEXTUAL_NON_BLOCKING
```

Never claim PASS without command evidence.

If a validator fails, stop and classify whether the failure is:

```text
BLOCKING
CONTEXTUAL_NON_BLOCKING
OUT_OF_SCOPE
```

---

## Phase 5 — Inspect Diff

Before committing, inspect the diff.

Check:

```text
- changed files match the SPEC
- implementation follows the PLAN
- no unrelated files changed
- no generated junk added
- no secrets or credentials added
- no closed task reopened
- no next task opened
- no broad formatting churn
```

If the diff contains unrelated changes, revert or isolate them before committing.

---

## Phase 6 — Commit

Commit only after validation and diff inspection.

Commit strategy:

```text
- product changes and governance changes should be committed separately when practical
- each commit must be atomic
- each commit message must describe the actual change
- do not claim broader completion than evidence supports
```

Recommended commit categories:

```text
feat:
fix:
docs:
test:
chore:
refactor:
```

Do not push unless explicitly instructed or governance policy requires an attempt.

If push is attempted and fails due to credentials or remote access, report it as:

```text
CONTEXTUAL_NON_BLOCKING
```

only if the applicable governance policy allows it.

---

## Phase 7 — Governance Update

Update governance only if the task requires it.

Potential governance areas:

```text
governance/roadmaps/
governance/SESSION-CONTEXT.md
governance/execution/current/
governance/execution/archive/
```

Rules:

```text
- Do not mark a task closed without validation evidence.
- Do not mark human approval without explicit user approval.
- Do not open the next task during closure of the current one.
- Keep current execution and archive records consistent.
- Record residual risks honestly.
```

---

## Phase 8 — Inspector Audit

The Inspector must audit the task independently from the Builder behavior.

Inspector checklist:

```text
SPEC satisfied:
PLAN respected:
Scope controlled:
No closed task reopened:
No next task opened:
Validations real:
Diff clean:
Commits auditable:
Governance consistent:
Residual risks documented:
Human approval state correct:
```

The Inspector must be critical.

If any item fails, do not overstate closure.

---

## Phase 9 — Final Report

The final report must include:

```text
STATUS:
SCOPE:
REPOSITORIES:
FILES CHANGED:
VALIDATIONS:
COMMITS:
GOVERNANCE:
INSPECTOR RESULT:
RISKS:
HUMAN APPROVAL:
NEXT ELIGIBLE:
```

Rules:

```text
- NEXT ELIGIBLE is informational only.
- Reporting NEXT ELIGIBLE does not open that task.
- STATUS must not overstate closure.
- All uncertainty must be explicit.
- Do not paste large logs.
- Summarize evidence with exact commands and outcomes.
```

---

## Valid Status Values

Use one of:

```text
NOT_STARTED
IN_PROGRESS
IMPLEMENTED
VALIDATED
COMMITTED
CLOSED_LOCALLY_HUMAN_APPROVAL_REQUIRED
FORMALLY_CLOSED
BLOCKED
INCONSISTENT_STATE
```

Do not use `FORMALLY_CLOSED` unless explicit human approval has been recorded when required.

---

## Stop Conditions

Stop immediately if:

```text
- governance state is inconsistent
- task is not eligible
- working tree has unrelated dirty changes
- required files are missing
- validation fails in a blocking way
- implementation would require destructive remote operations
- user approval is required for a risky action
```

<!-- AI_NATIVE_FACTORY_DELIVERY_GOVERNANCE_GATE_START -->

---

## Delivery Governance Gate

Before final closure, use:

- .agents/skills/delivery-governance/SKILL.md

The agent must evaluate:

- feature-per-task status
- branch / worktree status
- GitHub / push / PR status
- GitHub Actions / CI status
- Engram status
- MCP status
- documentation status
- Security by Design status
- DevSecOps status
- observability / monitoring status

Do not close a feature without classifying each item as PASS, UPDATED, NOT_APPLICABLE, NOT_RUN, BLOCKED or CONTEXTUAL_NON_BLOCKING.

<!-- AI_NATIVE_FACTORY_DELIVERY_GOVERNANCE_GATE_END -->
