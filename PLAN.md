# Agent Swarm Architecture — Design Plan

> **Status:** PLANNING — v2 (incorporated architecture review feedback)
> **Author:** Kaptaan + owner brainstorming
> **Date:** 2025

---

## 1. Problem Statement

The current agent is a **single ReAct loop** — one LLM call after another, up to 250 steps.
It thinks, acts, and judges its own work. This is like asking someone to write code
and review their own PR. Same brain, same blind spots.

**Symptoms:**
- Agent declares "done" without verifying (no build, no tests, no lint)
- Agent misses its own errors — same bugs persist across attempts
- Long tasks degrade — context gets polluted with failed attempts
- No decomposition — large tasks are attempted monolithically
- Quality plateaus at "junior developer" level

**Root cause:** No separation of concerns at the agent level.
One agent does everything: understand, plan, implement, review, ship.

**Goal:** Transform from a single "fast typist" into an autonomous engineering team
that operates at CTO-grade quality through role separation and adversarial review.

**Design principle:** Quality over speed. Token cost is a deliberate choice, not a constraint.

---

## 2. Architecture Overview

### The Swarm: Three Roles

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                  │
│                    (can interrupt anytime)                    │
│                         │                                    │
│                         ▼                                    │
│                  ┌─────────────┐                             │
│                  │   MANAGER   │  ← orchestrator             │
│                  │  (1 instance│  ← decomposes tasks         │
│                  │   per user  │  ← tracks progress          │
│                  │   request)  │  ← final authority          │
│                  │             │  ← resolves merge conflicts │
│                  └──────┬──────┘                             │
│                         │                                    │
│              ┌──────────┼──────────┐                         │
│              │          │          │                          │
│              ▼          ▼          ▼                          │
│        ┌─────────┐ ┌─────────┐ ┌─────────┐                  │
│        │   DEV   │ │   DEV   │ │   DEV   │  ← workers       │
│        │ (per    │ │ (per    │ │ (per    │  ← implement      │
│        │subtask) │ │subtask) │ │subtask) │  ← focused scope  │
│        └────┬────┘ └────┬────┘ └────┬────┘                  │
│             │           │           │                         │
│             └───────────┼───────────┘                         │
│                         │                                    │
│                         ▼                                    │
│                  ┌─────────────┐                             │
│                  │  REVIEWER   │  ← adversarial              │
│                  │ (1 instance │  ← reads diffs              │
│                  │  per review │  ← enforces standards       │
│                  │   cycle)    │  ← flags issues             │
│                  │             │  ← remembers across rounds  │
│                  └─────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

### Key Principle: Agents Never Talk Directly

All communication flows through the Manager. The Dev and Reviewer never see each
other's raw output. The Manager translates, filters, and decides what information
each agent needs.

```
Manager → Dev:     "Here's your task, here are the relevant files, here are constraints"
Dev → Manager:     "Status: done. Here's my diff. Here are test results."
Manager → Reviewer: "Here's the diff. Here are project standards. Review it."
Reviewer → Manager: "Verdict: REVISE. Issues: [list with severity]"
Manager → Dev:     "Reviewer found these issues. Fix them: [filtered list]"
Dev → Manager:     "Fixed. Here's the updated diff."
Manager → Reviewer: "Here's the updated diff. Re-review. Previous issues: [...]"
Reviewer → Manager: "Verdict: APPROVE. Previous issues resolved. No new issues."
Manager → User:    "Done. Here's what changed and what was verified."
```

---

## 3. Agent Roles — Detailed Design

### 3.1 Manager Agent

**Identity:** Tech lead / CTO. Never writes code. Never reviews code.
Thinks in architecture, decomposition, and quality gates.

**Responsibilities:**
1. Understand the user's intent (not just literal words)
2. **Self-validate decomposition** before executing (see §3.1.1)
3. Decompose tasks into logical subtasks with clear boundaries
4. Manage parallel execution with file-level conflict detection (see §3.1.2)
5. Review Reviewer feedback and decide: pass to Dev for fixes, or override
6. **Handle mid-task user interrupts** (see §3.1.3)
7. Track overall progress and report to user
8. Make architectural decisions (which pattern, which approach)
9. Decide when the task is truly "done"
10. **Resolve merge conflicts** when parallel Devs touch overlapping code (see §3.1.4)
11. Trigger git push only after full task completion + integration review

**Context it receives:**
- User's request (raw)
- Full conversation history
- Project memory + architecture notes + project standards
- Current codebase structure (file tree, not file contents)
- Active subtask statuses + file ownership map
- User interrupts (injected into context immediately)

**Context it does NOT receive:**
- Full file contents (too much context pollution)
- Tool execution output (Dev handles that)
- Diff contents (Reviewer handles that)

**Max steps:** 100 (it only thinks and delegates, never implements)

**Termination conditions:**
- All subtasks completed and reviewed → report success
- Max review cycles reached on a subtask → report partial success with warnings
- User request is ambiguous → ask for clarification
- Task is infeasible → explain why, suggest alternatives
- **User sends interrupt** → pause, process interrupt, adjust plan or abort

#### 3.1.1 Decomposition Self-Validation

**The problem:** Decomposition is the weakest link. A bad plan poisons every
downstream subtask. The Manager might create subtasks that are too large, too
vague, have hidden dependencies, or miss critical pieces.

**The solution:** After creating the plan, the Manager runs a **self-validation step**
before executing any subtasks. This is a separate LLM call with a validation-focused
prompt.

```
Manager creates plan (N subtasks)
    │
    ▼
Manager calls SELF-VALIDATE with the plan
    │
    ▼
Validation checks:
  1. Completeness — Does the plan cover ALL aspects of the user's request?
  2. Independence — Can each subtask be implemented without hidden dependencies?
  3. Scope — Is each subtask focused on ONE concern? (≤5 files per subtask)
  4. Dependencies — Are subtask orderings correct? Foundation before features?
  5. File conflicts — Do any subtasks modify the same files? If yes, must be sequential.
  6. Ambiguity — Is each subtask description clear enough for a Dev to execute?
  7. Testability — Can each subtask be independently verified?
    │
    ▼
Validation returns:
  - PASS → proceed to execution
  - REVISE → Manager rewrites plan with specific fixes, re-validates
    (max 2 self-validation rounds, then proceed anyway with warnings)
```

**Few-shot examples** are injected into the Manager prompt to guide decomposition:

```markdown
# Decomposition Examples

## Example 1: "Add dark mode"
GOOD decomposition:
  1. Add CSS variables for dark theme colors (frontend/src/app.css)
  2. Add theme toggle component (frontend/src/components/ThemeToggle.svelte)
  3. Wire toggle to persist in localStorage + apply on load (frontend/src/lib/stores.js)
  4. Update existing components to use CSS variables instead of hardcoded colors (3 files)

BAD decomposition:
  1. "Add dark mode" ← too vague, no file scope
  2. "Update CSS" ← which files? what changes?

## Example 2: "Add API authentication"
GOOD decomposition:
  1. Add auth middleware (backend/middleware/auth.py) ← new file, no conflicts
  2. Apply middleware to existing routes (backend/server.py) ← single file
  3. Add login/logout endpoints (backend/server.py) ← SAME file as #2, must be sequential
  4. Add frontend login flow (frontend/src/components/Login.svelte)

BAD decomposition:
  1. "Add auth" ← what specifically?
  2. "Update backend" ← which files? what changes?
  3. "Update frontend" ← too broad
```

These examples are part of the Manager's system prompt and can be extended
per-project based on past successful decompositions.

#### 3.1.2 Parallel Execution & File Locking

**The problem:** If 10 subtasks are spawned in parallel, two Devs might modify
the same file simultaneously, causing merge conflicts.

**The solution:** File-level ownership tracking + concurrency limit.

```
File Ownership Map (in-memory, per task):
  backend/db.py       → subtask-1 (locked)
  backend/server.py   → subtask-2 (locked)
  frontend/App.svelte → subtask-3 (locked)
```

**Rules:**
1. **Max 3 concurrent Dev agents.** Hard limit. Additional subtasks queue.
2. Before spawning a Dev, Manager checks file ownership. If any file is
   already owned by an active subtask, the new subtask **queues** until
   the file is released.
3. Subtasks with **zero file overlap** can run in parallel.
4. Subtasks with **file overlap** MUST run sequentially.
5. When a Dev finishes (approved), its file locks are released and the
   next queued subtask can start.

**Concurrency flow:**
```
Task has 10 subtasks. Max concurrency = 3.

Queue:    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

Step 1:   Spawn Dev for subtask 1, 2, 3 (no file overlap)
Active:   [1, 2, 3]
Queue:    [4, 5, 6, 7, 8, 9, 10]

Step 2:   Subtask 1 approved. Release locks.
          Spawn Dev for subtask 4 (no overlap with 2, 3)
Active:   [2, 3, 4]
Queue:    [5, 6, 7, 8, 9, 10]

Step 3:   Subtask 2 and 4 approved.
          Subtask 5 needs backend/db.py — currently locked by subtask 3.
          Spawn subtask 6 (no overlap), queue subtask 5.
Active:   [3, 6]
Queue:    [5, 7, 8, 9, 10]

...and so on.
```

**Manager's responsibility:**
- During decomposition, annotate each subtask with `files_to_modify`
- During execution, maintain the file ownership map
- Decide spawn order based on dependency + file conflict minimization
- If a subtask needs a locked file, queue it (don't block other subtasks)

#### 3.1.3 Mid-Task User Interrupt

**The problem:** If the Manager goes down the wrong path (2 subtasks deep),
the user is stuck waiting. No way to correct course.

**The solution:** User can send a message at any time. The Manager receives it
as an **interrupt** and must process it before continuing.

**Interrupt types:**
```json
{"type": "correction", "message": "Stop. Don't use that approach. Use X instead."}
{"type": "clarification", "message": "Also handle Y, I forgot to mention."}
{"type": "abort", "message": "Cancel this task entirely."}
{"type": "pause", "message": "Hold on. Let me think."}
```

**How it works:**
1. User sends a message while a task is in progress
2. Server injects the interrupt into the Manager's event queue
3. Manager checks for interrupts at the start of each step
4. On interrupt:
   - **correction** → Manager pauses active Devs, revises plan, re-spawns as needed
   - **clarification** → Manager adds to requirements, may create new subtasks
   - **abort** → Manager cancels all active Devs, marks task as cancelled
   - **pause** → Manager pauses spawning new subtasks, lets active ones finish
5. Manager streams its response to the user: "Got it. Adjusting plan..."
6. Active Dev agents that are mid-implementation are **not killed** — they finish
   their current step, then the Manager decides: keep their work or discard

**Implementation:** This is a priority queue in the orchestrator. User messages
have higher priority than agent events. The Manager's loop checks for interrupts
at every step boundary (between LLM calls).

#### 3.1.4 Merge Conflict Resolution

**The problem:** Even with file locking, sequential subtasks can produce
conflicting changes. Subtask 2 might add a function to `server.py` that
subtask 5 expects to exist but with a different signature.

**The solution:** The Manager runs an **integration review** after all subtasks
are complete.

```
All subtasks approved (individually)
    │
    ▼
Manager triggers INTEGRATION REVIEW
    │
    ▼
Reviewer sees the FULL cumulative diff (all subtasks combined)
Checks for:
  - Merge conflicts between subtask diffs
  - Inconsistent function signatures
  - Missing imports or references
  - Broken cross-file dependencies
    │
    ▼
If issues found:
  Manager creates a "fix integration issues" subtask
  Assigns to Dev with full context of what broke
  Reviewer reviews the fix
    │
    ▼
Final diff is clean → Manager triggers git push
```

**For cases where parallel Devs produce conflicting diffs:**
1. Manager detects the conflict (git merge --no-commit check)
2. Manager creates a **conflict resolution subtask** with:
   - Both diffs as context
   - Clear instructions on which changes take priority
   - The conflicting files
3. Single Dev resolves, Reviewer approves, Manager continues

---

### 3.2 Dev Agent

**Identity:** Senior developer. Receives a focused task. Implements it. Runs verification.

**Responsibilities:**
1. Read the relevant files (not the whole codebase)
2. Implement the assigned subtask
3. Run verification (tests, lint, build)
4. Report: status, diff, test results, any blockers

**Context it receives:**
- The specific subtask description
- List of files to read/modify
- Project conventions relevant to this task
- Constraints (e.g., "don't touch file X", "preserve backward compatibility")
- Reviewer feedback (if this is a revision cycle)
- **Summary of related subtasks** (what other Devs are building, so it doesn't break their work)

**Context it does NOT receive:**
- Other subtasks' full diffs or implementations
- Overall task decomposition details
- User's original request (irrelevant to focused implementation)

**Max steps:** 100 per subtask

**Termination conditions:**
- Implementation complete + verification passes → report done
- Blocked (missing info, dependency on another subtask) → report blocked
- Max steps exhausted → report partial progress

**Key design decision:** Each Dev agent gets a **fresh context window**.
No pollution from previous subtasks. Quality of subtask #20 = quality of subtask #1.

---

### 3.3 Reviewer Agent

**Identity:** Senior code reviewer. Skeptical by default. Its job is to find problems.

**Key difference from initial design:** The Reviewer has **memory across review rounds**.
It sees the full review history for the current subtask to catch regressions.

**Responsibilities:**
1. Read the diff (and only the diff + affected files for context)
2. Check against project standards
3. Look for: bugs, edge cases, missing error handling, style violations,
   security issues, performance problems, naming inconsistencies
4. **Compare against previous review rounds** — catch regressions
5. Return a structured verdict: APPROVE or REVISE with specific issues

**Context it receives:**
- The diff (unified diff format)
- The full content of changed files (for context around the diff)
- Project standards / conventions / anti-patterns
- The subtask description (what was requested)
- **Previous review rounds** (see §3.3.1)

**Context it does NOT receive:**
- How the implementation was done (no tool call history)
- Other subtasks' diffs
- User's original request

**Max steps:** 30 (read-only, no tool execution except file_read)

#### 3.3.1 Review Memory Across Rounds

**The problem:** If each review round is "fresh," the Reviewer can't detect
regressions. Round 1 approved the error handling. Round 2, the Dev "fixed"
a naming issue but accidentally removed the error handling. Fresh Reviewer
doesn't notice because it wasn't there in round 1.

**The solution:** Each review round includes the **full review history**.

```
Round 1 Review Context:
  - Current diff
  - Project standards
  - (No previous reviews)

Round 2 Review Context:
  - Current diff (updated)
  - Project standards
  - Round 1 verdict: APPROVE
  - Round 1 issues found: [list]
  - Round 1 diff (for comparison)

Round 3 Review Context:
  - Current diff (updated again)
  - Project standards
  - Round 1 verdict + issues + diff
  - Round 2 verdict + issues + diff
```

The Reviewer prompt explicitly says:
```markdown
# Regression Detection
You are seeing this subtask for review round N.
You have access to all previous review rounds.

IMPORTANT: Check that previous fixes haven't been undone.
If round 1 found and approved error handling on line 45,
verify it's still there in round 2.

Flag any REGRESSION as HIGH severity — things that were fixed but broke again.
```

**Storage:** Each review round is stored in the `subtasks` table as a JSON array:
```json
{
  "reviews": [
    {
      "round": 1,
      "verdict": "approve",
      "issues": [],
      "diff_snapshot": "--- a/..."
    },
    {
      "round": 2,
      "verdict": "revise",
      "issues": [{"severity": "high", "...": "..."}],
      "diff_snapshot": "--- a/..."
    }
  ]
}
```

#### 3.3.2 Cross-Subtask Awareness

**The problem:** Reviewer approves subtask 1 (adds `create_project()` to db.py).
Subtask 2 (API routes) uses `create_project()` with wrong args. Reviewer for
subtask 2 doesn't know the correct signature because it only sees subtask 2's diff.

**The solution:** The Manager provides the Reviewer with a **summary of approved
subtasks** that touch related files.

```
Manager → Reviewer (for subtask 2):
{
  "diff": "...",
  "changed_files": {...},
  "related_approved_subtasks": [
    {
      "subtask_id": "subtask-1",
      "title": "Add projects table",
      "files_modified": ["backend/db.py"],
      "key_changes": "Added create_project(name, emoji) → returns project dict. Added project_id column to configs/messages/runs."
    }
  ]
}
```

The Reviewer uses this to verify that subtask 2's usage of `create_project()`
matches the actual function signature from subtask 1.

---

## 4. LLM Configuration Per Role

Each role can use a **different LLM model**. This is configured in Settings.

```sql
-- In configs table
ALTER TABLE configs ADD COLUMN llm_manager_model TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_manager_url TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_manager_api_key TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_dev_model TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_dev_url TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_dev_api_key TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_reviewer_model TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_reviewer_url TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_reviewer_api_key TEXT DEFAULT '';
```

**Fallback behavior:**
- If role-specific model is empty → fall back to `llm1_url` / `llm1_model` / `llm1_api_key`
- This means existing configs work without changes — role-specific is optional

**Why different models per role:**
- Manager: needs strong reasoning + planning (e.g., Claude, GPT-4, DeepSeek-R1)
- Dev: needs strong code generation (e.g., DeepSeek-Coder, Claude, Codestral)
- Reviewer: needs strong analysis + attention to detail (e.g., GPT-4, Claude)
- Same model works fine too — the point is **configurability**

---

## 5. Data Model Changes

### 5.1 New Table: `tasks`

A task is the top-level unit of work — one user request.

```sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending | decomposing | validating | in_progress | reviewing | done | failed | cancelled
    user_message TEXT NOT NULL,
    plan TEXT DEFAULT '',
    -- Manager's decomposition plan (JSON array of subtask descriptors)
    validation_log TEXT DEFAULT '',
    -- Self-validation results (JSON)
    result_summary TEXT DEFAULT '',
    -- Manager's final report to user
    interrupt_queue TEXT DEFAULT '[]',
    -- JSON array of user interrupts pending processing
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
```

### 5.2 New Table: `subtasks`

A subtask is a unit of work assigned to a Dev agent.

```sql
CREATE TABLE IF NOT EXISTS subtasks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending | queued | assigned | implementing | reviewing | approved | revision_needed | failed
    sequence INTEGER NOT NULL,
    -- Order within the task (for sequential dependencies)
    title TEXT NOT NULL,
    -- Short description: "Add projects table schema"
    description TEXT NOT NULL,
    -- Full task description for the Dev agent
    files_to_modify TEXT DEFAULT '[]',
    -- JSON array of file paths the Dev should touch
    constraints TEXT DEFAULT '',
    -- Any constraints: "don't touch X", "preserve backward compat"
    depends_on TEXT DEFAULT '[]',
    -- JSON array of subtask_ids that must complete before this one starts
    diff TEXT DEFAULT '',
    -- Latest diff from Dev
    test_results TEXT DEFAULT '',
    -- Latest test/verification output
    reviews TEXT DEFAULT '[]',
    -- ALL review rounds (JSON array, not just latest) — for regression detection
    review_round INTEGER DEFAULT 0,
    -- How many review cycles so far
    max_review_rounds INTEGER DEFAULT 3,
    -- Cap to prevent infinite loops
    related_context TEXT DEFAULT '',
    -- Summary of approved subtasks that touch related files (for Reviewer)
    result TEXT DEFAULT '',
    -- Dev's final report
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 5.3 Modified Table: `runs`

Add task/subtask context so runs are traceable.

```sql
ALTER TABLE runs ADD COLUMN task_id TEXT DEFAULT '';
ALTER TABLE runs ADD COLUMN subtask_id TEXT DEFAULT '';
ALTER TABLE runs ADD COLUMN agent_role TEXT DEFAULT '';
-- 'manager' | 'dev' | 'reviewer'
```

### 5.4 Modified Table: `configs`

Add role-specific LLM config and swarm settings.

```sql
ALTER TABLE configs ADD COLUMN llm_manager_model TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_manager_url TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_manager_api_key TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_dev_model TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_dev_url TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_dev_api_key TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_reviewer_model TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_reviewer_url TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN llm_reviewer_api_key TEXT DEFAULT '';
ALTER TABLE configs ADD COLUMN swarm_enabled INTEGER DEFAULT 0;
ALTER TABLE configs ADD COLUMN swarm_max_concurrency INTEGER DEFAULT 3;
ALTER TABLE configs ADD COLUMN swarm_max_review_rounds INTEGER DEFAULT 3;
ALTER TABLE configs ADD COLUMN project_standards TEXT DEFAULT '';
```

### 5.5 Entity Relationships

```
User Request
    │
    ▼
Task (1)
    │
    ├── Subtask (1)  ←→  Run (dev)     ←→  Run Events
    │                        ↕
    │                   Run (reviewer)  ←→  Run Events
    │                   (may be multiple rounds)
    │
    ├── Subtask (2)  ←→  Run (dev)     ←→  Run Events
    │                        ↕
    │                   Run (reviewer)  ←→  Run Events
    │
    └── Subtask (3)  [queued — waiting for subtask 1 file lock]
```

---

## 6. Workflow State Machine

### 6.1 Task Lifecycle

```
USER_REQUEST
    │
    ▼
DECOMPOSING  ←── Manager analyzing, creating subtasks
    │
    ▼
VALIDATING   ←── Manager self-validates the plan
    │
    ├── (validation fails) ──→ DECOMPOSING (re-plan, max 2 rounds)
    │
    ▼
IN_PROGRESS  ←── Subtasks being executed (max 3 concurrent)
    │
    ├── (user interrupt: abort) ──→ CANCELLED
    │
    ├── (user interrupt: correction) ──→ re-plan → IN_PROGRESS
    │
    ├── (all subtasks approved)
    │       │
    │       ▼
    │   INTEGRATION_REVIEW  ←── Reviewer sees full cumulative diff
    │       │
    │       ├── (issues found) ──→ fix subtask → re-review
    │       │
    │       └── (clean) ──→ git push → DONE
    │
    └── (unrecoverable failure) ──→ FAILED
```

### 6.2 Subtask Lifecycle

```
PENDING
    │
    ▼
QUEUED  ←── Waiting for file locks / dependencies
    │
    ├── (files available + concurrency < 3)
    │       │
    │       ▼
    │   ASSIGNED  ←── Manager spawned Dev
    │       │
    │       ▼
    │   IMPLEMENTING  ←── Dev writing code, running verification
    │       │
    │       ├── (implementation done + verification passed)
    │       │       │
    │       │       ▼
    │       │   REVIEWING  ←── Reviewer reading diff
    │       │       │
    │       │       ├── (APPROVE) ──→ APPROVED  ←── release file locks
    │       │       │
    │       │       └── (REVISE)
    │       │               │
    │       │               ▼
    │       │       REVISION_NEEDED  ←── Manager sends feedback to Dev
    │       │               │
    │       │               └── (review_round < max) ──→ IMPLEMENTING (loop)
    │       │                       │
    │       │                       └── (review_round >= max)
    │       │                               │
    │       │                               ▼
    │       │                       FORCE_APPROVED  ←── Manager overrides
    │       │                       (with warnings in summary)
    │       │
    │       ├── (Dev blocked) ──→ BLOCKED  ←── Manager resolves or escalates
    │       │
    │       └── (max steps exhausted) ──→ FAILED
    │
    └── (dependency failed) ──→ FAILED
```

### 6.3 User Interrupt Flow

```
User sends message while task is in progress
    │
    ▼
Server adds to task's interrupt_queue
    │
    ▼
Manager checks interrupt_queue at next step boundary
    │
    ├── "abort" → cancel all active Devs → task CANCELLED
    │
    ├── "pause" → stop spawning new subtasks → let active finish → task PAUSED
    │
    ├── "correction" →
    │       1. Pause active Devs (let current step finish)
    │       2. Read user's correction
    │       3. Re-evaluate plan: adjust remaining subtasks
    │       4. May discard uncommitted work from active subtasks
    │       5. Resume with updated plan
    │
    └── "clarification" →
            1. Add to requirements
            2. May create new subtasks
            3. Continue with expanded scope
```

---

## 7. System Prompts Per Role

### 7.1 Manager Prompt (Composed)

```markdown
# Identity
You are the Manager — the technical orchestrator of Kaptaan.
You NEVER write code. You NEVER review code directly.
You think, plan, decompose, coordinate, and decide.

# Workflow
For every user request:
1. UNDERSTAND — Clarify the user's intent. Read the project structure.
2. PLAN — Decompose into logical subtasks.
3. SELF-VALIDATE — Check your plan against the validation checklist.
4. EXECUTE — Assign subtasks to Dev. Manage concurrency (max 3).
5. REVIEW — Send Dev output to Reviewer. Process feedback.
6. INTEGRATE — Run integration review on full cumulative diff.
7. REPORT — Summarize what was done, what was verified, any warnings.

# Decomposition Rules
- Each subtask must be focused on ONE concern.
- Each subtask must list specific files to modify.
- Each subtask must have clear acceptance criteria.
- Order subtasks: foundations first, features second, integration last.
- If subtasks share files, they MUST be sequential (never parallel).
- Max 5 files per subtask. If more, decompose further.

# Self-Validation Checklist
Before executing, validate your plan:
□ Does the plan cover ALL aspects of the user's request?
□ Can each subtask be implemented independently?
□ Are dependency orderings correct?
□ Are there file conflicts between parallel subtasks?
□ Is each subtask description unambiguous?
□ Can each subtask be independently tested?

If any check fails, revise the plan and re-validate (max 2 rounds).

# Concurrency Management
- Max 3 Dev agents running simultaneously.
- Track file ownership: each active Dev "locks" its files.
- If a subtask needs a locked file, queue it (don't block others).
- Optimize spawn order to minimize queue wait time.

# Mid-Task Interrupts
- Check for user interrupts at every step.
- Process interrupts immediately — don't wait for current subtask.
- On "correction": pause, re-plan, adjust.
- On "abort": cancel everything, report status.
- Always acknowledge the interrupt to the user.

# Quality Gates
- Every subtask must pass review before moving to the next.
- After all subtasks: run integration review on full diff.
- If integration review finds issues: create fix subtask, then re-review.
- Only git push after integration review passes.

# Communication
- Stream progress to user after each subtask completes.
- If the task is ambiguous, ask the user BEFORE decomposing.
- Be concise. Show: plan, progress, results. No internal agent chatter.
```

### 7.2 Dev Prompt (Composed)

```markdown
# Identity
You are a senior developer in the Kaptaan team.
You implement focused tasks. You write clean, production-quality code.
You verify your own work before declaring done.

# Workflow
For every subtask:
1. READ — Read the files you need to modify. Understand the existing code.
2. IMPLEMENT — Write the code. Follow project conventions.
3. VERIFY — Run tests, lint, build. Fix any failures.
4. REPORT — Submit your diff and verification results.

# Rules
- Only modify the files listed in your task. Don't touch anything else.
- If you need to modify additional files, report BLOCKED and explain why.
- Write tests for every change. If no test framework exists, say so.
- Handle errors explicitly. No bare except. No silent failures.
- Follow existing code patterns. Match the style of surrounding code.
- If verification fails, fix it before reporting done. Never ship broken code.

# Revision Rules
If you receive reviewer feedback:
- Fix every HIGH and MEDIUM issue.
- Address LOW issues if trivially fixable.
- Do NOT introduce new changes unrelated to the feedback.
- Re-verify after fixes.

# Anti-Patterns (NEVER do these)
- {loaded from project standards}
- No print() for logging
- No hardcoded secrets
- No catch-all exception handlers
- No unused imports
- No TODO comments in shipped code

# Output
When done, report:
- Status: done / blocked / failed
- Summary: what you changed and why
- Files modified: list
- Verification: what you ran and the results
```

### 7.3 Reviewer Prompt (Composed)

```markdown
# Identity
You are a senior code reviewer. Your job is to find problems.
You are skeptical by default. You approve only when code meets production standards.
You have never seen the implementation process — only the final diff.

# Workflow
For every review:
1. READ — Read the diff and the full content of changed files.
2. COMPARE — If previous review rounds exist, check for regressions.
3. ANALYZE — Check against the criteria below.
4. VERDICT — Approve or Revise with specific, actionable feedback.

# Review Criteria
## Correctness
- Does the code do what the task description says?
- Are edge cases handled?
- Are error paths handled explicitly?

## Code Quality
- Naming: clear, consistent, no abbreviations
- Functions: single responsibility, reasonable length
- No dead code, no unused variables
- No code duplication

## Security
- No hardcoded secrets
- Input validation present
- No SQL injection, no command injection
- Proper auth checks

## Testing
- Are there tests for the changes?
- Do tests cover happy path AND error paths?
- Are tests actually assertions (not just "runs without crashing")?

## Cross-Subtask Compatibility
- If related_approved_subtasks are provided, verify this subtask's
  usage of shared interfaces matches (function signatures, data shapes).
- Check that this subtask doesn't break code from approved subtasks.

## Project Standards
- {loaded from project settings — conventions, patterns, anti-patterns}

## Regression Detection (Round 2+)
- Compare current diff against previous review round's diff.
- If something was approved in a previous round but is now broken,
  flag as HIGH severity regression.
- Check that requested fixes were actually implemented (not just claimed).

# Output Format
Return a JSON object with:
- verdict: "approve" or "revise"
- summary: one-line summary of the review
- regressions_found: boolean
- issues: array of {severity, file, line_range, description, suggestion, regression}

Severity levels:
- HIGH: bugs, security issues, data loss risks, regressions → always blocks
- MEDIUM: missing error handling, code quality violations → blocks
- LOW: style, naming, minor improvements → informational only

# Rules
- Be specific. "This is bad" is useless. "Line 45: no try/except around HTTP call" is useful.
- Always provide a suggestion, not just a complaint.
- If you find zero issues, say APPROVE — don't invent problems.
- Review the diff, not the developer. Be professional.
```

---

## 8. Tool Access Per Role

### Manager — Orchestration Tools

| Tool | Access | Why |
|------|--------|-----|
| `file_read` | ✅ | Read project structure, configs |
| `shell_exec` | ❌ | Doesn't execute code |
| `file_write` | ❌ | Doesn't write code |
| `git_*` | ❌ | Doesn't interact with git directly |
| `memory_read` | ✅ | Load project context |
| `memory_update` | ✅ | Update project standards (auto-extracted) |
| `scratchpad_read/write` | ✅ | Track decomposition plan |
| `web_search` | ✅ | Research if needed |
| `spawn_dev` | ✅ | **NEW** — spawn a Dev agent for a subtask |
| `spawn_reviewer` | ✅ | **NEW** — spawn a Reviewer agent |
| `get_subtask_status` | ✅ | **NEW** — check subtask progress |
| `send_to_user` | ✅ | **NEW** — report progress to user |
| `trigger_integration_review` | ✅ | **NEW** — final review of full diff |
| `git_push` | ✅ | **Only** after integration review passes |

### Dev — Full Implementation Tools

| Tool | Access | Why |
|------|--------|-----|
| `file_read` | ✅ | Read code |
| `file_write` | ✅ | Write code |
| `shell_exec` | ✅ | Run tests, install deps, build |
| `git_status/diff/log` | ✅ | Check git state |
| `git_commit` | ✅ | Commit changes |
| `git_push` | ❌ | Only Manager triggers final push |
| `memory_read` | ✅ | Load project context |
| `scratchpad_read/write` | ✅ | Track implementation plan |
| `web_search/url_fetch` | ✅ | Research if needed |
| `vps_exec` | ❌ | No VPS access from Dev |
| `http_request` | ✅ | API calls if needed |

### Reviewer — Read-Only Tools

| Tool | Access | Why |
|------|--------|-----|
| `file_read` | ✅ | Read code for context |
| `file_write` | ❌ | Never modifies code |
| `shell_exec` | ❌ | Never executes commands |
| `git_diff` | ✅ | Read the diff |
| `git_status/log` | ✅ | Check git state |
| `git_commit/push` | ❌ | Never touches git |
| `memory_read` | ✅ | Load project standards |
| `scratchpad_read` | ✅ | Read-only access |
| `web_search` | ❌ | Not needed for review |

---

## 9. Project Standards — Dual Source

Project standards come from **two sources** and are merged:

### 9.1 User-Configured (Manual)

In Settings → Project Standards textarea. The user writes rules:

```markdown
## Code Style
- Use type hints everywhere
- 4 spaces indentation
- Max function length: 50 lines

## Architecture
- Routes → Services → Repositories → DB
- Never raw SQL in routes
- All async functions handle cancellation

## Testing
- pytest with 80% coverage target
- Test happy path + error path for every endpoint
```

### 9.2 Auto-Extracted (Agent-Maintained)

The Manager can update project standards by observing patterns in the codebase:

```markdown
# Auto-extracted (Manager updates this)
## Observed Patterns
- Database: aiosqlite, raw SQL, migrations in init_db()
- Auth: bcrypt + httpOnly cookies
- Frontend: Svelte 5 with $state/$derived runes
- API: FastAPI with Pydantic models

## Observed Anti-Patterns (to avoid)
- [from Reviewer feedback across tasks]
```

The Manager calls `memory_update` to evolve these standards after each task.
Over time, the standards become project-specific and increasingly accurate.

### 9.3 Merged Prompt

Both sources are injected into Dev and Reviewer prompts:

```
[User-configured standards]
[Auto-extracted patterns]
[Auto-extracted anti-patterns from past reviews]
```

---

## 10. Communication Protocol

### 10.1 Manager → Dev Message Format

```json
{
  "subtask_id": "uuid",
  "title": "Add projects table and migration",
  "description": "Create a new `projects` table with id, name, emoji, created_at, updated_at. Add project_id column to configs, messages, and runs tables. Write idempotent migration logic in init_db().",
  "files_to_modify": ["backend/db.py"],
  "constraints": [
    "Migration must be idempotent — safe to run multiple times",
    "Don't drop existing data",
    "Default project should be auto-created for existing installs"
  ],
  "project_conventions": "Use aiosqlite. All migrations go in init_db(). Use PRAGMA table_info to check existing columns before ALTER TABLE.",
  "related_subtasks_summary": [
    "Subtask 2 (API routes) will call create_project() — ensure it returns a dict with id, name, emoji"
  ],
  "review_feedback": null
}
```

### 10.2 Dev → Manager Response Format

```json
{
  "subtask_id": "uuid",
  "status": "done",
  "summary": "Added projects table with 5 columns. Added project_id FK to configs, messages, runs.",
  "files_modified": ["backend/db.py"],
  "diff": "--- a/backend/db.py\n+++ b/backend/db.py\n...",
  "verification": {
    "tests_ran": true,
    "tests_passed": true,
    "output": "7/7 tests passed"
  },
  "blockers": null
}
```

### 10.3 Manager → Reviewer Message Format

```json
{
  "subtask_id": "uuid",
  "task_description": "Add projects table and migration",
  "diff": "--- a/backend/db.py\n+++ b/backend/db.py\n...",
  "changed_files": {
    "backend/db.py": "<full file content>"
  },
  "project_standards": "...",
  "previous_reviews": [],
  "related_approved_subtasks": [
    {
      "subtask_id": "subtask-0",
      "title": "Update configs table",
      "files_modified": ["backend/db.py"],
      "key_changes": "Added sandbox_cpu, sandbox_memory, sandbox_disk columns"
    }
  ]
}
```

### 10.4 Reviewer → Manager Response Format

```json
{
  "subtask_id": "uuid",
  "verdict": "revise",
  "summary": "Missing index on project_id column. No rollback handling.",
  "regressions_found": false,
  "issues": [
    {
      "severity": "medium",
      "file": "backend/db.py",
      "line_range": "55-60",
      "description": "ALTER TABLE adds project_id but no index. Queries filtering by project_id will be slow.",
      "suggestion": "Add CREATE INDEX IF NOT EXISTS idx_configs_project ON configs(project_id)",
      "regression": false
    }
  ]
}
```

---

## 11. Frontend — User Visibility

### 11.1 What the User Sees

The user sees **only Manager commentary + subtask cards**. No Dev tool calls,
no Reviewer internals, no raw diffs.

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│ [MANAGER] Analyzing your request...                 │
│                                                     │
│ [MANAGER] This requires 4 changes:                  │
│   1. Database schema (projects table + migrations)  │
│   2. API layer (project CRUD + scope endpoints)     │
│   3. Frontend (project sidebar + switcher)          │
│   4. Integration (wire everything, test)            │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ✓ 1. Database schema                            │ │
│ │   Passed review (round 1) • 7/7 tests passed   │ │
│ ├─────────────────────────────────────────────────┤ │
│ │ ⟳ 2. API endpoints                              │ │
│ │   Implementing... (step 12/100)                 │ │
│ ├─────────────────────────────────────────────────┤ │
│ │ ○ 3. Frontend project switcher                  │ │
│ │   Waiting (depends on #2)                       │ │
│ ├─────────────────────────────────────────────────┤ │
│ │ ○ 4. Integration                                │ │
│ │   Waiting (depends on #2, #3)                   │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ [MANAGER] Working on subtask 2...                   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 10.2 Subtask Card States

| State | Icon | Detail shown |
|-------|------|-------------|
| Pending | ○ | "Waiting" or "Waiting (depends on #N)" |
| Queued | ◐ | "Queued — waiting for file lock" |
| Implementing | ⟳ | "Implementing... (step N/M)" |
| Reviewing | ◎ | "Under review (round N)" |
| Revision needed | ↻ | "Revision needed — [issue summary]" |
| Approved | ✓ | "Passed review • test results" |
| Failed | ✗ | "Failed — [reason]" |
| Force approved | ⚠ | "Approved with warnings — [warning]" |

### 11.3 SSE Event Types

```json
{"type": "manager_commentary", "text": "Analyzing request..."}
{"type": "task_created", "task_id": "...", "plan": [...]}
{"type": "validation_result", "passed": true, "notes": ""}
{"type": "subtask_queued", "subtask_id": "...", "title": "...", "depends_on": [...]}
{"type": "subtask_started", "subtask_id": "...", "title": "..."}
{"type": "subtask_progress", "subtask_id": "...", "step": 12, "max": 100}
{"type": "subtask_reviewing", "subtask_id": "...", "round": 1}
{"type": "subtask_approved", "subtask_id": "...", "review_summary": "..."}
{"type": "subtask_revision", "subtask_id": "...", "issues": [...]}
{"type": "subtask_failed", "subtask_id": "...", "reason": "..."}
{"type": "integration_review_started"}
{"type": "integration_review_passed"}
{"type": "integration_review_failed", "issues": [...]}
{"type": "task_completed", "task_id": "...", "summary": "..."}
{"type": "task_failed", "task_id": "...", "reason": "..."}
{"type": "task_cancelled", "task_id": "..."}
{"type": "user_interrupt_received", "message": "..."}
```

---

## 12. Integration With Current Codebase

### 12.1 Files to Create

```
backend/
├── swarm/
│   ├── __init__.py
│   ├── orchestrator.py    ← Manager agent loop
│   ├── worker.py          ← Dev agent loop
│   ├── reviewer.py        ← Reviewer agent loop
│   ├── prompts.py         ← Composed system prompts per role
│   ├── protocol.py        ← Message formats, validation
│   ├── concurrency.py     ← File locking, spawn queue, max concurrency
│   └── config.py          ← Swarm constants (max rounds, max steps, etc.)
```

### 12.2 Files to Modify

| File | Change |
|------|--------|
| `backend/db.py` | Add `tasks`, `subtasks` tables. Add columns to `runs`, `configs`. |
| `backend/server.py` | New endpoints. Modify `/api/message`. Add interrupt injection. |
| `backend/agent.py` | Keep as-is (becomes the worker loop base). |
| `backend/tools.py` | Add role-based filtering. New tools: spawn_dev, spawn_reviewer, etc. |
| `frontend/src/lib/stores.js` | Track task + subtask state. Handle interrupt UI. |
| `frontend/src/components/Chat.svelte` | Show task progress cards. |
| `frontend/src/components/Settings.svelte` | Role-specific LLM config. Swarm toggle. Project standards. |

### 12.3 New API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/message` | POST | **Modified** — creates a Task in swarm mode |
| `/api/tasks` | GET | List all tasks with status |
| `/api/task/{id}` | GET | Get task details + subtasks |
| `/api/task/{id}/stream` | SSE | Stream all events (manager commentary + subtask cards) |
| `/api/task/{id}/cancel` | POST | Cancel a running task |
| `/api/task/{id}/interrupt` | POST | Send interrupt to running task |

### 12.4 Backward Compatibility

Swarm mode is behind a feature flag. Single-agent mode remains as default.

```python
SWARM_ENABLED = cfg.get("swarm_enabled", 0)  # 0 = off, 1 = on
```

---

## 13. Edge Cases & Failure Modes

| Scenario | Detection | Mitigation |
|----------|-----------|------------|
| **Bad decomposition** | Self-validation step catches: missing coverage, ambiguous tasks, hidden deps | Manager rewrites plan (max 2 validation rounds) |
| **Infinite review loop** | `review_round >= max_review_rounds` | Manager force-approves or escalates to user |
| **Reviewer regression blindness** | Review history carried across rounds | Reviewer explicitly checks round-over-round diffs |
| **Dev introduces regression** | Reviewer compares against previous approved diff | Flagged as HIGH severity regression |
| **File conflict between parallel Devs** | File ownership map + concurrency manager | Sequential execution for overlapping files |
| **Merge conflict after sequential subtasks** | Integration review detects | Manager creates fix subtask |
| **User goes wrong direction** | User interrupt (correction) | Manager pauses, re-plans, adjusts |
| **User wants to abort** | User interrupt (abort) | Manager cancels everything |
| **Dev modifies files outside scope** | Reviewer checks diff against `files_to_modify` | HIGH severity; Manager reassigns |
| **Subtask depends on another** | Manager detects during decomposition | Ordered execution, dependency tracking |
| **Dev can't understand task** | Dev reports BLOCKED | Manager rewrites with more specificity |
| **Reviewer too strict** | Only LOW issues but verdict REVISE | Manager overrides after 2 rounds of only LOW |
| **Context overflow** | Manager decomposes into smaller subtasks | ≤5 files per subtask |
| **LLM returns garbage** | Empty/malformed response | Retry max 3 times per LLM call |
| **Sandbox dies mid-task** | Tool error | Manager pauses, recreates sandbox, resumes |
| **Max concurrency starvation** | Queue analysis | Manager reorders to minimize wait |
| **Cross-subtask interface mismatch** | Integration review + Reviewer cross-subtask awareness | Manager provides related subtask summaries |

---

## 14. Implementation Phases

### Phase 1: Data Model + Orchestrator Skeleton + User Interrupt
**Effort:** ~1.5 days

- Add `tasks` and `subtasks` tables to `db.py`
- Add `task_id`, `subtask_id`, `agent_role` columns to `runs`
- Add role-specific LLM columns + swarm settings to `configs`
- Create `backend/swarm/` directory structure
- Implement `orchestrator.py` — Manager agent loop (skeleton)
- Implement decomposition with self-validation
- Implement user interrupt handling (abort, pause, correction, clarification)
- Task creation and status tracking
- **No actual Dev/Reviewer yet** — Manager just plans and reports

**Exit criteria:** User sends message → Manager decomposes → self-validates → reports plan.
User can interrupt mid-plan. Subtasks show in DB.

### Phase 2: Worker Agent + Concurrency Manager
**Effort:** ~1.5 days

- Extract current `run_agent()` logic into `worker.py`
- Add role-based tool filtering (Dev gets full tools, no push)
- Implement `concurrency.py` — file locking, spawn queue, max 3 concurrency
- Worker receives structured task, returns structured response
- Orchestrator spawns worker runs respecting concurrency limits
- File ownership tracking

**Exit criteria:** Manager spawns Dev for a subtask → Dev implements → diff generated.
Max 3 concurrent Devs. File conflicts cause sequential execution.

### Phase 3: Reviewer Agent + Review Memory
**Effort:** ~1 day

- Implement `reviewer.py` — read-only agent loop
- Reviewer receives diff + changed files + standards + review history
- Returns structured verdict with regression detection
- Wire up: Dev finishes → Reviewer reviews → verdict back to Manager
- Manager processes verdict: approve or send back to Dev
- Cross-subtask awareness (related_approved_subtasks)

**Exit criteria:** Full cycle: Manager → Dev → Reviewer → Manager.
Review feedback flows back. Regression detection works.

### Phase 4: Integration Review + Merge Conflict Resolution
**Effort:** ~1 day

- Implement integration review after all subtasks complete
- Full cumulative diff reviewed by Reviewer
- Merge conflict detection (git merge --no-commit)
- Manager creates fix subtask for integration issues
- Final git push after integration review passes

**Exit criteria:** All subtasks approved → integration review → clean diff → git push.
Merge conflicts detected and resolved.

### Phase 5: Frontend + Multi-LLM Config + Project Standards
**Effort:** ~1.5 days

- New SSE event types for swarm progress
- Task progress UI (subtask cards with all states)
- Manager commentary stream
- Settings: role-specific LLM config (Manager/Dev/Reviewer models)
- Settings: swarm toggle, max concurrency, max review rounds
- Settings: project standards editor
- Feature flag in Settings (enable/disable swarm mode)
- Auto-extraction of project standards from codebase patterns

**Exit criteria:** Full UI: plan view, subtask cards, manager commentary.
User can configure LLM per role. Project standards editable.

### Phase 6: Quality Tuning + Few-Shot Learning
**Effort:** ~1 day

- Tune decomposition with few-shot examples per project type
- Tune review strictness (severity thresholds)
- Calibrate max steps per role based on real task testing
- Optimize token usage (context window management)
- Add few-shot example library (extendable per project)
- Test with 10+ real tasks to measure quality improvement

**Exit criteria:** Agent output quality measurably better than single-agent mode.
First-attempt correctness >90%. Review feedback is actionable.

---

## 15. Open Questions

| Question | Current Decision | Revisit When |
|----------|-----------------|--------------|
| **Same LLM per role or different?** | Configurable per role, fallback to global | Phase 5 |
| **User sees Dev tool calls?** | No — only Manager commentary + subtask cards | Phase 5 |
| **Can user configure max concurrency?** | Yes, in Settings (default 3) | Phase 5 |
| **Subtask rollback on failure?** | No rollback — partial progress stays. Manager decides next steps. | Phase 4 |
| **How does Manager learn from past tasks?** | Auto-extracts patterns into project standards after each task | Phase 6 |
| **Few-shot examples per project?** | User can add custom examples in project standards | Phase 6 |

---

## 16. Summary

**Current state:** One agent does everything. No separation of concerns.
Quality limited by single-context-window, self-review, no verification gates.

**Target state:** Three-role swarm — Manager orchestrates, Dev implements,
Reviewer adversarially reviews. Each role has focused context, clear responsibilities,
and appropriate tool access.

**Key architectural decisions:**
- Decomposition self-validation before execution
- Review memory across rounds (regression detection)
- User interrupts at any point (correction, abort, pause)
- Max 3 concurrent Devs with file-level locking
- Integration review after all subtasks complete
- Role-specific LLM configuration
- Manager commentary + subtask cards only (clean UX)
- Project standards from both user and auto-extraction

**The core insight:** The agent doesn't need to be smarter. It needs better process.
Plan → Build → Verify → Review → Ship. Not as suggestions. As mandatory gates.

---

*This document is a living plan. Update as decisions are made and implementation progresses.*
