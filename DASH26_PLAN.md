# IaC Guardian → Dash '26 Product Plan

## Context
February 2026. Hackathon demo is working: pre-commit hook, GitHub Actions bot, Streamlit UI, 6 scenarios, Claude analysis. Dash '26 is ~4–5 months away (typically June/July). Scope: **Kubernetes only** for Preview — raw YAML + Helm, across cost/reliability/performance/security. Terraform deferred to GA+.

**Recommendation: Preview (Limited Availability) at Dash '26, GA 6 months after.**
GA in 4 months is not credible. Preview with 5–10 design partners is.

---

## The Product: "K8s Change Intelligence"

**One sentence:** Every Kubernetes change — whether raw YAML or Helm values — analyzed against your live Datadog telemetry before it hits production.

**Why only Datadog can do this:**
- Static linters (Kubelinter, Checkov, Datree) catch syntax and best-practice violations. They don't know your traffic patterns.
- Datadog has CPU/memory/request/error data per service. We can answer "will this specific change, on this specific service, at this specific traffic level, cause an incident?"
- Cloud Cost Management gives actual $/pod, not AWS list price guesses.
- SLO + incident history: "this pattern caused a 23-min outage last Tuesday."

**Where it sits:** Software Delivery (alongside CI Visibility, Test Visibility). New surface: **Change Intelligence**.

---

## Where Helm Fits

Most production K8s workloads are NOT deployed as raw YAML. Engineers write `values.yaml` overrides and Helm handles the templating. So:

- A developer changing `replicas: 5` in `values.yaml` is the same risk as changing it in a raw deployment manifest — but today, linters miss it because they only see the override, not the rendered manifest.
- **The right approach: render first, then analyze.**
  1. Detect Helm chart changes (values.yaml, Chart.yaml, templates/)
  2. Run `helm template` in CI to produce the rendered manifests
  3. Analyze the rendered output against Datadog telemetry — same engine as raw YAML

This means engineers get the same quality of analysis regardless of how their team delivers K8s workloads. Helm support is not a "nice to have" — it's required to cover the majority of real production deployments.

**Input surface priority:**
1. Raw K8s YAML (manifests) — Preview
2. Helm values.yaml changes → render → analyze — Preview
3. Kustomize overlays — Post-Preview
4. ArgoCD/Flux Application CRDs — GA

---

## K8s Check Coverage — What We Know vs. What Needs Validation

**Important:** The checks below are hypotheses, not a validated list. Before committing engineering resources, each must be ranked by **frequency × impact × Datadog differentiation**. Four parallel workstreams can collect this data (see section below).

### Confidence tiers

**Tier 1 — High confidence (validated by public incident data + intuition)**
These appear repeatedly in k8s.af, CNCF failure stories, and internal postmortems. Ship these first.

| Check | Evidence basis | Datadog differentiation |
|---|---|---|
| Replica reduction vs. peak traffic | k8s.af: most common cause of cascading failures. Demo scenario 1. | HIGH — only we have the traffic data |
| Missing liveness/readiness probes | Extremely common in k8s.af; causes silent failures | LOW — Kubelinter already catches this |
| Missing PodDisruptionBudget | k8s.af: frequent cause of rolling-update outages | MEDIUM — static catch, but we can add "this service had 3 restarts last week" |
| CPU over-request vs. actual usage | Cloud Cost Management already shows this pattern at scale | HIGH — we have the telemetry |

**Tier 2 — Medium confidence (plausible but unvalidated)**
Good hypotheses. Need data before building.

| Check | What's unknown | How to validate |
|---|---|---|
| Insufficient replicas (<3, no HPA) | Is 3 the right threshold? Varies by service criticality | Customer interviews + DD replica distribution data |
| CPU throttling → latency impact | Threshold (20%?) is made up | Pull DD container.cpu.throttled metric across fleet; find natural breakpoint |
| No HPA on latency-sensitive service | Which services "should" have HPA is context-dependent | Interview SREs; look at p99 latency variance vs. HPA presence in DD fleet data |
| Memory limit < 2× request | The 2× ratio is a guess | Analyze OOM kill events in DD fleet; what was the limit/request ratio at time of kill? |
| Rolling update maxUnavailable=100% | How common is this misconfiguration in practice? | Query DD fleet data: distribution of maxUnavailable values |

**Tier 3 — Low confidence (intuitive but need evidence)**
Don't build until Tier 1+2 are validated.

| Check | Why low confidence |
|---|---|
| No topology spread constraints | Unclear how often this causes real incidents vs. being a theoretical risk |
| Idle workload (0 traffic for 7d) | Cost impact unclear; might be intentional (batch jobs, standby) |
| Image without digest pinning | Real security risk but: do customers care? Is this table stakes for CSPM? |
| Privileged container / hostNetwork | Already caught by CSPM and Kubelinter — low differentiation |

---

## Data Collection Workstreams

Four parallel tracks. Start all simultaneously. 4–6 weeks to results.

---

### Workstream 1: Mine Datadog's own fleet data
**Goal:** Understand the actual distribution of K8s misconfigurations across customer clusters.
**Owner:** Data/Analytics team + K8s product team
**Timeline:** 4 weeks

What to pull from the Datadog fleet (with appropriate privacy/aggregation):
- Distribution of `maxUnavailable` values across Deployments
- % of Deployments with no liveness probe, no readiness probe, no PDB
- % of services with HPA vs. no HPA, split by p99 latency variance
- Distribution of CPU request vs. p95 actual usage (over-request ratio)
- OOM kill event rate vs. memory limit/request ratio at time of kill
- Idle workload prevalence (0 req/min for 7d but replicas > 0)

**Output:** Ranked frequency table of each Tier 2/3 hypothesis. If a misconfiguration affects <1% of clusters, deprioritize it.

---

### Workstream 2: Incident postmortem analysis
**Goal:** Ground the "impact" dimension. Which K8s misconfigs actually caused production incidents?
**Owner:** SRE / Reliability team
**Timeline:** 4 weeks

**Internal (Datadog):**
- Tag last 12 months of Datadog-internal incident postmortems by root cause category
- Specifically: which incidents were caused by a K8s config change?
- Map each to a check hypothesis

**External (public):**
- Systematically categorize all 100+ incidents on [k8s.af](https://k8s.af) by check type
- Weight by recency and company scale (Netflix outage > small startup)

**Output:** Impact score per check. Combined with Workstream 1 frequency data → priority matrix.

---

### Workstream 3: Customer interviews
**Goal:** Validate that engineers will actually use this, and what they care about most.
**Owner:** Product + Customer Success
**Timeline:** 4–6 weeks, 10–15 interviews

Target: SREs and platform engineers at companies with >50 engineers and K8s in production.

Key questions:
- "Walk me through the last K8s change that caused an incident. What was the config? What did you wish you'd caught earlier?"
- "What does your current IaC review process look like? What does it miss?"
- "If a bot flagged a PR for you, what would make you trust it? What would make you ignore it?"
- "Where do Helm values changes live in your workflow? Who reviews them?"
- "What % of your K8s workloads are managed by Helm vs. raw YAML vs. GitOps?"

**Output:** Qualitative validation of check priorities + UX requirements (what makes the bot trustworthy vs. ignorable). Also: Helm adoption rate to confirm it's Preview scope, not post-GA.

---

### Workstream 4: Competitive teardown
**Goal:** Understand what checks are already commoditized (low differentiation) vs. where we're unique.
**Owner:** Product
**Timeline:** 2 weeks

Tools to analyze:
- **Kubelinter, Datree, Checkov, Terrascan** — what do they catch? (likely: probes, PDB, privileged containers, image pinning)
- **Reliably, Steadybit** — chaos/reliability angle
- **Cortex, Backstage** — developer portal / service catalog approach
- **GitHub Copilot for infra** — what's Microsoft building?

For each check hypothesis: mark it **Commoditized** (competitors already do it) or **Differentiated** (requires runtime telemetry → only Datadog).

**Output:** Strike any check from the list that's already well-covered by free tools. Double down on the ones only we can do (replica reduction vs. live traffic is the clearest example).

---

## Check Prioritization Framework (post-data collection)

Score each check 1–5 on three dimensions:

| Dimension | What it measures |
|---|---|
| **Frequency** | How often does this misconfiguration appear in production? (from Workstream 1) |
| **Impact** | How bad is the outcome when it triggers? (from Workstream 2) |
| **Differentiation** | Can only Datadog catch this, or do free tools already do it? (from Workstream 4) |

**Priority = Frequency × Impact × Differentiation**

Only build checks scoring above a threshold. Don't build 15 checks — build 6 great ones.

---

## What to Ship for Preview

1. **Real Datadog API integration** — CPU/memory p95, request rate, error rate, Cloud Cost Management per service.
2. **GitHub App** (native, not Actions YAML) — PR check status (✅/⚠️/❌) not just a comment. Engineers see it in the merge gate.
3. **Helm support** — detect values.yaml changes, run `helm template`, analyze rendered output.
4. **Rules engine + LLM hybrid** — deterministic rules for static checks, Claude for capacity math and incident correlation.
5. **~6–8 validated K8s checks** (to be finalized after data collection workstreams).
6. **Suppression rules** — per-team, per-service overrides. Critical for adoption; false positives kill trust.

### Deferred to GA
- Kubernetes admission webhook (enforce in-cluster)
- Kustomize, ArgoCD/Flux
- Per-service risk threshold UI
- Outcome tracking / feedback loop
- Terraform

---

## Timeline (Feb → Dash '26)

| Month | Milestone |
|---|---|
| **Feb–Mar** | Real DD API, GitHub App, rules engine, Helm render pipeline |
| **Mar–Apr** | All validated K8s checks, Cloud Cost Management integration |
| **Apr–May** | Design partner onboarding (5–10 internal DD teams + external beta) |
| **May** | Dogfood: Datadog engineering ships K8s changes through this daily |
| **Jun** | Dash '26 Preview announcement, public waitlist opens |
| **Jun–Dec** | GA: admission webhook, Kustomize, suppression UI, outcome tracking |

---

## The Dash Announcement

**Title:** "Know before you deploy — K8s Change Intelligence, powered by Datadog"

**Demo arc (10 min):**
1. Raw YAML: replica reduction 20→5, DD shows last Tuesday needed 18 pods at 85% CPU → CRITICAL, blocked
2. Helm: engineer bumps `resources.cpu.requests` in values.yaml → rendered manifest shows throttling risk → HIGH
3. Cost: Helm values double instance count → Cloud Cost Management shows $5,040/mo increase, current pods at 15% CPU → MEDIUM with right-sizing recommendation
4. Admission webhook: bad deploy attempted directly with kubectl → blocked in-cluster
5. Datadog UI: Change Intelligence dashboard — risk history, cost savings, team breakdown

**The line that lands on stage:** *"Every other tool tells you your YAML is valid. Datadog tells you if it will survive Tuesday at 2pm."*

---

## Risks

| Risk | Mitigation |
|---|---|
| False positive rate kills adoption | Dogfood period to tune; suppressions from day 1; show confidence % |
| Helm render in CI adds complexity | Ship as optional; document setup; provide Actions template |
| LLM latency (>30s) blocks PRs | Rules engine handles 80% instantly; LLM async with 60s timeout |
| "Just use Kubelinter/Checkov" objection | Those do static analysis. We do static + runtime telemetry. Different category. |
| Datadog API permissions friction | Read-only metrics scope only; no new agents needed |
