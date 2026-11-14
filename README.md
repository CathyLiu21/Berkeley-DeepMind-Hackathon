# Durable AI Deep Research

A multi-agent due diligence and market research workbench powered by **Gemini 3.6 Flash + Google Search Grounding**, **Gemini TTS (`gemini-2.5-flash-preview-tts`)**, **Vertex AI**, **Google Cloud Run Services & Worker Pools**, and **Temporal** — built for the **Berkeley x DeepMind Hackathon**.

## Demo Videos

- **2-Minute Video — Team Introduction & Elevator Pitch:** https://youtu.be/BViIUzQXxIs
- **1-Minute Video — Prototype Demo (Critical User Journey):** https://youtu.be/YcfgTGyPi8U

## What This App Does

1. **Ask & Budget Guardrail:** Submit a startup, market, or technical question with a selectable **Lean** (`3 parts · 120k tok`), **Standard** (`6 parts · 350k tok`), or **Deep** (`6 parts · 700k tok`) budget guardrail.
2. **Scale-from-Zero Parallel Research:** A planner breaks the question into sub-tracks and fans them out across Cloud Run Worker Pool instances (1 Activity slot per instance, scaled `0 -> N -> 0` by Temporal's Worker Controller Instance). Workers call Gemini via **Vertex AI** with **Google Search Grounding** (`types.GoogleSearch()`).
3. **Critic Audit & Cited Report:** A Critic stage audits findings against primary sources before synthesizing a cited memo with a **Report Scorecard**, **Observability & Trace** waterfall, Markdown copy, and PDF export.
4. **Human-in-the-Loop Pause & Stop Control:** Once drafted (`Research Done · Waiting for Review`), workers return to `0` while keeping the resumable `/r/<id>` link active for **Good enough** (`Research Done`) or **Dig deeper** follow-up rounds. Active runs can also be terminated immediately via **Stop Running**.
5. **Neural Audio Briefing Reel:** Converts the executive memo into an interactive slide-by-slide audio briefing narrated by **Gemini TTS (`gemini-2.5-flash-preview-tts`)**.

---

## 🚀 Antigravity CLI Track (`/swarm` Multi-Agent Development)

Built with **Antigravity CLI**, this prototype leveraged `/swarm` multi-agent orchestration to parallelize development across strict architectural boundaries while a dedicated **Verifier Agent** guarded cross-tier contracts before deployment:

- **Frontend Agent (`web.py`, `web/index.html`, `web/app.css`):** Built the **Play Briefing Reel** audio player (`POST /api/tts` with sentence-boundary splitting, WAV concatenation, and LRU caching), the **Observability & Trace** waterfall (`GET /api/run/{id}/trace`), proactive passcode unlock (`Unlock & Run ↵` with `type="password"` masking and auto-hide after submission), active `Stop Running` workflow termination (`POST /api/run/{id}/stop`), and stage status indicators (`Research Done · Waiting for Review` / `Research Done`).
- **Backend & Gemini Workflow Agent (`llm.py`, `research_workflow.py`, `research_activities.py`, `research_types.py`):** Implemented keyless Vertex AI authentication (`GOOGLE_GENAI_USE_VERTEXAI=true`), `NarrateWorkflow` and chunked `narrate_briefing` Activity using `gemini-2.5-flash-preview-tts` (`LPCM -> WAV`), `RunBudget` guardrails (`lean`, `standard`, `deep`), and durable Temporal signals/activities.
- **Infra, Evals & Tests Agent (`terraform/`, `evals/`, `tests/`):** Wired keyless Vertex AI IAM (`aiplatform.googleapis.com` and `roles/aiplatform.user` on the Cloud Run Worker Pool runtime service account), built the offline cassette evaluation suite (`evals/run_evals.py`), and expanded unit, replay, and web contract tests.
- **Verifier Agent (Pre-Demo Gatekeeper):** Because this codebase enforces strict AST and security boundaries across tiers (`web.py` must never import `llm` or `google.genai`, `llm.py` must never import `temporalio`, `web/index.html` must contain zero `innerHTML` calls, and `ResearchWorkflow` must pass deterministic Temporal history replay), the Verifier Agent continuously ran the verification suite (`pytest`, `python -m evals.run_evals`, `terraform fmt -check`, and JS syntax checks) to catch any boundary violation before deploying to Cloud Run.

### Why `/swarm` Fits This Architecture
A multi-tier Temporal + Cloud Run + Vertex AI system breaks silently if a frontend change leaks an SDK import into the web container or a workflow edit breaks deterministic replay. Using `/swarm` allowed frontend UI iteration, backend Gemini 2.5 Flash / TTS plumbing, and Terraform IAM configuration to move in parallel without stepping on each other, while the Verifier Agent enforced every architectural invariant automatically before our live demo.

---

## Starter Repo Attribution & Code Built During the Hackathon

This project started from the open-source [temporal-community/durable-research-fleet](https://github.com/temporal-community/durable-research-fleet) Serverless Workers + Cloud Run template (`runtime.py`, `workflows.py`, `activities.py`, `starter.py`, `worker_local.py`, `worker_cloudrun.py`, `selfhosted/`, and base `terraform/` GCP networking/VM/pool scaffolding).

To keep this submission repository focused strictly on the GCP + Gemini prototype, upstream AWS Bedrock AgentCore code, multi-cloud `fleet` CLI switchers, and unrelated reference docs were removed.

### Features Created / Extended Within the 24-Hour Hackathon Window

- **Neural Audio Briefing Reel (`llm.py`, `research_activities.py`, `research_workflow.py`, `web.py`, `web/index.html`, `web/app.css`):**
  - Added `NarrateWorkflow` and chunked `narrate_briefing` Activity using `gemini-2.5-flash-preview-tts` (`LPCM -> WAV`).
  - Added `POST /api/tts` endpoint with sentence-boundary splitting, WAV concatenation, and LRU caching, plus the interactive **Play Briefing Reel** UI (prefetching, pause/resume, mute/unmute, browser speech fallback).
- **Observability & Distributed Execution Trace (`web.py`, `web/index.html`, `web/app.css`):**
  - Added `GET /api/run/{id}/trace` reading Temporal Event History to render queue vs. execution waterfalls, retries, Signals, and worker counts without exposing raw worker hostnames.
- **Run Budget Guardrails & Report Scorecard (`research_types.py`, `research_workflow.py`, `web.py`, `web/index.html`):**
  - Added `RunBudget` presets (`lean`, `standard`, `deep`) and live scorecard / budget utilization meters.
- **Vertex AI Keyless Integration (`terraform/main.tf`, `terraform/iam.tf`, `terraform/variables.tf`, `terraform/workerpool.tf`, `terraform/tests/wiring.tftest.hcl`, `Makefile`):**
  - Enabled `aiplatform.googleapis.com`, granted `roles/aiplatform.user` to the Cloud Run Worker Pool runtime service account, and configured `GOOGLE_GENAI_USE_VERTEXAI=true` with `vertex_location = "global"`.
- **Console UX, Masked Passcode & Workflow Kill Switch (`web.py`, `web/index.html`, `web/app.css`):**
  - Added masked (`type="password"`) passcode entry with auto-hide on auth success and proactive `passcode_required` detection via `/api/fleet`.
  - Added `POST /api/run/{id}/stop` (**Stop Running**) to terminate active workflows cleanly, plus `Research Done` status pills, **New Research** navigation, and PDF/Markdown export.
- **Offline Evaluation Harness & Tests (`evals/`, `tests/test_web.py`, `tests/test_research_workflow.py`, `tests/test_replay.py`):**
  - Added cassette-based offline evaluation suite (`evals/run_evals.py`) and expanded unit, Temporal replay, and XSS/security contract tests.

---

## Repository Layout

| Path | Role |
|---|---|
| `web.py`, `web/` | FastAPI web console (`ResearchWorkflow` client, `/api/tts`, `/api/run/{id}/trace`, `/api/run/{id}/stop`), zero-build vanilla HTML/CSS/JS UI |
| `llm.py` | Gemini (`gemini-3.6-flash` + Google Search) & Gemini TTS (`gemini-2.5-flash-preview-tts`) provider layer |
| `research_workflow.py`, `research_activities.py`, `research_types.py` | Temporal `ResearchWorkflow`, `NarrateWorkflow`, Activity heartbeats, critic audit, and budget guardrails |
| `runtime.py`, `apps.py`, `worker_cloudrun.py`, `worker_local.py` | Temporal Worker runtime & entrypoint wiring for Cloud Run and local development |
| `workflows.py`, `activities.py`, `starter.py` | Smoke-test `HelloWorkflow` used by `make verify` to validate Cloud Run scale-from-zero |
| `evals/` | Deterministic cassette evaluation runner (`evals/run_evals.py`) |
| `terraform/`, `Dockerfile`, `scripts/verify_stack.sh` | Declarative GCP stack (Cloud Run Service + Worker Pool, Compute Engine Temporal VM, Vertex AI IAM, Secret Manager, VPC) |
| `selfhosted/` | Docker Compose Temporal server for local runs |
| `tests/` | Offline `pytest` suite (workflow replay, web security/contracts, LLM fakes, runtime invariants) |

---

## Quickstart

### 1. Run Offline Tests & Evals
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m evals.run_evals
terraform -chdir=terraform test
```

### 2. Run Locally (with Docker Compose Temporal)
```bash
cp .env.example .env
# Set GEMINI_API_KEY in .env (and optionally DEMO_PASSCODE)
set -a; . ./.env; set +a

docker compose -f selfhosted/docker-compose.yml up -d
.venv/bin/python worker_local.py        # Terminal 1
.venv/bin/uvicorn web:app --port 8000   # Terminal 2
```

### 3. Deploy to Google Cloud Run + Vertex AI
Create `terraform/terraform.tfvars` (gitignored) with your GCP project and optional demo passcode:
```hcl
project_id    = "your-gcp-project-id"
demo_passcode = "your-passcode"
```
Then build and apply the stack:
```bash
make up AUTO=1 PROJECT=your-gcp-project-id
```
