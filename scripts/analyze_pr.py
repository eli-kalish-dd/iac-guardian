#!/usr/bin/env python3
"""
IaC Guardian - PR Analysis Script
Analyzes infrastructure changes and provides risk assessment
"""

import os
import sys
import json
import re
import time
from typing import Dict, List, Optional
import anthropic
from datadog_api_client import get_datadog_context
from fix_generator import FixGenerator
from github_pr_creator import GitHubPRCreator
from output_formatter import OutputFormatter
from metrics_emitter import emit_analysis_metrics, infer_category, infer_cost_savings

def parse_diff(diff_file: str) -> Dict[str, any]:
    """Parse git diff to extract changed files and their changes"""
    with open(diff_file, 'r') as f:
        diff_content = f.read()

    changes = {
        'files': [],
        'k8s_changes': [],
        'terraform_changes': [],
        'raw_diff': diff_content
    }

    # Extract changed files
    file_pattern = r'diff --git a/(.*?) b/(.*?)(?:\n|$)'
    files = re.findall(file_pattern, diff_content)

    for old_file, new_file in files:
        file_info = {'path': new_file, 'type': None}

        # Determine file type
        if new_file.endswith(('.yaml', '.yml')):
            file_info['type'] = 'kubernetes'
            changes['k8s_changes'].append(file_info)
        elif new_file.endswith('.tf'):
            file_info['type'] = 'terraform'
            changes['terraform_changes'].append(file_info)

        changes['files'].append(file_info)

    # Extract specific K8s changes (replica counts, resource limits)
    replica_changes = re.findall(r'[-+]\s*replicas:\s*(\d+)', diff_content)
    if replica_changes:
        changes['replica_changes'] = replica_changes

    # Extract Terraform instance changes
    instance_changes = re.findall(r'[-+]\s*instance_type\s*=\s*"([^"]+)"', diff_content)
    if instance_changes:
        changes['instance_type_changes'] = instance_changes

    count_changes = re.findall(r'[-+]\s*count\s*=\s*(\d+)', diff_content)
    if count_changes:
        changes['count_changes'] = count_changes

    # Extract K8s memory limit changes
    memory_limit_changes = re.findall(r'[-+]\s*memory:\s*"?(\d+[MmGg][Ii]?)"?', diff_content)
    if memory_limit_changes:
        changes['memory_limit_changes'] = memory_limit_changes

    return changes


def try_create_fix(changes: Dict, datadog_context: Dict, analysis: str) -> Optional[str]:
    """
    Try to generate and create a fix PR

    Returns:
        PR URL if successful, None otherwise
    """
    try:
        # Generate fix
        generator = FixGenerator()
        fix = generator.generate_fix(changes, datadog_context, analysis)

        if not fix:
            if os.getenv('GITHUB_ACTIONS') != 'true':
                print("ℹ️  No automatic fix available for this issue")
            return None

        if os.getenv('GITHUB_ACTIONS') != 'true':
            print(f"\n🔧 Generated fix: {fix['description']}")

        # Create PR
        pr_creator = GitHubPRCreator()
        pr_number = os.getenv('PR_NUMBER')  # From GitHub Actions
        pr_url = pr_creator.create_fix_pr(
            fix=fix,
            original_pr_number=int(pr_number) if pr_number else None
        )

        return pr_url

    except Exception as e:
        if os.getenv('GITHUB_ACTIONS') != 'true':
            print(f"⚠️  Could not create auto-fix: {e}")
        return None


MCP_SERVER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mcp-servers", "datadog-mcp"
)

# Tool definitions Claude can call to query Datadog
_DD_TOOLS = [
    {
        "name": "get_deployment_replicas",
        "description": "Get current and historical replica counts for a Kubernetes deployment. Queries kubernetes_state.deployment.replicas_available.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string", "description": "K8s deployment name"},
                "hours_back": {"type": "integer", "description": "Hours of history to fetch", "default": 168},
            },
            "required": ["deployment_name"],
        },
    },
    {
        "name": "get_deployment_health",
        "description": "Get health signals for a K8s deployment: CPU usage, container restarts, liveness probe failures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string", "description": "K8s deployment name"},
                "hours_back": {"type": "integer", "description": "Hours of history to fetch", "default": 24},
            },
            "required": ["deployment_name"],
        },
    },
    {
        "name": "get_pdb_status",
        "description": "Get PodDisruptionBudget status: disruptions_allowed and pods_desired for a deployment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string", "description": "K8s deployment name"},
            },
            "required": ["deployment_name"],
        },
    },
    {
        "name": "get_hpa_status",
        "description": "Get HorizontalPodAutoscaler status: current vs desired replicas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string", "description": "K8s deployment name"},
            },
            "required": ["deployment_name"],
        },
    },
    {
        "name": "get_service_health",
        "description": "Get health metrics for a service: CPU, restarts, request rate, error rate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Service name"},
                "hours_back": {"type": "integer", "description": "Hours of history to fetch", "default": 24},
            },
            "required": ["service_name"],
        },
    },
    {
        "name": "get_cloud_costs",
        "description": "Get real AWS cloud cost data from Datadog Cloud Cost Management. Returns daily spend for the past 7 days, optionally filtered by AWS product (e.g. 'amazonec2', 'rds', 'elb').",
        "input_schema": {
            "type": "object",
            "properties": {
                "aws_product": {"type": "string", "description": "AWS product filter (e.g. 'amazonec2', 'rds'). Omit for total.", "default": ""},
            },
            "required": [],
        },
    },
    {
        "name": "get_memory_pressure",
        "description": "Get memory usage vs limits for a K8s deployment. Returns avg/max memory usage in MiB per pod and current limit. Use this for any change that modifies memory limits or requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string", "description": "K8s deployment name"},
                "hours_back": {"type": "integer", "description": "Hours of history to fetch", "default": 24},
            },
            "required": ["deployment_name"],
        },
    },
    {
        "name": "get_cpu_pressure",
        "description": "Get CPU usage vs limits for a K8s deployment. Returns avg/max CPU usage in millicores per pod. Use this for any change that modifies CPU limits or requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "deployment_name": {"type": "string", "description": "K8s deployment name"},
                "hours_back": {"type": "integer", "description": "Hours of history to fetch", "default": 24},
            },
            "required": ["deployment_name"],
        },
    },
]


def _execute_dd_tool(tool_name: str, tool_input: Dict) -> str:
    """
    Execute a Datadog tool call by querying the API directly.
    Uses DatadogAPIClient which has real API + mock fallback.
    """
    from datadog_api_client import DatadogAPIClient
    import time

    client = DatadogAPIClient()
    name = tool_input.get("deployment_name") or tool_input.get("service_name", "unknown")
    hours_back = tool_input.get("hours_back", 24)
    now = int(time.time())
    from_ts = now - hours_back * 3600

    def _query(q):
        result = client.query_metrics(q, from_ts, now)
        series = result.get("series", [])
        if not series:
            return f"No data for: {q}"
        pts = series[0].get("pointlist", [])
        vals = [p[1] for p in pts if p[1] is not None]
        if not vals:
            return f"No values for: {q}"
        return (
            f"Query: {q}\n"
            f"  avg={sum(vals)/len(vals):.1f}  max={max(vals):.1f}  "
            f"min={min(vals):.1f}  samples={len(vals)}"
        )

    if tool_name == "get_deployment_replicas":
        r1 = _query(f"avg:kubernetes_state.deployment.replicas_available{{kube_deployment:{name}}}")
        r2 = _query(f"avg:kubernetes_state.deployment.replicas_unavailable{{kube_deployment:{name}}}")
        return f"Deployment Replicas: {name}\n{r1}\n{r2}"

    elif tool_name == "get_deployment_health":
        r1 = _query(f"avg:kubernetes.cpu.usage.total{{kube_deployment:{name}}}")
        r2 = _query(f"sum:kubernetes.containers.restarts{{kube_deployment:{name}}}")
        r3 = _query(f"sum:kubernetes.liveness_probe.failure.total{{kube_deployment:{name}}}")
        return f"Deployment Health: {name}\nCPU: {r1}\nRestarts: {r2}\nLiveness failures: {r3}"

    elif tool_name == "get_pdb_status":
        r1 = _query(f"avg:kubernetes_state.pdb.disruptions_allowed{{kube_deployment:{name}}}")
        r2 = _query(f"avg:kubernetes_state.pdb.pods_desired{{kube_deployment:{name}}}")
        return f"PDB Status: {name}\nDisruptions allowed: {r1}\nPods desired: {r2}"

    elif tool_name == "get_hpa_status":
        r1 = _query(f"avg:kubernetes_state.hpa.current_replicas{{kube_deployment:{name}}}")
        r2 = _query(f"avg:kubernetes_state.hpa.desired_replicas{{kube_deployment:{name}}}")
        return f"HPA Status: {name}\nCurrent: {r1}\nDesired: {r2}"

    elif tool_name == "get_service_health":
        r1 = _query(f"avg:kubernetes.cpu.usage.total{{kube_deployment:{name}}}")
        r2 = _query(f"sum:kubernetes.containers.restarts{{kube_deployment:{name}}}")
        r3 = _query(f"sum:trace.http.request.hits{{service:{name}}}.as_count()")
        return f"Service Health: {name}\nCPU: {r1}\nRestarts: {r2}\nRequests: {r3}"

    elif tool_name == "get_cloud_costs":
        aws_product = tool_input.get("aws_product", "")
        scope = f"aws_product:{aws_product}" if aws_product else "*"
        # Query 7 days of daily costs (aggregated — avoid large fan-out)
        week_ago = now - 7 * 86400
        cost_result = client.query_metrics(
            f"sum:aws.cost.net.amortized{{{scope}}}.rollup(sum, 86400)",
            week_ago,
            now,
        )
        series = cost_result.get("series", [])
        if not series:
            # Fallback: check CCM-specific endpoint format
            cost_result = client.query_metrics(
                f"sum:all.cost{{{scope}}}.rollup(sum, 86400)",
                week_ago,
                now,
            )
            series = cost_result.get("series", [])
        if not series:
            label = f"aws_product:{aws_product}" if aws_product else "total"
            return f"No Cloud Cost Management data for {label}. Using EC2 on-demand pricing for estimates."
        # Aggregate across all series
        all_vals = []
        for s in series:
            all_vals.extend([p[1] for p in s.get("pointlist", []) if p[1] is not None])
        if not all_vals:
            return "CCM returned empty cost data."
        avg_daily = sum(all_vals) / len(all_vals)
        label = f"aws_product:{aws_product}" if aws_product else "all AWS"
        return (
            f"Cloud Cost Management ({label}, last 7 days):\n"
            f"  avg daily cost: ${avg_daily:,.0f}\n"
            f"  avg monthly cost: ${avg_daily * 30:,.0f}\n"
            f"  data points: {len(all_vals)}"
        )

    elif tool_name == "get_memory_pressure":
        # kubernetes.memory.usage returns bytes → convert to MiB (÷ 1048576)
        usage_data = client.query_metrics(
            f"avg:kubernetes.memory.usage{{kube_deployment:{name}}}", from_ts, now
        )
        limit_data = client.query_metrics(
            f"avg:kubernetes.memory.limits{{kube_deployment:{name}}}", from_ts, now
        )

        def _mib_stats(result):
            vals = [p[1] for s in result.get("series", [])
                    for p in s.get("pointlist", []) if p[1] is not None]
            if not vals:
                return None, None
            return sum(vals) / len(vals) / 1048576, max(vals) / 1048576

        avg_use, max_use = _mib_stats(usage_data)
        avg_lim, _ = _mib_stats(limit_data)

        if avg_use is not None:
            line = (f"Memory Pressure — {name}:\n"
                    f"  avg usage: {avg_use:.0f}MiB/pod  max usage: {max_use:.0f}MiB/pod")
            if avg_lim:
                line += f"\n  current limit: {avg_lim:.0f}MiB/pod ({avg_use/avg_lim*100:.0f}% utilized)"
            return line
        return f"Memory Pressure — {name}: No data from Datadog."

    elif tool_name == "get_cpu_pressure":
        # kubernetes.cpu.usage.total returns nanocores → divide by 1e6 for millicores
        # kubernetes.cpu.limits returns cores → multiply by 1000 for millicores
        usage_data = client.query_metrics(
            f"avg:kubernetes.cpu.usage.total{{kube_deployment:{name}}}", from_ts, now
        )
        limit_data = client.query_metrics(
            f"avg:kubernetes.cpu.limits{{kube_deployment:{name}}}", from_ts, now
        )

        def _mc_stats(result, scale):
            vals = [p[1] * scale for s in result.get("series", [])
                    for p in s.get("pointlist", []) if p[1] is not None]
            if not vals:
                return None, None
            return sum(vals) / len(vals), max(vals)

        avg_use, max_use = _mc_stats(usage_data, 1e-6)   # nanocores → millicores
        avg_lim, _ = _mc_stats(limit_data, 1000.0)        # cores → millicores

        if avg_use is not None:
            line = (f"CPU Pressure — {name}:\n"
                    f"  avg usage: {avg_use:.0f}m/pod  max usage: {max_use:.0f}m/pod")
            if avg_lim:
                line += f"\n  current limit: {avg_lim:.0f}m/pod ({avg_use/avg_lim*100:.0f}% utilized)"
            return line
        return f"CPU Pressure — {name}: No data from Datadog."

    return f"Unknown tool: {tool_name}"


DD_MCP_URL = "https://mcp.datadoghq.com/api/unstable/mcp-server/mcp"


def analyze_with_mcp(changes: Dict) -> Dict:
    """
    Analyze infrastructure changes with Claude using the official Datadog MCP server.

    Uses the Anthropic API MCP beta (type=url) to connect to mcp.datadoghq.com —
    the same server Claude Code uses. Claude actively calls Datadog tools to fetch
    real metrics, then produces a risk assessment.

    Falls back to the multi-turn tool-use approach (with mock data) if MCP fails.

    Returns:
        dict with keys: 'analysis' (str | None), 'data_source' ("mcp" | "mock")
    """
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return {"analysis": None, "data_source": "mock"}

    diff_summary = f"Files changed: {len(changes['files'])}"
    if changes.get('replica_changes'):
        diff_summary += f"\nReplica count changes: {changes['replica_changes']}"
    if changes.get('instance_type_changes'):
        diff_summary += f"\nInstance type changes: {changes['instance_type_changes']}"
    if changes.get('count_changes'):
        diff_summary += f"\nResource count changes: {changes['count_changes']}"

    prompt = f"""You are IaC Guardian, an infrastructure risk analyzer with access to Datadog.

Analyze this infrastructure change:

## Summary
{diff_summary}

## Full Diff
```diff
{changes['raw_diff'][:3000]}
```

## AWS EC2 On-Demand Pricing Reference (us-east-1, per month = $/hr × 730hr)
- t3.medium: $30/mo  t3.large: $61/mo  t3.xlarge: $122/mo
- m5.xlarge: $154/mo  m5.2xlarge: $308/mo  m5.4xlarge: $616/mo
- c5.xlarge: $124/mo  c5.2xlarge: $248/mo  c5.4xlarge: $496/mo  c5.9xlarge: $1,117/mo

Instructions:
1. For K8s changes: call get_deployment_replicas / get_deployment_health / get_pdb_status / get_hpa_status / get_memory_pressure / get_cpu_pressure as appropriate.
2. For EC2/instance count changes: call get_cloud_costs for CCM context, then use the pricing table for the before/after delta.
3. For security group changes: no tool call needed — assess from the diff directly.
4. Respond in EXACTLY this 4-section format. Each section is mandatory.

## Risk Level: [CRITICAL/HIGH/MEDIUM/LOW]

## What Changed
[One factual sentence describing what the PR does and its direct impact. No judgment — just facts.
Examples:
- "Reduces xray-converter-main replicas from 225 to 20."
- "Scales data-processor fleet from 5× c5.2xlarge ($1,240/mo) to 10× c5.4xlarge ($4,960/mo, +$3,720/mo)."
- "Reduces xray-converter-main memory limit from 512Mi to 128Mi per pod."
- "Adds a new deployment (intake-processor) with no CPU or memory limits defined."
- "Opens SSH port 22 to 0.0.0.0/0 on the intake-api-servers security group."]

## Why This is a Problem
[1-2 sentences. Lead with the DATA or hard technical reason. This is the critical section — it must explain WHY the change is dangerous, not just repeat what changed.
Rules by type:
- Replica reduction: "Datadog shows peak traffic required N replicas at X% CPU [last week/period] — cutting to M leaves only P% of peak capacity with no buffer."
- Cost over-provision: "Datadog shows the current fleet runs at X% avg CPU / Y% peak — well below the ~70% threshold where additional capacity helps. This change adds 4× capacity for demand that doesn't exist."
- Memory limit: "Datadog shows pods using ~XMi steady-state — the proposed YMi limit leaves only ZMi headroom. Any GC pause or traffic spike triggers OOMKill across all N pods."
- CPU limit: "Datadog shows avg Xm / peak Ym CPU per pod. The proposed Zm limit means pods are throttled at normal load, not just spikes — expect latency increases."
- Missing health probes: "Without liveness/readiness probes, Kubernetes cannot detect stuck or crashed containers, so broken pods stay in the load balancer rotation and receive live traffic."
- Missing PDB: "Without a PodDisruptionBudget, a node drain or rolling deploy can evict all N pods at once — full service outage for the duration."
- Missing resource limits: "Without CPU/memory limits, this pod can consume the entire node's resources, starving every other pod on the node and triggering cascading evictions."
- Security group: "SSH (port 22) is now exposed to every IP on the internet, not just internal VPN range."
- If Datadog has no data for the service: state the IaC risk clearly, then add: "Datadog has no metrics for <service> to confirm current utilization."]

## What To Do
[1-2 bullets. Concrete and specific — include actual numbers, config values, or alternatives.
Examples:
- "Keep replicas at 225; if cost reduction is needed, add an HPA with minReplicas: 150 and scale down only when CPU drops below 40% for 15+ minutes."
- "Keep 5× c5.2xlarge ($1,240/mo); set a CPU alert at 70% utilization and scale only when demand materializes."
- "Set memory limit to at least 200Mi (current usage + 75% buffer); verify with: kubectl top pods -l app=xray-converter-main."
- "Add a resources block with CPU request: 200m, limit: 500m and memory request: 256Mi, limit: 512Mi."
- "Add a PodDisruptionBudget with minAvailable: N-1 (e.g. minAvailable: 11 for a 12-replica deployment)."
- "Restrict cidr_blocks to your VPN range (e.g. 10.0.0.0/8) instead of 0.0.0.0/0."]

Risk level calibration:
- CRITICAL: Immediate production outage (will crash under current load) OR immediate security exposure (0.0.0.0/0)
- HIGH: Likely outage under normal conditions (memory OOMKill, CPU starvation, missing PDB, low replicas)
- MEDIUM: Degraded performance or cost waste, but won't immediately crash (over-provisioned, suboptimal config)
- LOW: Best-practice violation with minimal near-term risk

IMPORTANT: Do NOT use code blocks (```) in any section. Plain text only.
Keep it SHORT. A busy engineer needs to understand in 10 seconds.
"""

    # Try: official Datadog MCP server via Anthropic API URL-type MCP beta
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            mcp_servers=[{"type": "url", "url": DD_MCP_URL, "name": "datadog",
                          "authorization_token": os.getenv("DATADOG_API_KEY", "")}],
            betas=["mcp-client-2025-04-04"],
        )
        analysis_text = next(
            (b.text for b in reversed(response.content) if hasattr(b, "text")), ""
        )
        if analysis_text:
            return {"analysis": analysis_text, "data_source": "mcp"}
    except Exception as e:
        if os.getenv('GITHUB_ACTIONS') != 'true':
            print(f"⚠️  DD MCP URL failed ({e}), trying tool-use fallback")

    # Fallback: multi-turn tool-use loop with DatadogAPIClient (real API or mock)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        messages = [{"role": "user", "content": prompt}]

        for _ in range(6):
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                tools=_DD_TOOLS,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                analysis_text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                return {"analysis": analysis_text, "data_source": "mcp"}

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if os.getenv('GITHUB_ACTIONS') != 'true':
                        print(f"🔧 Calling {block.name}({block.input})")
                    result = _execute_dd_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        if os.getenv('GITHUB_ACTIONS') != 'true':
            print(f"⚠️  Tool-use fallback also failed ({e})")

    return {"analysis": None, "data_source": "mock"}


def analyze_with_claude(changes: Dict, datadog_context: Optional[Dict] = None) -> str:
    """Send changes to Claude for analysis (fallback when MCP is unavailable)"""

    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return "❌ Error: ANTHROPIC_API_KEY not set"

    client = anthropic.Anthropic(api_key=api_key)

    # Build context for Claude
    context = f"""You are an infrastructure expert reviewing a pull request for potential issues.

## Changes Detected:
- Files changed: {len(changes['files'])}
- Kubernetes changes: {len(changes['k8s_changes'])} files
- Terraform changes: {len(changes['terraform_changes'])} files

## Specific Changes:
"""

    if changes.get('replica_changes'):
        context += f"- Replica count changes: {changes['replica_changes']}\n"

    if changes.get('instance_type_changes'):
        context += f"- Instance type changes: {changes['instance_type_changes']}\n"

    if changes.get('count_changes'):
        context += f"- Resource count changes: {changes['count_changes']}\n"

    if datadog_context:
        context += f"\n## Real-time Datadog Metrics:\n{json.dumps(datadog_context, indent=2)}\n"

    context += f"\n## Full Diff:\n```diff\n{changes['raw_diff'][:3000]}\n```\n"

    prompt = f"""{context}

Analyze this infrastructure change and provide a CRISP, SHORT analysis in exactly this format:

## Risk Level: [CRITICAL/HIGH/MEDIUM/LOW]

## Why This is Risky
[1-2 sentences max. Focus on the specific IaC issue in the diff. Rules:
- Missing health probes: "No liveness/readiness probes — Kubernetes cannot detect if the container is stuck, so broken pods keep receiving traffic."
- Insufficient replicas: "N replicas in production means a single pod failure or rolling update leaves M pods serving traffic — no HA guarantee."
- Missing PodDisruptionBudget: "No PDB on a multi-replica service — during node drain or rolling update, Kubernetes can evict all pods simultaneously, causing full downtime."
- Security group too open: "Port X open to 0.0.0.0/0 — exposed to the entire internet."
Respond in EXACTLY this 4-section format:

## Risk Level: [CRITICAL/HIGH/MEDIUM/LOW]

## What Changed
[One factual sentence: what does this PR do and what is the direct impact? No judgment.
E.g.: "Scales data-processor fleet from 5× c5.2xlarge ($1,240/mo) to 10× c5.4xlarge ($4,960/mo, +$3,720/mo)."]

## Why This is a Problem
[1-2 sentences. Lead with DATA or technical reason WHY this is dangerous/wasteful — not just a repeat of what changed.
- Cost over-provision: include current utilization from Datadog (e.g. "Current fleet runs at 15% avg CPU — well below the ~70% threshold where more capacity helps. This adds 4× capacity for demand that doesn't exist.")
- Replica reduction: include peak traffic data if available
- Memory/CPU: include usage vs proposed limit
- Missing probes/PDB/limits: explain the failure mode concisely
- If no Datadog data: explain the IaC risk, then note "Datadog has no metrics for <service>."]

## What To Do
[1-2 bullets. Concrete numbers and alternatives.
E.g.: "Keep 5× c5.2xlarge; set a CPU alert at 70% and scale only when demand materializes."]

Risk level calibration:
- CRITICAL: Immediate outage or 0.0.0.0/0 security exposure
- HIGH: Likely failure under normal conditions (OOMKill, starvation, missing PDB, low replicas)
- MEDIUM: Cost waste or degraded performance but won't immediately crash
- LOW: Best-practice violation with minimal near-term risk

IMPORTANT: Do NOT use code blocks (```) in the What To Do section. Plain text bullets only.
Keep it SHORT and PUNCHY. A busy engineer needs to understand in 10 seconds.
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        return response.content[0].text

    except Exception as e:
        return f"❌ Error calling Claude API: {str(e)}"


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_pr.py <diff_file>")
        sys.exit(1)

    diff_file = sys.argv[1]

    if not os.path.exists(diff_file):
        print(f"❌ Error: Diff file not found: {diff_file}")
        sys.exit(1)

    # Parse the diff
    changes = parse_diff(diff_file)

    if not changes['files']:
        print("ℹ️ No infrastructure changes detected in this PR.")
        sys.exit(0)

    t_start = time.time()

    # Try MCP-powered analysis first (uses real Datadog data via local MCP server)
    mcp_result = analyze_with_mcp(changes)
    if mcp_result.get("analysis"):
        analysis = mcp_result["analysis"]
        data_source = mcp_result["data_source"]
        datadog_context = {"data_source": data_source}  # Signal for auto-fix path
    else:
        # Fallback: get Datadog context via REST API (may use mock data)
        datadog_context = get_datadog_context(changes)
        analysis = analyze_with_claude(changes, datadog_context)
        data_source = "mock"

    duration_ms = (time.time() - t_start) * 1000

    # Check if auto-fix is enabled and issue is detected
    auto_fix_enabled = os.getenv('IAC_GUARDIAN_AUTO_FIX', 'true').lower() == 'true'

    fix_pr_url = None
    if auto_fix_enabled and datadog_context:
        # Try to generate and create fix
        fix_pr_url = try_create_fix(changes, datadog_context, analysis)

    # Emit metrics to Datadog (silent no-op if no DD keys)
    risk_match = re.search(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', analysis)
    risk_level = risk_match.group(1) if risk_match else "LOW"
    repo = os.getenv('GITHUB_REPOSITORY', 'unknown')
    scenario_type = changes.get('files', [{}])[0].get('file', '').split('/')[-1].replace('.yaml', '').replace('.tf', '')
    category = infer_category(scenario_type, analysis)
    cost_savings = infer_cost_savings(analysis)
    emit_analysis_metrics(
        risk_level=risk_level,
        scenario_type=scenario_type,
        repo=repo,
        data_source=data_source,
        category=category,
        cost_savings_annual=cost_savings,
        duration_ms=duration_ms,
    )

    # Format and output the analysis
    formatter = OutputFormatter()

    # Check if we're outputting for GitHub (has GITHUB_ACTIONS env) or terminal
    is_github = os.getenv('GITHUB_ACTIONS') == 'true'

    if is_github:
        # Format for GitHub PR comment (concise format)
        formatted_output = formatter.format_for_github_concise(analysis, fix_pr_url)
    else:
        # Format for terminal (clean, no HTML)
        formatted_output = formatter.format_for_terminal(analysis, fix_pr_url)

    print(formatted_output)


if __name__ == "__main__":
    main()
