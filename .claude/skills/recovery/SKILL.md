---
name: recovery
description: Recover the real state of one task from governance, git, diffs, commits and validation evidence before continuing.
---

---

# AI-NATIVE Recovery Skill

## Scope

This is the single canonical skill for both the AI-NATIVE factory repository and generated projects (it replaces the former duplicated `factory-*` / `project-*` pair; PAR-CANONICAL-SOURCE).

Where the text below says "the factory" or "the workspace", read it as the repository that contains this skill and its own governance. A generated project is operable from its own repository: it must not assume the factory workspace exists locally or depend on factory workspace paths.

---

## Purpose

Use this skill to recover a partially completed or interrupted task inside the AI-NATIVE factory.

Recovery is diagnostic first.

Do not implement new changes until the task state is classified.

---

## Required Operating Contract

Before using this skill, read and obey:

```text
AGENTS.md
```

AGENTS.md defines the stable operating rules.

This skill defines the recovery procedure.

Governance and git define the truth.

---

## Hard Rules

The agent must obey:

```text
- Do not assume continuity from chat memory.
- Do not trust old prompts as evidence.
- Do not continue implementation before classification.
- Do not overwrite uncommitted work.
- Do not open the next task.
- Do not reimplement closed tasks.
- Do not create commits before recovery classification.
- Do not claim validation PASS without command evidence.
```

---

## Phase 1 — Governance Inspection

Inspect governance first.

Read relevant files under:

```text
governance/roadmaps/
governance/SESSION-CONTEXT.md
governance/execution/current/
governance/execution/archive/
```

Determine:

```text
ACTIVE ROADMAP:
CURRENT TASK:
ELIGIBLE TASK:
TASK STATE:
CLOSED TASKS:
BLOCKED TASKS:
HUMAN APPROVAL STATE:
ARCHIVE STATE:
GOVERNANCE INCONSISTENCIES:
```

If governance is inconsistent, record the inconsistency and continue only with diagnostic inspection.

---

## Phase 2 — Git Inspection

Inspect git state in relevant repositories.

If scope is unclear, inspect all factory repositories:

```text
governance/
foundation/
knowledge/
template/
```

Minimum commands per inspected repository:

```bash
git status --short
git branch --show-current
git log --oneline --decorate -8
```

If there are uncommitted changes:

```bash
git diff --stat
git diff
```

If there are suspected untracked files:

```bash
git status --short
```

Do not modify files during this phase.

---

## Phase 3 — Evidence Inspection

Look for evidence of partial or completed work:

```text
- modified files
- untracked files
- recent commits
- archive records
- current execution records
- validation logs or reports
- generated outputs
- branch names
- commit messages
```

Branch names and commit messages are clues, not final proof.

Governance plus git plus validations decide state.

---

## Phase 4 — Recovery Classification

Classify the task as exactly one of:

```text
NOT_STARTED
IN_PROGRESS_UNCOMMITTED
IMPLEMENTED_UNVALIDATED
VALIDATED_UNCOMMITTED
COMMITTED_UNGOVERNED
CLOSED_LOCALLY_HUMAN_APPROVAL_REQUIRED
FORMALLY_CLOSED
INCONSISTENT_STATE
```

Classification rules:

```text
NOT_STARTED:
No relevant uncommitted changes, no relevant commits, no current execution evidence.

IN_PROGRESS_UNCOMMITTED:
Relevant uncommitted changes exist, but validation is missing or incomplete.

IMPLEMENTED_UNVALIDATED:
Implementation appears complete, but validations are missing, stale or failed.

VALIDATED_UNCOMMITTED:
Relevant implementation is validated but not committed.

COMMITTED_UNGOVERNED:
Relevant commits exist, but governance/execution (current and archive) does not reflect them.

CLOSED_LOCALLY_HUMAN_APPROVAL_REQUIRED:
Implementation, validation, commits and governance closure exist, but human approval is pending.

FORMALLY_CLOSED:
Governance records formal closure and required human approval is recorded.

INCONSISTENT_STATE:
Evidence conflicts and safe continuation is not possible without user decision.
```

Do not continue before classification.

---

## Phase 5 — Safe Action Matrix

Use this matrix after classification:

```text
NOT_STARTED:
Stop unless the user explicitly asks to execute the task.

IN_PROGRESS_UNCOMMITTED:
Inspect diff, confirm scope, then continue only the same task if safe.

IMPLEMENTED_UNVALIDATED:
Run missing validations before committing.

VALIDATED_UNCOMMITTED:
Re-check relevant validations if needed, then commit if still valid.

COMMITTED_UNGOVERNED:
Inspect commits and update governance only if commits are valid.

CLOSED_LOCALLY_HUMAN_APPROVAL_REQUIRED:
Do not change product. Prepare human approval summary.

FORMALLY_CLOSED:
Stop. Do not reopen.

INCONSISTENT_STATE:
Stop and report evidence plus options.
```

---

## Phase 6 — Optional Continuation

Continuation is allowed only if:

```text
- the task is clearly the same task
- governance allows continuing it
- uncommitted changes are in scope
- no closed task is being reopened
- no next task is being opened
- no unrelated dirty changes would be overwritten
```

If continuation is allowed, use the task execution skill from the recovered point.

Do not restart from scratch unless evidence proves the task was not started.

---

## Recovery Report

The recovery report must include:

```text
RECOVERED STATE:
TASK:
ROADMAP:
REPOSITORIES:
BRANCHES:
COMMITS FOUND:
UNCOMMITTED CHANGES:
UNTRACKED FILES:
GOVERNANCE STATE:
VALIDATIONS FOUND:
VALIDATIONS MISSING:
RISKS:
SAFE NEXT ACTION:
HUMAN APPROVAL:
```

Rules:

```text
- Do not overstate recovery certainty.
- Distinguish evidence from assumptions.
- Do not paste large diffs unless necessary.
- Prefer exact paths, commands and short outcomes.
```

---

## Stop Conditions

Stop immediately if:

```text
- governance contradicts git state
- unrelated dirty changes exist
- task identity is unclear
- product commits exist without clear scope
- archive records conflict with current state
- formal closure already exists
- human approval is pending
```
