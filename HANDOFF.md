# IaC Guardian — Handoff to Eli

## What This Is

Hackathon proof-of-concept of "K8s Shift Left." Works end-to-end with real Datadog metrics.
**This is a live demo/spec, not production code.** Engineers rebuild the backend properly;
the prototype shows exactly what it should do and that it works.

**Repo:** https://github.com/ananth-vaid/iac-guardian

---

## What the Prototype Proved

- **Claude + DD MCP works** — Real DD metrics (replica counts, CPU/memory, CCM costs) grounded in PR comments
- **4-section comment format resonates** — Risk Level / What Changed / Why It's a Problem / What To Do
- **IaC drift detection is novel** — Comparing spec vs. live replica count catches a real class of bug
- **10 scenarios validated** — K8s replica, memory, CPU, health checks, PDB, HPA ceiling, cost, security group
- **CI integration is trivial** — GH Actions workflow is ~90 lines; GitHub App is the real work

---

## 1-Hour Session Agenda

Walk these 3 live PRs — each shows a different analysis capability:

| PR | Scenario | Key point |
|----|----------|-----------|
| [#8 — IaC Drift](https://github.com/ananth-vaid/iac-guardian/pull/8) | Spec says 225 replicas, reduce to 20 | Spec vs. live count divergence |
| [#14 — Memory OOMKill](https://github.com/ananth-vaid/iac-guardian/pull/14) | Cut memory limit 512Mi→128Mi | Live usage data prevents OOMKill |
| [#17 — HPA Ceiling](https://github.com/ananth-vaid/iac-guardian/pull/17) | Lower HPA maxReplicas 300→200 | Live pod count (225) exceeds new ceiling |

Then walk `scripts/analyze_pr.py` — the core of the system, ~300 lines, one file.

**Pipeline:** GH Actions → `analyze_pr.py` → Claude Sonnet 4.6 + DD MCP → 4-section comment

---

## Key Files

| File | What it does |
|------|-------------|
| `scripts/analyze_pr.py` | Core analysis — `_DD_TOOLS`, `_execute_dd_tool()`, `analyze_with_mcp()`, `parse_diff()` |
| `scripts/output_formatter.py` | `format_for_github_concise()` — produces the 4-section PR comment |
| `scripts/fix_generator.py` | Detects issue type (replica/memory/cost) and generates suggested fix |
| `scripts/datadog_api_client.py` | Extracts service name from diff, fetches DD context |
| `app.py` | Streamlit UI — scenario selector at lines ~307–460, all diff content inline |
| `.github/workflows/` | GH Actions workflows that trigger analysis on PR |

---

## All 10 Scenarios (Working Today)

| # | Scenario | Service | DD Data |
|---|----------|---------|---------|
| 1 | Peak Traffic Risk | `xray-converter-main` | 225 pods live |
| 2 | Cost Optimization | fictional EC2 fleet | CCM total cost |
| 3 | Missing Health Checks | `errors-logs-extractor-logs-datadog-5cb9` | 51 pods live |
| 4 | Missing PodDisruptionBudget | `appsec-reducer-signal-6cf25-datadog-sep` | 12 pods live |
| 5 | Insufficient Replicas | `k8s-lifecycle-publisher-shared-bone` | 4 pods live |
| 6 | Security Group Open | `intake-api-servers` (Terraform) | static analysis |
| 7 | Memory Limit OOMKill | `xray-converter-main` | ~113 MiB/pod live |
| 8 | Missing Resource Limits | `intake-processor` (new deploy) | static analysis |
| 9 | CPU Limit Throttling | `xray-converter-main` | ~158m avg / 188m peak |
| 10 | HPA Ceiling Too Low | `xray-converter-main` | 225 pods > 200 ceiling |

---

## PR Comment Format

```
## Risk Level: [CRITICAL/HIGH/MEDIUM/LOW]
## What Changed
[One factual sentence, no judgment]
## Why This is a Problem
[1-2 sentences with DD data as evidence]
## What To Do
[1-2 concrete bullets with numbers]
```

---

## What Already Exists at Datadog (Reuse First)

| Asset | Location |
|-------|----------|
| **105-scenario K8s eval set** | `DataDog/experimental/teams/container-apps/k8s-manifests/failure-scenarios` |
| **Container-apps team** | Already familiar with K8s failure patterns — natural eng owners |
| **Multi-hop cascade scenarios** | `failure-scenarios/pods/24-28-*-chain-*.yaml` — highest-value detections |
| **ECS + Terraform examples** | `DataDog/experimental/teams/container-apps/ecs-terraform` |

Use the 105-scenario set as the eval set for comment quality. Define the quality bar before writing a line of production code.

---

## Roadmap to Dash (June 2026)

### Phase 1: Find eng owners + align on scope (→ Mar 14)
- Identify eng owner from container-apps team (they own the eval set)
- Align on MVP scope: raw K8s YAML only (no Helm/Kustomize), commenting only (no gating)
- Decision: GitHub App (right long-term) vs. GH Actions workflow (faster to ship)
- Align on LLM platform: Anthropic API vs. Bits AI / internal

### Phase 2: Architecture + GitHub App (→ Apr 11)
- GitHub App: installs at org level, auto-monitors K8s PRs (no per-repo config)
- Multi-tenant auth: customer links GitHub org → their DD org via OAuth
- Scoped DD context: customer's own service metrics, not hardcoded API keys
- Use the 105-scenario eval set to define quality bar before building

### Phase 3: Build Preview (→ May 9)
- GitHub App posting comments on customer K8s PRs
- Live DD context: replica count, CPU/memory metrics, cost
- Links to DD entity pages in comment
- Eval pipeline running against 105-scenario set (quality gate before ship)
- Dogfood: enable on `datadog/datadog` K8s manifests internally

### Phase 4: Design Partners (→ May 30)
- 5–10 design partners (teams already using DD K8s monitoring)
- Measure: false positive rate, comment quality, time-to-merge impact
- Collect "Guardian caught this" stories for Dash talk

### Phase 5: Dash (Jun 6)
- Live demo: open PR → Guardian comment in <60s → fix → gate clears
- Announce Preview availability

---

## Key Decisions to Make in Phase 1

| Decision | Options | Recommendation |
|----------|---------|----------------|
| GH integration | GitHub App vs. GH Actions | App (right long-term); GH Actions if timeline slips |
| LLM platform | Anthropic API vs. Bits AI | Align with DD AI platform team first |
| Scope at Preview | Raw YAML only vs. Helm | YAML only — Helm needs `helm template` in CI, adds 4-6 weeks |
| PR gating at Dash | Yes vs. No | No — comment-only for Preview, gating post-Dash |
| Eval ownership | container-apps team or new | container-apps team already owns the 105-scenario set |

---

## Dash Demo Script (Target)

1. Engineer opens PR: reduces `xray-converter-main` replicas 32 → 10
2. Guardian posts in <60s: *"CRITICAL: Live DD shows 32 replicas at 159m CPU avg / 189m peak. Dropping to 10 → 509m avg vs. 612m limit."*
3. PR gate blocks merge
4. Engineer bumps to 20 → Guardian re-runs → MEDIUM → gate clears

---

## Run the Prototype Locally

```bash
cd iac-guardian
set -a && source .env && set +a
streamlit run app.py
# → http://localhost:8501
```

Needs `DATADOG_API_KEY` and `DATADOG_APP_KEY` in `.env`. Real API calls fire against `xray-converter-main`.
