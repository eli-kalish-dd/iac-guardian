# IaC Guardian — Thread Context Export

Use this as context when starting a new thread to continue work on this project.

---

## Project Overview

- **What it is:** Hackathon demo for "K8s Shift Left" / Proactive Remediation. Analyzes K8s/Terraform PRs, uses Claude + Datadog MCP for real metrics, posts 4-section comments (Risk Level / What Changed / Why It's a Problem / What To Do).
- **Repo:** Fork at `eli-kalish-dd/iac-guardian` (origin: ananth-vaid/iac-guardian)
- **Key surfaces:** Streamlit UI (`app.py`), CLI (`scripts/analyze_pr.py`), GitHub Actions workflow (`.github/workflows/iac-review.yml`)

---

## Setup (Completed)

- **Python 3.10+**, venv, `pip install -r requirements.txt`
- **`.env`** with: `ANTHROPIC_API_KEY`, `DATADOG_API_KEY`, `DATADOG_APP_KEY`
- **API keys:** Anthropic via Datadog app (https://app.datadoghq.com/app-builder/apps/59b315b9-4ce0-45c9-a2d4-2dfaa595876a) → Request Access. Datadog keys via dd-auth CLI or Org Settings → API Keys.
- **Run UI:** `./run_ui.sh` → http://localhost:8501 (skip Streamlit email prompt)

---

## Fixes Applied This Thread

1. **`scripts/datadog_api_client.py`** — Added missing `import re` (was causing `NameError` in Scenario 9).
2. **`.github/workflows/iac-review.yml`** — Fixed YAML:
   - Removed leading 2 spaces from root keys (was "completed with no jobs")
   - Fixed `runs-on` / `permissions` indentation (was "Invalid workflow file" on line 17)
   - Added `workflow_dispatch` with `pr_number` input for manual runs
3. **Scenario 9 PR demo** — PR must show a *reduction* in CPU (500m→100m, 1000m→200m), not a new file. Baseline file on `main` first, then branch modifies it.

---

## GitHub PR Demo Flow

1. **Main** must have `k8s/xray-converter-main-deployment.yaml` (baseline: 500m request, 1000m limit).
2. **Branch** `demo/scenario-9-cpu-throttling` modifies that file to 100m/200m.
3. **Secrets** on fork: `ANTHROPIC_API_KEY`, `DATADOG_API_KEY`, `DATADOG_APP_KEY` (Settings → Secrets → Actions).
4. **Manual run:** Actions → IaC Guardian Review → Run workflow → select PR branch, enter PR number. (Workflow must exist on that branch — merge main into PR branch if needed.)
5. **Action had perms errors** posting comments — we switched to **manually pasting** the comment.

---

## Manual PR Comment (Scenario 9)

We drafted a Markdown comment for the CPU throttling PR. Format:

- Image (optional)
- `## **Datadog IaC Health** · ⚠️ **HIGH RISK**`
- **What changed:** (factual diff summary)
- **Why it's a problem:** (with Datadog link if desired)
- **Recommendation:** (bullets)
- `<sub>🤖 Powered by Datadog + Claude AI</sub>`

---

## Key Paths

| Path | Purpose |
|------|---------|
| `app.py` | Streamlit UI, scenario selector, inline diffs |
| `scripts/analyze_pr.py` | Core analysis, Claude + DD context |
| `scripts/datadog_api_client.py` | Fetches DD context (needs `import re`) |
| `scripts/output_formatter.py` | 4-section PR comment format |
| `scripts/create_scenario_9_pr.sh` | Creates throttling PR (modifies baseline file) |
| `k8s/xray-converter-main-deployment.yaml` | Baseline (500m/1000m) on main; PR branch has 100m/200m |
| `HANDOFF.md` | Product context, 10 scenarios, roadmap |
| `GITHUB_PR_DEMO.md` | PR demo instructions |
| `RUN_FIRST_TIME.md` | First-time run checklist |

---

## Remotes

- `origin` or `myfork` = user's fork (eli-kalish-dd/iac-guardian)
- Push to fork, not upstream (ananth-vaid) — no write access

---

## Open Items / Next Steps

- GitHub Action still has perms errors posting comments — using manual paste for demo.
- Could fix Action perms (e.g. `GITHUB_TOKEN` scope, or PAT with `issues: write`) if automated comments are needed later.
- CEO demo prep: polish UI, ensure Scenario 9 comment looks good, maybe add more scenarios to PR demo flow.
