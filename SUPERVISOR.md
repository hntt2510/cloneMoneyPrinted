# Autonomous GitHub → Antigravity Supervisor (G11)

The **Autonomous GitHub → Antigravity Supervisor** establishes an unattended development control plane where GitHub Issues serve as a durable, machine-readable work queue and a local supervisor process executes coding jobs, enforces strict quality assurance (QA), and manages Git integration.

---

## 1. Overview & Architecture

```mermaid
flowchart TD
    GH[GitHub Issue #123 (agent:queued)] -->|Poll / GitHub API| SUP[Local Supervisor Loop]
    SUP -->|1. Atomic Claim| CLAIM[agent:claimed]
    SUP -->|2. Verify Ancestry & Branch| GIT[Git Working Tree]
    SUP -->|3. Dispatch Coding Agent| AGENT[Antigravity CLI (agy)]
    AGENT -->|Code Changes| GIT
    SUP -->|4. Independent QA Enforcement| QA[QARunner]
    QA -->|Fail| FIX[FIXING Loop (Max 3 retries)]
    FIX --> AGENT
    QA -->|Pass| MERGE[Merge --no-ff to main]
    MERGE --> MAIN_QA[Main QA Validation]
    MAIN_QA -->|Pass| PUSH[Push origin main]
    PUSH --> REPORT[GitHub Status Comment + agent:done]
```

### Key Principles
- **No GUI Automation**: The supervisor never simulates mouse clicks or keypresses against IDE windows. It uses programmatic CLI/API dispatch.
- **Truthful QA**: Textual `PASS` declarations from coding models are ignored. All checks must execute and exit with code `0`.
- **Zero Force Push**: Force pushes (`--force`, `-f`, `--force-with-lease`) are blocked at both configuration and git invocation levels.
- **Durable State**: Supervisor state is saved to `.agents/state/<job_id>.json` on every state transition.

---

## 2. Installation & Prerequisites

1. **Python Environment**:
   ```bash
   uv sync
   # Active interpreter: .venv/Scripts/python.exe (Windows) or .venv/bin/python (POSIX)
   ```

2. **Antigravity CLI (Non-interactive Agent Runner)**:
   Ensure `agy` is installed and available in your `PATH`:
   ```bash
   agy --version
   ```

3. **Node.js & GitHub MCP Server (Optional for MCP integration)**:
   ```bash
   npx -y @modelcontextprotocol/server-github
   ```

---

## 3. Configuration Reference (`.agents/orchestrator.yaml`)

```yaml
allowed_repo: "hntt2510/cloneMoneyPrinted"
allowed_base_branch: "main"
allow_push_main: true
allow_force_push: false
max_parallel_jobs: 1
polling_interval_s: 30
required_labels:
  - "agent:queued"
stop_labels:
  - "agent:cancelled"
qa_commands:
  - "python -m compileall app test"
  - "python -m unittest discover -s test"
  - "uv lock --check"
  - "git diff --check"
working_directory: "D:\\HOCTAP\\latvat\\REUP-ANTROM\\MoneyPrinterTurbo"
state_directory: ".agents/state"
log_directory: ".agents/logs"
trusted_github_actors:
  - "hntt2510"
```

| Field | Type | Description |
|---|---|---|
| `allowed_repo` | `str` | Only execute tasks targeting this repository |
| `allowed_base_branch` | `str` | Permitted base branch to branch from and merge into |
| `allow_push_main` | `bool` | Whether to automatically push merged main to remote |
| `allow_force_push` | `bool` | Must be `false`. Invariant enforced by `SupervisorLoop` |
| `polling_interval_s` | `int` | Interval between GitHub API queue poll cycles |
| `required_labels` | `list[str]` | Label indicating a job is ready for claim |
| `stop_labels` | `list[str]` | Labels triggering immediate job cancellation |
| `qa_commands` | `list[str]` | Mandatory checks executed after coding and after merge |
| `trusted_github_actors` | `list[str]` | GitHub usernames authorized to submit jobs |

---

## 4. MCP Configuration (`.agents/mcp_config.json`)

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

---

## 5. Job Specification Schema

Jobs are defined in GitHub Issues using YAML frontmatter followed by markdown sections:

```markdown
---
agent_job_version: "1.0"
repo: "hntt2510/cloneMoneyPrinted"
goal_id: "G11"
base_sha: "0c391a39406ddcbc163798d3b6360b749f8184dc"
branch: "feature/autonomous-github-supervisor"
merge_to: "main"
merge_mode: "no-ff"
auto_push_main: true
stop_after: "independent_review"
---

## Objective
Implement autonomous supervisor for unattended task execution.

## Scope
- GitHub API client
- State machine persistence
- QA verification runner
- Git enforcer

## Non-Goals
- GUI automation
- Interactive human prompt loops

## Acceptance Criteria
- 16+ unit tests passing
- Smoke test passing on disposable git repository fixture

## QA Commands
- python -m compileall app test
- python -m unittest discover -s test
- uv lock --check
- git diff --check
```

---

## 6. State Machine & Lifecycle

```
QUEUED ──► CLAIMED ──► CODING ──► QA ─────────┬──► MERGING ──► MAIN_QA ──► PUSHING ──► REPORTING ──► DONE
               │                  ▲  │        │
               │                  │  ▼        │
               │                  └──FIXING   │
               │                               ▼
               └──────────────────────────► BLOCKED / CANCELLED
```

### State Definitions
- `QUEUED`: Issue exists on GitHub with label `agent:queued`.
- `CLAIMED`: Supervisor acquired the job lease, labeled `agent:claimed`.
- `CODING`: Coding agent dispatched with `CodingBrief`.
- `QA`: Independent execution of `QARunner`.
- `FIXING`: Bounded repair loop (up to 3 attempts) if QA fails.
- `MERGING`: Fast-forward prohibited (`git merge --no-ff`).
- `MAIN_QA`: Rerun full regression suite on merged target branch.
- `PUSHING`: Push to origin and verify SHA match.
- `REPORTING`: Post final status comment to GitHub issue.
- `DONE`: Task completed; label updated to `agent:done`.
- `BLOCKED`: Unrecoverable failure, base SHA mismatch, or QA retry limit exhausted.
- `CANCELLED`: `agent:cancelled` label detected; supervisor halted safely.

---

## 7. Security Boundaries & Invariants

1. **Untrusted Author Rejection**: Issues authored by users not in `trusted_github_actors` are ignored.
2. **Credential Sanitization**: Bearer tokens, GitHub PATs, and URL credentials are redacted (`***REDACTED***`) before writing to logs or GitHub comments.
3. **No Force Push**: Invocation of `git push --force` or `-f` raises `GitEnforcerError`.
4. **Safe Subprocess Execution**: All shell commands are executed as parameter lists (`shell=False`).
5. **Kill Switch**: If `agent:cancelled` is placed on the issue at any point, the supervisor aborts immediately before subsequent git modifications.
