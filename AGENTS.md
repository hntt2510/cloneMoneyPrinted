# Autonomous Development & QA/QC Loop

Bạn là Master Orchestrator chịu trách nhiệm hoàn thiện toàn bộ project theo từng Milestone.

## Chu trình làm việc bắt buộc (Closed Loop):
1. **Phân tích & Lập Task (Plan)**:
   - Đọc danh sách việc cần làm (Roadmap/Milestone tiếp theo, ví dụ G09, G10...).
   - Tạo danh sách công việc nhỏ (sub-tasks).

2. **Code (Execution)**:
   - Viết hoặc sửa đổi code theo đúng kiến trúc của project.

3. **Tự động QA/QC (Quality Assurance)**:
   - Tự chạy typecheck: `python -m compileall app`
   - Tự chạy test tương ứng: `python -m unittest discover -s test/services` (hoặc test cụ thể như `test_cli_motion.py`).
   - Kiểm tra linter / code formatting.

4. **Đánh giá & Phản hồi (Feedback Loop)**:
   - **Nếu QA FAIL**: Phân tích log lỗi, quay lại bước 2 để sửa code và test lại cho đến khi PASS 100%.
   - **Nếu QA PASS**: Tạo commit git, cập nhật tài liệu/walkthrough, rồi tự động chuyển sang Task/Milestone tiếp theo.

5. **Điều kiện dừng (Stop Condition)**:
   - Tiếp tục lặp lại các bước 1 -> 4 cho đến khi hoàn thành toàn bộ Roadmap/Project, không dừng lại hỏi trừ khi gặp blocker hệ thống không thể tự giải quyết.


   AUTONOMOUS DEVELOPMENT & QA/QC MASTER ROADMAP

Project: hntt2510/cloneMoneyPrinted — Video Research & Asset Builder
Operating mode: Closed-loop autonomous development
Core loop: Plan → Implement → QA/QC → Fix → Re-QA → Commit → Merge Main → Re-QA Main → Push → Verify → Advance

0. MASTER ORCHESTRATOR ROLE

You are the Master Orchestrator responsible for completing the entire project milestone by milestone.

You are responsible for: reading the approved baseline; selecting the next unfinished milestone; breaking it into sub-tasks; inspecting architecture before writing code; implementing the smallest compatible change; preserving unrelated behavior; running QA/QC automatically; fixing failures until green; self-reviewing the diff; committing; merging locally into main with --no-ff; rerunning QA on merged main; pushing origin/main; verifying main == origin/main; reporting exact SHAs and QA; and automatically advancing when allowed.

Never claim PASS merely because code compiles or one targeted test passes.

1. CLOSED-LOOP DEVELOPMENT CYCLE

Phase A — Baseline / Safety

Before editing:

git status
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git rev-parse origin/main
git merge-base --is-ancestor <APPROVED_BASE_SHA> HEAD

Rules:

identify current approved base SHA;

inspect uncommitted files;

never overwrite unrelated user work;

never use destructive reset to hide changes;

never force-push;

never rewrite public main history.

Phase B — Architecture Inspection

Before coding, read existing models, runners, CLI dispatch, tests, artifact lineage, persistence contracts, retry semantics, resume semantics, and failure behavior. Search for reusable helpers before creating new ones. Write an internal implementation plan first.

Phase C — Feature Branch

git switch -c feature/<milestone-short-name>

Phase D — Implementation

prefer cohesive services over god files;

reuse approved runners rather than duplicate business logic;

keep core logic independent of Streamlit/UI unless the milestone explicitly requires UI;

preserve backward compatibility unless breaking change is explicitly authorized;

keep generated media out of git unless it is an intentional fixture;

do not hardcode secrets;

persist sanitized URLs/errors only.

Phase E — Targeted QA Loop

If QA fails: inspect full failure → identify root cause → fix → rerun failed test → rerun targeted suite → repeat until clean. Do not merge while targeted QA is red.

Phase F — Regression QA

Minimum global checks:

python -m compileall app test
python -m unittest discover -s test
uv lock --check
git diff --check

If Remotion is touched:

cd remotion
npm ci
npm run typecheck
cd ..

If a linter/formatter is already configured, run it. Do not add unrelated formatting tooling just for this policy.

Phase G — Actual Runtime Smoke

For media pipeline changes, run a real local/synthetic smoke test. Validate as applicable:

output exists and non-empty;

decoder opens it;

resolution correct;

FPS correct;

duration matches canonical frame span within <= 1 frame tolerance;

clean scene assets contain no audio;

no unexpected subtitles/BGM/cross-scene transitions baked into clean assets;

smoke output is not committed.

Phase H — Self Review

git diff <APPROVED_BASE_SHA>...HEAD

Inspect for scope creep, duplicate implementation, stale reuse, path bugs, provenance loss, job overwrite, terminal retrying with no work left, secrets in manifests, accidental live network tests, stale errors after recovery, failed output marked READY, and unrelated regressions.

Phase I — Feature Commit

Commit only after feature QA is green.

Phase J — Merge Main

git switch main
git pull --ff-only origin main
git merge --no-ff feature/<milestone-short-name> -m "merge: <milestone summary>"

Phase K — QA AGAIN ON MERGED MAIN

Repeat targeted, regression, compile/typecheck, and runtime smoke tests on merged main. Mandatory.

Phase L — Push Main

git push origin main
git fetch origin
git rev-parse main
git rev-parse origin/main
git status

Requirements: main == origin/main, clean worktree, no force push.

Phase M — Report & Advance

Every milestone report must include:

status;

base SHA;

feature branch;

feature commit;

merge commit;

final main SHA;

origin/main SHA;

files changed;

architecture summary;

QA commands;

total/passed/failed/skipped test counts;

runtime smoke result;

dependency changes;

working-tree state;

main pushed yes/no;

known debt;

next milestone.

If unittest says Ran 400 tests and OK (skipped=7), report total=400, failed=0, skipped=7, passed/non-skipped=393, not 400/400 passed.

2. GLOBAL STOP CONDITIONS

Continue automatically unless: a required local tool has no compatible fallback; an external credential is truly required; upstream access blocks verification; conflicting human changes need a human decision; a destructive irreversible step requires explicit authorization; or the roadmap says STOP FOR INDEPENDENT REVIEW.

When blocked: preserve work, never fabricate PASS, report the exact blocker and safest next action.

3. GLOBAL QUALITY GATES

A milestone is PASS only if all applicable gates pass:

Q1 Static: python -m compileall app test, git diff --check.

Q2 Targeted tests: milestone-specific suite passes.

Q3 Regression: all affected earlier milestone suites pass.

Q4 Full suite: python -m unittest discover -s test, no new failures.

Q5 Dependency integrity: uv lock --check.

Q6 Remotion: npm ci + npm run typecheck when relevant.

Q7 Runtime smoke: real local/synthetic execution passes.

Q8 Git integrity: correct base ancestry, clean branch, feature commit, merge commit, merged-main QA, push, main == origin/main.

Final release requires zero known failures; environment/encoding issues must be fixed or made deterministic instead of permanently waived.

4. PRODUCT ARCHITECTURE

CHATGPT / IDEA RESEARCH
        ↓
PROJECT SPEC
        ↓
SCRIPT / NARRATION
        ↓
TIMING / ALIGNMENT
        ↓
VISUAL PLANNER
        ↓
SCENE ORCHESTRATOR
   ┌───────────────┬────────────────┬─────────────────┐
   ↓               ↓                ↓
BROLL           DATA / TEXT      DOCUMENT
G05             G06              G07
   └───────────────┴────────────────┴─────────────────┘
        ↓
VALIDATION / FALLBACK / RECONCILIATION
        ↓
ORDERED CLEAN SCENE ASSETS
        ↓
G09 EDITOR PACKAGE
        ↓
Premiere / CapCut / Resolve manual edit
        ↓
G10 FINAL ASSEMBLY ENGINE
        ↓
final.mp4

Non-negotiable runtime principles:

no mandatory user checkpoints;

no B-roll review gate;

no WAITING_FOR_USER / REVIEW_REQUIRED / APPROVED runtime states;

factual evidence remains content-grounded;

generic imagery never masquerades as factual evidence;

clean per-scene assets use exact timing and no baked cross-scene transition;

successful assets survive unrelated failures;

manifests remain deterministic and auditable.

5. ROADMAP STATUS

G01 Foundation / Source policy                  ✅ APPROVED
G02 Project Spec / Project Runner               ✅ APPROVED
G03 Timeline Engine                             ✅ APPROVED
G04 Autonomous Visual Planner                   ✅ APPROVED
G05 Autonomous B-roll                           ✅ APPROVED
G06 Deterministic Remotion Engine               ✅ APPROVED
G07 Document / Evidence Pipeline                ✅ APPROVED
G08 Scene Orchestrator / Run All                🟡 IMPLEMENTED, HARDENING REQUIRED
G09 Editor-ready Export Package                 ⏳ TODO
G10 Final Assembly Engine                       ⏳ TODO
G11 Autonomous GitHub → Antigravity Supervisor  ⏳ TODO
G12 Production Release / Reliability Gate       ⏳ TODO

G08 must be fully hardened before G09 starts.

G08-H — SCENE ORCHESTRATOR HARDENING

Goal

Close the remaining G08 integration gaps so --run-all is safe, resumable, provenance-preserving, and compatible with project-adjacent sources.json.

G08-H.1 — Preserve Original sources.json

Input package:

Project/
├── project.json
├── sources.json
└── evidence.pdf

G08 must let G07 resolve the original project directory even when latest runtime state lives in project.motion.json, project.assets.json, or project.planned.json.

Preferred behavior:

invoke G07 with original project.json + same task_id;

let G07 workspace resolution load the newest task-stage project;

preserve original directory for source registry discovery;

keep relative local_file paths relative to original source registry.

Do not copy sources.json into task dir as the primary fix.

G08-H.2 — TTS Planning Resume

Planning reuse must validate generated planning artifacts rather than requiring planned_project.narration.file for TTS.

Reuse checks:

project.planned.json valid;

visual_plan.json valid;

timeline.json valid;

timeline.audio_file exists/non-empty;

timeline.timing_file exists/non-empty;

timeline and visual cues remain consistent;

FPS/aspect compatible;

project ownership fingerprint matches.

G08-H.3 — Durable Ownership Fingerprint

Create an atomic task ownership record such as:

task_input.json

with schema version, task ID, source project fingerprint, source project file, created_at, updated_at.

Rules:

same task + same fingerprint → resumable;

same task + different fingerprint → fail before reuse;

stale planning artifacts without trusted G08 ownership metadata → do not silently reuse;

interrupted G08 run with valid ownership metadata → resume safely.

G08-H.4 — Real Runner Return Contracts

Use current real runner keys:

B-roll: ready_count, failed_count
Motion: motion_count, failed_count
Evidence: evidence_count, failed_count, skipped_count

Tests must mock the production contracts exactly.

G08-H.5 — Preserve DOCUMENT Provenance Through Fallback

Do not remove original G07 RenderJob when optional DOCUMENT falls back to TEXT.

Keep both:

R003   document attempt/result
RF003  text_fallback result

Fallback job metadata must include:

fallback_from=document;

fallback_reason;

original document render job ID;

original document status;

original error, sanitized.

Final output resolution for DOCUMENT should explicitly choose ready fallback where fallback was executed, otherwise ready document evidence. Do not use naive next(job for scene_id) logic when multiple render jobs can exist for one scene.

G08-H.6 — Persistent Progress Snapshots

Atomically persist execution_manifest.json after each stage. Suggested milestones:

preflight  5
planning  25
broll     45
motion    65
evidence  85
fallback  95
finalize 100

Progress must never decrease. An interrupted process must leave a useful execution manifest on disk.

G08-H.7 — Atomic project.executed.json

Write final executed project atomically: temporary file → parse/validate → replace canonical destination.

G08-H.8 — Stage Error Reconciliation

Keep project_manifest.outputs["stage_errors"] as a labelled dictionary, e.g.:

{
  "broll": "...",
  "motion": "...",
  "evidence": "...",
  "fallback": "..."
}

Recovered errors must leave the current fatal state while remaining available as diagnostics where appropriate. If every planned scene has a validated final output—including an approved optional DOCUMENT→TEXT fallback—overall execution may be complete.

G08-H Required Tests

Must cover:

project-adjacent sources.json + relative local PDF;

no Wikimedia call when valid local registry evidence exists;

TTS plan reuse with narration.file=None;

interrupted G08 run resumes with ownership fingerprint;

stale legacy plan without ownership fingerprint not blindly reused;

same task different project rejected;

exact real stage counts persisted;

original DOCUMENT RenderJob preserved after fallback;

fallback RenderJob appended with unique ID;

final resolver chooses fallback correctly;

progress snapshots monotonic;

interruption leaves useful execution manifest;

source bytes change causes evidence reprocessing while planning remains reused;

B-roll canonical frame timing;

B-roll terminal retrying only when actual work remains.

G08-H Runtime Smoke

Local/no-network project:

S001 DATA
S002 TEXT
S003 DOCUMENT optional -> TEXT fallback
S004 DOCUMENT -> project-adjacent sources.json -> local PDF

Validate all final usable outputs.

G08-H QA Gate

python -m unittest test.services.test_scene_orchestrator
python -m unittest test.services.test_scene_orchestrator_smoke
python -m unittest test.services.test_broll_runner test.services.test_broll
python -m unittest test.services.test_motion_runner test.services.test_motion_normalizer
python -m unittest test.services.test_evidence_runner test.services.test_evidence_selector test.services.test_evidence_sources
python -m unittest test.services.test_cli
python -m unittest discover -s test
python -m compileall app test
uv lock --check
git diff --check
cd remotion && npm ci && npm run typecheck && cd ..

Feature commit: fix: harden scene orchestrator resume and provenance
Merge commit: merge: harden autonomous scene orchestrator

STOP FOR INDEPENDENT REVIEW after G08-H.

G09 — EDITOR-READY EXPORT PACKAGE

Goal

Convert a G08 task workspace into a deterministic, portable editor package for Premiere Pro, CapCut, DaVinci Resolve, or another NLE. G09 does not assemble final.mp4.

Desired Output

exports/<project-slug>/
├── project.json
├── project.executed.json
├── execution_manifest.json
├── edit_manifest.json
├── README_EDIT.md
├── narration/
│   ├── narration.<ext>
│   └── subtitle.srt
├── scenes/
│   ├── S001_BROLL.mp4
│   ├── S002_DATA.mp4
│   ├── S003_DOCUMENT.mp4
│   └── ...
└── sources/
    └── source_manifest.json

G09.1 — Export Models

Recommended app/models/export.py with strict extra="forbid" models:

EditorPackageStatus;

EditorSceneEntry;

EditorSourceEntry;

EditManifest;

ExportResult.

G09.2 — edit_manifest.json

Top-level fields:

schema version;

project title/slug;

task ID;

source project fingerprint;

package status;

FPS/resolution/aspect;

duration frames/seconds;

narration file;

subtitle file;

ordered scenes;

source provenance entries;

missing scenes;

created_at;

outputs.

Scene entry fields:

scene_id/order;

planned_visual_type/resolved_visual_type;

purpose;

start/end;

start_frame/end_frame/duration_frames;

exported file;

SHA-256;

source stage;

fallback provenance;

provenance reference.

G09.3 — Deterministic Scene Naming

Use S###_<RESOLVED_TYPE>.mp4. Preserve planned type separately in manifest. No duplicate names.

G09.4 — Portable Copy Policy

No symlinks by default. Copy actual files for Windows/external-drive portability.

Per file: validate source → copy to temp → SHA source/destination → require equality → atomic rename.

G09.5 — Narration Export

Use planning timeline/runtime narration source of truth. Copy to narration/narration.<ext> and persist SHA-256.

G09.6 — Subtitle Export

If timing is SRT, export directly. If another supported structured timing format can be deterministically converted, generate SRT without paraphrasing text. No LLM subtitle rewrite. If unavailable, subtitle_file=null plus reason.

G09.7 — Provenance Export

Create sources/source_manifest.json aggregating B-roll selected asset metadata, Evidence metadata, execution manifest, and normalized source registry where present. Never persist signed URL secrets.

G09.8 — Partial Package

Support statuses:

complete
partial
failed

All valid scenes → complete. Some valid + some missing → partial. No valid scenes → failed. Never create fake placeholder videos.

G09.9 — README_EDIT.md

Generate deterministic edit instructions with project title, FPS, resolution, narration filename, scene order, missing/fallback scenes, evidence provenance note, reminder that scene MP4s are intentionally silent, and recommended manual assembly order.

G09.10 — CLI

Standalone export:

python cli.py --project project.json --task-id TASK_ID --export-editor-package

One-command chain:

python cli.py --project project.json --run-all --export-editor-package

Do not change legacy plain --project behavior.

G09.11 — Export Resumability

Export fingerprint includes source project fingerprint, scene SHAs, narration SHA, subtitle/timing SHA, and export schema/config. Same validated fingerprint may be reused. Changed asset invalidates only required package files safely.

G09 Required Tests

complete package;

partial package;

deterministic order;

planned vs resolved fallback type retained;

scene SHA copy verification;

narration copy/hash;

subtitle export;

missing subtitle honest handling;

signed URL secret sanitization;

repeat export reuse;

changed scene invalidation;

Windows-safe filenames;

no symlink default;

standalone CLI export;

--run-all --export-editor-package chain;

assert no final.mp4 created.

G09 Runtime Smoke

Use a local fixture workspace containing several resolved scene types. Validate directory structure and SHA integrity.

G09 QA

python -m unittest test.services.test_export_runner
python -m unittest test.services.test_cli
python -m unittest discover -s test
python -m compileall app test
uv lock --check
git diff --check

Run Remotion regression if integration is touched.

Feature commit: feat: add editor-ready asset export package
Merge commit: merge: add editor-ready export workflow

STOP FOR INDEPENDENT REVIEW after G09.

G10 — FINAL ASSEMBLY ENGINE

Goal

Produce validated final.mp4 from the same deterministic editor/execution manifest without changing the clean per-scene production contract. Final assembly is optional in UX but is part of the full roadmap.

Input

Prefer edit_manifest.json; fallback to execution_manifest.json + project.executed.json only when equivalent data is available.

Output

final/
├── final.mp4
├── assembly_manifest.json
├── qc_report.json
└── render.log

G10.1 — Assembly Models

Create strict models:

AssemblyConfig;

AssemblyScene;

AudioMixConfig;

AssemblyManifest;

FinalQCReport.

G10.2 — Scene Concatenation

Concatenate in manifest order only. No random ordering, duplication, hidden gaps, or silent omission of failed scenes. Preserve project resolution/FPS. Prefer frame counts over accumulated floats where possible.

G10.3 — Narration Backbone

Narration is the continuous primary audio track. Do not stretch narration to hide scene timing bugs. Final duration must reconcile with narration/timeline within documented media/container tolerance.

G10.4 — Subtitles

Support disabled, soft subtitles where practical, and deterministic burn-in when explicitly configured. Subtitle application happens at final assembly, not inside clean scene assets.

G10.5 — BGM

Default none. If enabled, use local/approved assets, deterministic loop/trim, configured volume, and predictable ducking/attenuation. Do not introduce remote music search unless a later source policy explicitly authorizes it.

G10.6 — Transitions

Transitions occur only at assembly boundaries. Default none. Any enabled transition must come from an explicit deterministic allowlist. Never modify G05/G06/G07 outputs to bake transitions back into source scenes.

G10.7 — Branding / SFX

Optional and configuration-driven. No hidden watermark. No unlicensed external asset fetch.

G10.8 — Assembly Fingerprint

Include edit-manifest SHA, scene SHAs, narration SHA, subtitle SHA, assembly config, optional BGM/branding hashes, and encoder settings. Same fingerprint + valid QC may reuse final output.

G10.9 — Atomic Final Render

Render to temporary file → validate → rename to final.mp4. A known-bad file must never remain under the canonical final filename.

G10.10 — Final QC

Validate:

MP4 exists/non-empty;

expected resolution/FPS;

playable video stream;

narration audio stream exists when expected;

expected duration;

scene order unchanged;

boundary map covers expected timeline;

no unexpected black/frozen gaps;

subtitle behavior matches config;

no secret metadata leaks.

G10.11 — CLI

Add explicit --assemble-final and support:

python cli.py --project project.json --run-all --export-editor-package --assemble-final

Do not make final assembly mandatory for asset-only users.

G10.12 — Failure Policy

Missing required scene → assembly fails. Do not fabricate placeholder. Editor package remains available. Approved optional DOCUMENT→TEXT fallback is a valid resolved scene.

G10 Required Tests

deterministic 3-scene concat;

narration mix;

subtitle disabled;

subtitle enabled;

BGM none default;

local BGM enabled;

transition none default;

missing scene fails;

wrong dimensions rejected;

duplicate order rejected;

assembly fingerprint reuse;

changed config invalidates final;

atomic output behavior;

final QC detects invalid audio/video;

one-command CLI chain;

editor package remains unchanged.

G10 Runtime Smoke

Fully local 1920x1080 30fps fixture. Render a 3–5 second final MP4 with actual video+audio validation.

G10 QA

Full targeted assembly/CLI tests, complete Python regression, compileall, lock check, and actual FFmpeg assembly smoke.

Feature commit: feat: add deterministic final assembly engine
Merge commit: merge: add final video assembly pipeline

STOP FOR INDEPENDENT REVIEW after G10.

G11 — AUTONOMOUS GITHUB → ANTIGRAVITY SUPERVISOR

Goal

Create a development control plane where GitHub is the durable source of work instructions and a local Antigravity-based supervisor autonomously claims tasks, instructs coding agents, observes QA, commits/merges/pushes according to policy, and advances milestones.

This is development automation, not video runtime logic.

Architecture Decision

Do not base unattended automation on GUI clicks against the IDE.

Recommended architecture:

GitHub Issue / Roadmap Command
        ↓
GitHub MCP / GitHub API
        ↓
Local Supervisor Process
(Antigravity SDK or CLI — inspect installed capability first)
        ↓
Workspace Agent
        ↓
Repo / Terminal / Tests / Git
        ↓
GitHub status comment + labels
        ↓
Next command

Antigravity IDE may remain the visible workspace, but the unattended controller should use a programmatic/local agent surface rather than brittle GUI automation.

Before implementation, inspect the installed Antigravity CLI/SDK and official documentation. Never invent SDK methods or CLI flags. If SDK is unavailable but CLI supports non-interactive agent execution, use CLI. If neither provides the required workflow, stop G11 with a precise blocker instead of faking automation through GUI clicks.

G11.1 — GitHub Command Queue

Use GitHub Issues as durable jobs.

Recommended labels:

agent:queued
agent:claimed
agent:running
agent:qa
agent:blocked
agent:review
agent:done
agent:cancelled

Optional labels: G08, G09, G10, bug, hardening, release.

G11.2 — Machine-readable Command Schema

Issue front matter example:

---
agent_job_version: "1.0"
repo: "hntt2510/cloneMoneyPrinted"
goal_id: "G09"
base_sha: "..."
branch: "feature/video-research-asset-builder-g09-export"
merge_to: "main"
merge_mode: "no-ff"
auto_push_main: true
stop_after: "independent_review"
---

Markdown sections:

## Objective
## Scope
## Non-Goals
## Acceptance Criteria
## QA Commands
## Runtime Smoke
## Final Report Format

G11.3 — Supervisor Config

Recommended repository config:

.agents/orchestrator.yaml

Fields:

allowed repo;

allowed base branch;

allow push main;

allow_force_push=false;

max parallel jobs;

polling interval;

required/stop labels;

QA commands;

working directory;

state directory;

log directory;

trusted GitHub actors.

G11.4 — MCP Configuration

Use workspace-level MCP config where supported:

.agents/mcp_config.json

GitHub tools should allow the agent to read issues/commits, inspect job instructions, post status, and manage authorized labels. Never commit tokens.

G11.5 — Local Supervisor State Machine

QUEUED
CLAIMED
PLANNING
CODING
QA
FIXING
MERGING
MAIN_QA
PUSHING
REPORTING
DONE
BLOCKED
CANCELLED

Persist state locally so restarts do not duplicate work.

G11.6 — Claim / Lease

Only one supervisor executes a job at a time. Use GitHub claim state + local run UUID + timestamp/lease expiration. A second supervisor must refuse a valid active lease.

G11.7 — Idempotency

Repeated polling must not create duplicate branches, duplicate commits, repeat completed merges, push the same work twice, reopen completed jobs, or spam duplicate reports. Key state by GitHub job ID + base SHA + run ID.

G11.8 — Coding Agent Dispatch

Supervisor sends exact repo path, approved base SHA, full issue spec, branch policy, QA commands, non-goals, stop condition, and final report schema. Coding agent must inspect architecture before modifying code.

G11.9 — QA Enforcement

Supervisor independently verifies agent claims. At minimum rerun:

python -m compileall app test
python -m unittest discover -s test
uv lock --check
git diff --check

plus issue-specific QA. Textual PASS from a coding agent is never sufficient by itself.

QA failure loops:

QA -> FIXING -> QA

with bounded retries and truthful BLOCKED state if unrecoverable.

G11.10 — Git Enforcement

Enforce expected ancestry, clean feature branch, no force push, no merge while QA red, merged-main QA before push, and origin/main == main verification after push.

G11.11 — GitHub Status Reporting

Keep status updates concise. Prefer editing a single status comment or bounded transition comments rather than spam.

Example:

Status: QA
Run ID: ...
Branch: ...
Head: ...
Latest QA: ...
Last update: ...

G11.12 — Kill Switch

If agent:cancelled appears, stop before the next write/merge/push operation, preserve branch/logs, and report cancellation.

G11.13 — Security Boundary

Required:

repo/base branch allowlists;

trusted-author policy;

untrusted issue/comment text cannot directly gain command authority;

no secrets in GitHub comments/logs;

sanitize signed URLs/tokens;

no force push;

bounded retries/timeouts;

command arguments via safe subprocess lists where practical;

branch deletion only after DONE and optional retention period.

G11.14 — Trusted Author Policy

Only execute jobs created or explicitly approved by configured trusted actors. Untrusted content may be context, not executable authority.

G11.15 — Polling vs Webhook

Phase 1: poll GitHub every 30–60 seconds for simplicity/reliability. Webhook mode may be added later when a stable inbound endpoint exists.

G11 Required Tests

Mock GitHub by default. Cover:

queued job claim;

duplicate claim rejected;

untrusted author rejected;

base SHA mismatch;

coding success;

QA failure → fix loop;

bounded repeated QA failure → BLOCKED;

feature commit validation;

merge blocked while QA red;

merged-main QA;

push success;

push failure preserved;

restart/resume idempotency;

cancellation kill switch;

status sanitization;

no force-push command path.

G11 Local Integration Smoke

Use a disposable local git fixture repository and mocked GitHub source:

queued
→ claim
→ agent makes tiny fixture change
→ QA
→ commit
→ merge
→ main QA
→ fake push/report
→ DONE

Do not use the production repo for destructive smoke.

G11 Optional Real GitHub Dry Run

If credentials and authorization exist, provide dry_run=true: read/claim/report a real GitHub job without code push.

G11 Documentation

Create SUPERVISOR.md covering install, Antigravity capability detection, GitHub MCP setup, config, job schema, state machine, recovery, kill switch, and security boundaries.

Feature commit: feat: add autonomous github development supervisor
Merge commit: merge: add github antigravity supervision workflow

STOP FOR INDEPENDENT REVIEW after G11.

G12 — PRODUCTION RELIABILITY / RELEASE GATE

Goal

Turn the completed pipeline into a stable release candidate with deterministic end-to-end verification, CI, recoverability, security checks, documentation, and zero unresolved milestone blockers.

G12.1 — Golden End-to-End Fixture

Create a local deterministic fixture project exercising:

DATA
TEXT
BROLL local fixture or mocked acquisition
DOCUMENT local PDF
optional DOCUMENT fallback
editor export
final assembly

No live network dependency. Prefer generating test media during QA rather than committing large binaries.

G12.2 — CI

Add repository CI with at minimum:

Python compile;

full Python tests;

uv lock --check;

clean Remotion install;

Remotion typecheck;

deterministic no-network integration smoke.

Prefer Windows + Linux matrix if both are supported.

G12.3 — Windows Safety

Explicitly test:

paths with spaces;

Unicode filenames;

safe subprocess argument lists;

atomic replace behavior;

console/text encoding;

no /tmp assumptions;

portable export names.

Close any remaining cp1252/console encoding failure before final release.

G12.4 — Crash Recovery

Simulate interruption after planning, B-roll, motion, evidence, fallback, export, and final assembly temp render. Rerun and verify no duplicate jobs, no wrong-project stale reuse, no corrupt canonical JSON, correct valid-stage reuse, and no partial temp file marked READY.

G12.5 — Manifest Audit

Validate real outputs against:

project manifest;

execution manifest;

B-roll manifest;

motion manifest;

evidence manifest;

edit manifest;

assembly manifest;

QC report.

No dangling path may exist for a READY record.

G12.6 — Secret / PII Audit

Search generated JSON/log output for credential patterns such as Authorization, Bearer, api_key, apikey, token=, sig=, secret=, password=. Extend sanitization tests to nested exception chains and URL query strings.

G12.7 — Dependency Audit

lock reproducible;

no unnecessary package;

Python/Node versions documented;

FFmpeg/Node detection has actionable errors;

no undeclared runtime tool download.

G12.8 — Performance Baseline

Record local baseline for planning reuse startup, each render type, export, final assembly, and artifact size. No invented SLA is required, but obvious regressions should be visible.

G12.9 — Logging

Logs should include task ID, stage, scene ID where relevant, attempt, safe source/provider identity, duration, and failure category, without secrets.

G12.10 — Documentation

Update/create as applicable:

README.md / README-en.md
PROJECT_SPEC.md
EDITOR_EXPORT.md
FINAL_ASSEMBLY.md
SUPERVISOR.md
RELEASE_CHECKLIST.md

Document shortest workflows:

Asset-only:

python cli.py --project project.json --run-all

Editor package:

python cli.py --project project.json --run-all --export-editor-package

Full assembly:

python cli.py --project project.json --run-all --export-editor-package --assemble-final

G12.11 — Release Gate

Release candidate PASS only when:

all milestone acceptance tests pass;

full suite has zero failures;

runtime smoke passes;

no unresolved critical/high blocker;

main == origin/main;

clean worktree;

release docs match actual behavior;

no generated junk committed;

security audit passes;

deterministic local E2E fixture passes twice consecutively.

G12.12 — Release Tag

Do not tag before all gates pass. If no repository version policy exists, propose one rather than silently inventing a release version.

Feature commit: chore: harden production release workflow
Merge commit: merge: finalize production release readiness

STOP FOR FINAL INDEPENDENT REVIEW.

6. AUTONOMOUS MILESTONE ADVANCEMENT RULE

After a milestone is merged, QA'd on main, pushed, and verified:

update roadmap state;

write the completion report;

if milestone says STOP FOR INDEPENDENT REVIEW, stop;

reviewer APPROVED → begin next goal;

reviewer CHANGES REQUESTED → create a hardening branch from current main, implement only requested fixes, run the complete closed loop again;

never skip an unapproved milestone to start a later goal.

7. GITHUB-DRIVEN AUTONOMOUS DEVELOPMENT MODE

After G11, GitHub becomes the durable job queue while this file remains the policy source.

ROADMAP / REVIEWER
      ↓
GitHub issue labelled agent:queued
      ↓
Antigravity Supervisor claims job
      ↓
Agent verifies repo + current SHA
      ↓
Feature branch
      ↓
Implementation
      ↓
Targeted QA loop
      ↓
Regression QA
      ↓
Feature commit
      ↓
No-ff merge main
      ↓
Merged-main QA
      ↓
Push origin/main
      ↓
GitHub report
      ↓
agent:review
      ↓
Independent review
      ↓
APPROVED → next issue
CHANGES_REQUESTED → hardening issue

The supervisor treats reviewer approval as a mandatory gate wherever the milestone says STOP FOR INDEPENDENT REVIEW.

8. FINAL DEFINITION OF DONE

The project is complete only when:

G08 hardening approved;

G09 approved;

G10 approved;

G11 approved if autonomous GitHub-driven development is desired;

G12 final release gate approved;

project.json can autonomously produce ordered scene assets;

editor package is deterministic and portable;

optional final assembly produces validated final.mp4;

evidence never degrades into ungrounded illustration;

every READY scene has validated media;

resume semantics never cross project fingerprints;

source provenance is retained;

full suite has zero failures;

deterministic no-network E2E fixture passes twice;

main is clean and synchronized with origin;

documentation matches actual commands and behavior.

At that point stop autonomous development and produce the final project completion report.
