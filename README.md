# DevLoopAI

DevLoopAI is a local-first AI coding assistant built around a conservative safety pipeline. Sprint 1 establishes the foundation for inspecting projects, planning changes, reviewing and validating plans, previewing exact diffs, applying tightly controlled text-file changes, verifying them with allowlisted checks, rolling back from snapshots, and creating an audited local Git commit.

It is designed to run with a Next.js frontend, a FastAPI backend, and Ollama as the local model provider. The frontend never talks directly to Ollama.

## Architecture

```text
Next.js frontend
  -> FastAPI API
  -> workflow and agent services
  -> execution safety layer
  -> Ollama
```

Important backend layers:

- Workspace service: safe local project opening, listing, context summaries, and text-file reads.
- Agents: Planner, Reviewer, Validator, and zero-write Coder dry-run/diff proposal.
- Planning workflow: Planner -> Reviewer -> Validator with persisted approval history.
- Execution safety layer: preflight, handoff, dry-run, diff review, controlled apply, rollback, verification, quality gate, recovery, and Git audit.
- SQLite stores: planning workflows, task sessions, attempts, diff reviews, executions, verifications, Git commits, and recovery state.

## Current Coding Workflow

```text
Task
  -> Context
  -> Planner
  -> Reviewer
  -> Validator
  -> Plan Approval
  -> Preflight
  -> Handoff
  -> Dry Run
  -> Diff
  -> Execution Approval
  -> Apply
  -> Verification
  -> Quality
  -> Retry or Rollback when needed
  -> Controlled Git Commit
```

Planning approval and execution approval are separate. Approving a plan never authorizes file mutation. The user must explicitly apply the exact reviewed diff before project files can change.

## Quick Start on Windows

Double-click `start-devloopai.bat` from the repository root.

The launcher:

- starts the FastAPI backend in a separate terminal window using `backend\.venv\Scripts\python.exe`;
- starts the Next.js frontend in a separate terminal window with `npm run dev`;
- waits briefly, then opens `http://localhost:3000`;
- resolves paths relative to the batch file, so it works when the repository is cloned to another folder.

If port `8000` or `3000` is already in use, the launcher leaves that existing process alone instead of starting a duplicate.

## Setup

### Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

If dependencies need to be installed in a fresh environment:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Backend configuration uses `DEVLOOPAI_` environment variables. The default local database path is `backend/data/devloopai.sqlite3`. Runtime data and snapshots are intentionally ignored by Git.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

For production checks:

```powershell
cd frontend
npm run lint
npm run build
```

Set `NEXT_PUBLIC_API_BASE_URL` if the FastAPI backend is not running at the default local URL.

### Ollama

Install and run Ollama locally, then pull the configured model:

```powershell
ollama pull qwen2.5-coder:7b
```

The model may be stored outside the C drive by setting `OLLAMA_MODELS`, for example:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\OllamaModels", "User")
$env:OLLAMA_MODELS = "D:\OllamaModels"
```

## Testing

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall app tests -q
```

Frontend:

```powershell
cd frontend
npm run lint
npm run build
```

Optional direct Ollama smoke:

```powershell
$body = @{ model = "qwen2.5-coder:7b"; prompt = "Reply OK"; stream = $false } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:11434/api/generate -Method Post -ContentType "application/json" -Body $body
```

## Safety Guarantees

Sprint 1 enforces these boundaries:

- Workspace containment blocks traversal and symlink/junction escapes.
- Secret-like, generated, heavy, binary, non-UTF8, and oversized files are blocked from automatic reading/mutation.
- Model output is validated through strict schemas before it can influence a plan, dry-run, or diff preview.
- Raw model shell commands are never executed.
- Dry-run and diff preview are zero-write.
- File mutation supports only `modify_text_file` and `create_text_file`.
- Apply uses the persisted reviewed diff content; it does not regenerate code.
- Existing files are snapshotted before mutation.
- Stale files abort before write.
- Multi-file partial failures roll back completed writes.
- Rollback is explicit and audit-preserving.
- Verification is allowlisted only: `python_compile`, `pytest`, `frontend_lint`, and `frontend_build`.
- The deterministic Quality Gate does not call Ollama.
- Retry is bounded to three attempts and every retry diff still requires explicit Apply.
- Recovery/resume never replays destructive actions after restart.
- Controlled Git commit stages only audited execution files and uses `--no-verify`; it does not push.
- No generic terminal, arbitrary shell, dependency installation, deployment, force push, reset, clean, merge, rebase, or Git push workflow is implemented.

## Known Limitations

- DevLoopAI is local-first and currently optimized for a single local operator.
- Ollama availability and GPU memory can affect planning, dry-run, and diff preparation.
- Browser automation from this Codex session can be limited by Windows shell/process policy; route and API-backed verification are used when that happens.
- Verification is intentionally limited to a small allowlist.
- Git push and deployment workflows are not implemented.
- Repository indexing, persistent semantic memory/RAG, specialist platform agents, and visual browser verification are not part of Sprint 1.

## Sprint 1 Status

Sprint 1 is a release-candidate safety foundation. It can inspect projects, plan, review, validate, approve, preflight, preview diffs, apply tightly controlled text-file changes, verify, evaluate quality, retry within bounds, roll back, recover state after restarts, and create controlled local Git commits.
