---
name: delivery-governance
description: Apply delivery governance for feature-per-task execution, Git, GitHub, GitHub Actions, worktrees, Engram, MCP, documentation, Security by Design, DevSecOps and monitoring.
---

# Factory Delivery Governance Skill

## Scope

This is the single canonical skill for both the AI-NATIVE factory repository and generated projects (it replaces the former duplicated `factory-*` / `project-*` pair; PAR-CANONICAL-SOURCE).

Where the text below says "the factory" or "the workspace", read it as the repository that contains this skill and its own governance. A generated project is operable from its own repository: it must not assume the factory workspace exists locally or depend on factory workspace paths.

---

## Purpose

Use this skill for executable AI-NATIVE factory tasks that involve implementation, validation, documentation, security, observability, commits, GitHub, CI, Engram or MCP.

This skill complements:

- AGENTS.md
- .specify/memory/constitution.md
- .agents/skills/task-execution/SKILL.md

Governance remains the source of truth.

---

## Feature Per Task Policy

Every executable task must be treated as one feature unless governance explicitly classifies it as audit-only, documentation-only or governance-only.

One feature means:

- one task boundary
- one spec boundary when required
- one branch or worktree when isolation is required
- one validation boundary
- one documentation decision
- one security decision
- one closure decision
- one human approval decision when required

Do not batch unrelated work.

Do not open the next feature during closure of the current one.

---

## Git / GitHub / CI / Worktree Policy

Git records what changed.

GitHub is the remote collaboration and traceability layer when configured.

GitHub Actions is external CI evidence when configured.

Worktrees may isolate risky, parallel or recovery work.

Rules:

- run local validation before relying on CI
- do not push unless explicitly instructed or governance requires an attempt
- do not open PRs unless explicitly instructed or governance requires it
- do not merge without explicit approval
- do not delete remote branches without explicit approval
- do not delete worktrees with uncommitted work

CI status values:

- PASS
- FAIL
- PENDING
- NOT_RUN
- NOT_AVAILABLE
- CONTEXTUAL_NON_BLOCKING

---

## Engram Policy

Engram is auxiliary memory.

Use Engram to reduce token usage and preserve checkpoints when available.

Engram may store:

- pre-task checkpoint
- post-task checkpoint
- recovery summary
- closure summary
- validation summary
- commit summary
- residual risk notes

Engram never overrides:

- governance
- git
- validators
- explicit human approval

---

## MCP Policy

MCP is auxiliary tool/context access.

Use MCP to reduce context-window usage by retrieving narrow context from tools, repositories, GitHub metadata, documentation or memory systems.

MCP does not replace repository evidence.

If MCP conflicts with governance or git, governance and git win.

---

## Documentation Policy

Every executable feature must evaluate documentation impact.

Documentation categories:

- technical documentation
- project/user/generated-project documentation

Documentation must be updated when a feature changes:

- behavior
- setup
- generated project behavior
- CLI behavior
- configuration
- validation commands
- security posture
- observability posture
- governance process
- recovery process

Documentation status values:

- UPDATED
- PASS
- NOT_APPLICABLE
- NOT_RUN
- BLOCKED

---

## Security by Design Policy

Security must be considered from design through runtime.

Design checks:

- trust boundaries
- sensitive data
- auth/authz impact
- supply-chain impact
- configuration risks
- generated-project security impact

Development checks:

- no hardcoded secrets
- no unsafe defaults
- no injection-prone changes
- no bypassed validation
- no weakened security controls
- dependencies justified

DevSecOps checks:

- static analysis considered
- secret scanning considered
- dependency review considered
- vulnerability scanning considered
- SBOM impact considered
- GitHub Actions permissions preserved
- deployment gates preserved

Monitoring checks:

- logs
- metrics
- traces
- alerts
- dashboards
- health checks
- runbooks

Security status values:

- PASS
- NOT_APPLICABLE
- RISK_ACCEPTED
- BLOCKED
- CONTEXTUAL_NON_BLOCKING

---

## Final Delivery Gate

Before closure, report:

FEATURE:
BRANCH / WORKTREE:
SPEC STATUS:
TASKS STATUS:
LOCAL VALIDATION:
CI STATUS:
DOCUMENTATION STATUS:
SECURITY STATUS:
DEVSECOPS STATUS:
OBSERVABILITY STATUS:
ENGRAM STATUS:
MCP STATUS:
COMMITS:
GITHUB / PUSH / PR STATUS:
GOVERNANCE STATUS:
HUMAN APPROVAL:
NEXT ELIGIBLE:

Do not overstate closure.
