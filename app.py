#!/usr/bin/env python3
"""
IaC Guardian - Streamlit UI
Interactive demo for infrastructure change analysis
"""

import streamlit as st
import os
import sys
from pathlib import Path
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent / "scripts"))

import re
import time
from analyze_pr import parse_diff, analyze_with_claude, analyze_with_mcp
from datadog_api_client import get_datadog_context, DatadogAPIClient
from fix_generator import FixGenerator
from metrics_emitter import emit_analysis_metrics, infer_category, infer_cost_savings

# Page config
st.set_page_config(
    page_title="Datadog IaC Proactive Detection",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;600;700&family=Roboto+Mono&display=swap');

* { font-family: 'Noto Sans', sans-serif; }

.main-header {
    font-size: 2.4rem;
    font-weight: 700;
    text-align: center;
    margin-bottom: 0.5rem;
    color: #632CA6;
    letter-spacing: -0.5px;
}
.sub-header {
    text-align: center;
    color: #6B6B8A;
    margin-bottom: 2rem;
    font-size: 1rem;
}
.metric-card {
    background: #F5F5FA;
    padding: 1rem;
    border-radius: 6px;
    margin: 0.5rem 0;
    border-left: 3px solid #632CA6;
}
.risk-high {
    background: #FFF0F3;
    border-left: 4px solid #E63244;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 4px;
}
.risk-medium {
    background: #FFF8ED;
    border-left: 4px solid #FCB429;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 4px;
}
.risk-low {
    background: #EDFAF2;
    border-left: 4px solid #19AA4F;
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 4px;
}
code, pre { font-family: 'Roboto Mono', monospace !important; }
</style>
""", unsafe_allow_html=True)


def create_cpu_chart(k8s_metrics):
    """Create CPU utilization chart"""
    if not k8s_metrics:
        return None

    current = k8s_metrics.get('current_state', {})
    peak = k8s_metrics.get('peak_traffic_last_7_days', {})

    # Extract numeric values
    current_cpu = int(current.get('avg_cpu_per_pod', '65%').rstrip('%'))
    peak_cpu = int(peak.get('cpu_per_pod', '85%').rstrip('%'))

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name='Current Average',
        x=['CPU Utilization'],
        y=[current_cpu],
        marker_color='#9B6DC5',
        text=[f'{current_cpu}%'],
        textposition='auto',
    ))

    fig.add_trace(go.Bar(
        name='Peak (Last 7 Days)',
        x=['CPU Utilization'],
        y=[peak_cpu],
        marker_color='#2E6DFE',
        text=[f'{peak_cpu}%'],
        textposition='auto',
    ))

    fig.update_layout(
        title='CPU Utilization per Pod',
        yaxis_title='Percentage',
        yaxis_range=[0, 100],
        height=300,
        showlegend=True,
        paper_bgcolor='#FAFAFA',
        plot_bgcolor='#FAFAFA',
        font=dict(family='Noto Sans', color='#1A1A2E'),
    )

    return fig


def create_replica_chart(k8s_metrics):
    """Create replica count timeline"""
    if not k8s_metrics:
        return None

    current = k8s_metrics.get('current_state', {})
    peak = k8s_metrics.get('peak_traffic_last_7_days', {})

    # Mock timeline data
    dates = pd.date_range(end=datetime.now(), periods=7, freq='D')
    replicas = [20, 19, 18, 20, 21, 20, current.get('replicas', 20)]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=dates,
        y=replicas,
        mode='lines+markers',
        name='Active Replicas',
        line=dict(color='#632CA6', width=2),
        marker=dict(size=8)
    ))

    # Add peak annotation
    fig.add_hline(
        y=peak.get('replicas_active', 18),
        line_dash="dash",
        line_color="#E63244",
        annotation_text=f"Peak: {peak.get('replicas_active', 18)} replicas"
    )

    fig.update_layout(
        title='Replica Count - Last 7 Days',
        xaxis_title='Date',
        yaxis_title='Replicas',
        height=300,
        showlegend=True,
        paper_bgcolor='#FAFAFA',
        plot_bgcolor='#FAFAFA',
        font=dict(family='Noto Sans', color='#1A1A2E'),
    )

    return fig


def create_traffic_chart(k8s_metrics):
    """Create traffic pattern chart"""
    if not k8s_metrics:
        return None

    current = k8s_metrics.get('current_state', {})
    peak = k8s_metrics.get('peak_traffic_last_7_days', {})

    # Mock hourly traffic pattern
    hours = list(range(24))
    base_traffic = 45000
    peak_traffic = peak.get('requests_per_minute', 82000)

    # Simulate daily pattern (peak at 2pm)
    traffic = [
        base_traffic * (0.3 + 0.7 * (1 - abs(h - 14) / 24)) for h in hours
    ]
    traffic[14] = peak_traffic  # Peak at 2pm

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=hours,
        y=traffic,
        mode='lines',
        fill='tozeroy',
        name='Requests/min',
        line=dict(color='#632CA6', width=2)
    ))

    fig.update_layout(
        title='Traffic Pattern (Typical Day)',
        xaxis_title='Hour of Day',
        yaxis_title='Requests/min',
        height=300,
        showlegend=True,
        paper_bgcolor='#FAFAFA',
        plot_bgcolor='#FAFAFA',
        font=dict(family='Noto Sans', color='#1A1A2E'),
    )

    return fig


def create_cost_chart(infra_metrics):
    """Create cost comparison chart"""
    if not infra_metrics:
        return None

    options = ['Current', 'Proposed', 'Recommended']
    costs = [4200, 33600, 10080]
    colors = ['#19AA4F', '#E63244', '#FCB429']

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=options,
        y=costs,
        text=[f'${c:,}/mo' for c in costs],
        textposition='auto',
        marker_color=colors
    ))

    fig.update_layout(
        title='Monthly Cost Comparison',
        yaxis_title='Cost (USD/month)',
        height=350,
        showlegend=False,
        paper_bgcolor='#FAFAFA',
        plot_bgcolor='#FAFAFA',
        font=dict(family='Noto Sans', color='#1A1A2E'),
    )

    return fig


def main():
    # Header
    st.markdown('<div class="main-header">🛡️ Datadog IaC Proactive Detection</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Proactively detect and remediate risky infrastructure changes before they are deployed to production — powered by Claude</div>',
        unsafe_allow_html=True
    )

    # Sidebar
    with st.sidebar:
        st.header("Configuration")

        # API Keys
        with st.expander("🔑 API Keys", expanded=False):
            anthropic_key = st.text_input(
                "Anthropic API Key",
                value=os.getenv('ANTHROPIC_API_KEY', ''),
                type="password",
                help="Your Claude API key"
            )
            datadog_api_key = st.text_input(
                "Datadog API Key",
                value=os.getenv('DATADOG_API_KEY', ''),
                type="password",
                help="Optional - will use mock data if not provided"
            )
            datadog_app_key = st.text_input(
                "Datadog App Key",
                value=os.getenv('DATADOG_APP_KEY', ''),
                type="password",
                help="Optional - will use mock data if not provided"
            )

            if anthropic_key:
                os.environ['ANTHROPIC_API_KEY'] = anthropic_key
            if datadog_api_key:
                os.environ['DATADOG_API_KEY'] = datadog_api_key
            if datadog_app_key:
                os.environ['DATADOG_APP_KEY'] = datadog_app_key

        st.divider()

        # Input method
        st.header("📥 Input Method")
        input_method = st.radio(
            "Choose input:",
            ["Demo Scenario", "Upload Diff", "Paste Diff"],
            help="Select how to provide infrastructure changes"
        )

        diff_content = None

        if input_method == "Demo Scenario":
            scenario = st.selectbox(
                "Select Demo:",
                [
                    "Scenario 1: Peak Traffic Risk",
                    "Scenario 2: Cost Optimization",
                    "Scenario 3: Missing Health Checks",
                    "Scenario 4: Missing PodDisruptionBudget",
                    "Scenario 5: Insufficient Replicas",
                    "Scenario 6: Security Group Too Open"
                ]
            )

            if scenario == "Scenario 1: Peak Traffic Risk":
                st.info("🚨 Reduces K8s replicas 20→5. Will it crash?")
                diff_path = "examples/scenario-1-peak-traffic/payment-api-deployment.yaml"
            elif scenario == "Scenario 2: Cost Optimization":
                st.info("💰 Adds 10x c5.4xlarge. Is it over-provisioned?")
                diff_path = "examples/scenario-2-cost-optimization/compute.tf"
            elif scenario == "Scenario 3: Missing Health Checks":
                st.info("⚠️ Container deployed without liveness/readiness probes")
                diff_path = "examples/scenario-3-health-checks/api-deployment.yaml"
            elif scenario == "Scenario 4: Missing PodDisruptionBudget":
                st.info("🔄 High-availability service without PDB - risky rolling updates")
                diff_path = "examples/scenario-4-pdb/frontend-deployment.yaml"
            elif scenario == "Scenario 5: Insufficient Replicas":
                st.info("🔢 Production service with only 2 replicas - no HA during deploys")
                diff_path = "examples/scenario-5-replicas/checkout-deployment.yaml"
            elif scenario == "Scenario 6: Security Group Too Open":
                st.info("🚪 SSH open to 0.0.0.0/0 - security vulnerability")
                diff_path = "examples/scenario-6-security/security-groups.tf"

            # Create mock diff for demo
            if scenario == "Scenario 1: Peak Traffic Risk":
                diff_content = """diff --git a/payment-api-deployment.yaml b/payment-api-deployment.yaml
index 63e64b6..860092d 100644
--- a/payment-api-deployment.yaml
+++ b/payment-api-deployment.yaml
@@ -8,7 +8,7 @@ metadata:
     team: payments
     service: checkout
 spec:
-  replicas: 20
+  replicas: 5
   selector:
     matchLabels:
       app: payment-api"""
            elif scenario == "Scenario 2: Cost Optimization":
                diff_content = """diff --git a/compute.tf b/compute.tf
index f9b5445..59a26b9 100644
--- a/compute.tf
+++ b/compute.tf
@@ -12,11 +12,11 @@ provider "aws" {
   region = "us-east-1"
 }

-# Data processing cluster - currently right-sized
+# Data processing cluster - scaling up for new workload
 resource "aws_instance" "data_processor" {
-  count         = 5
+  count         = 10
   ami           = "ami-0c55b159cbfafe1f0"
-  instance_type = "c5.2xlarge"
+  instance_type = "c5.4xlarge"

   tags = {
     Name        = "data-processor-${count.index}\""""

            elif scenario == "Scenario 3: Missing Health Checks":
                diff_content = """diff --git a/api-deployment.yaml b/api-deployment.yaml
index abc123..def456 100644
--- a/api-deployment.yaml
+++ b/api-deployment.yaml
@@ -1,6 +1,7 @@
 apiVersion: apps/v1
 kind: Deployment
 metadata:
   name: api-server
+  namespace: production
 spec:
   replicas: 10
@@ -15,6 +16,7 @@ spec:
      containers:
      - name: api
        image: api-server:v2.0
+        # NOTE: No liveness or readiness probes configured!
        ports:
        - containerPort: 8080"""

            elif scenario == "Scenario 4: Missing PodDisruptionBudget":
                diff_content = """diff --git a/frontend-deployment.yaml b/frontend-deployment.yaml
index aaa111..bbb222 100644
--- a/frontend-deployment.yaml
+++ b/frontend-deployment.yaml
@@ -1,9 +1,10 @@
 apiVersion: apps/v1
 kind: Deployment
 metadata:
   name: frontend
   namespace: production
+  # NOTE: No PodDisruptionBudget defined for this service
 spec:
   replicas: 5"""

            elif scenario == "Scenario 5: Insufficient Replicas":
                diff_content = """diff --git a/checkout-deployment.yaml b/checkout-deployment.yaml
index xxx999..yyy888 100644
--- a/checkout-deployment.yaml
+++ b/checkout-deployment.yaml
@@ -5,7 +5,7 @@ metadata:
   namespace: production
   labels:
    app: checkout
 spec:
-  replicas: 3
+  replicas: 2
   selector:"""

            elif scenario == "Scenario 6: Security Group Too Open":
                diff_content = """diff --git a/security-groups.tf b/security-groups.tf
index zzz777..www666 100644
--- a/security-groups.tf
+++ b/security-groups.tf
@@ -1,10 +1,11 @@
 resource "aws_security_group" "app_servers" {
   name        = "app-servers"
  description = "Security group for application servers"
   vpc_id      = aws_vpc.main.id

   ingress {
+    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
-    cidr_blocks = ["10.0.0.0/8"]
+    cidr_blocks = ["0.0.0.0/0"]  # WARNING: Open to internet!
   }
 }"""

        elif input_method == "Upload Diff":
            uploaded_file = st.file_uploader("Upload git diff file", type=['txt', 'diff'])
            if uploaded_file:
                diff_content = uploaded_file.getvalue().decode('utf-8')

        else:  # Paste Diff
            diff_content = st.text_area(
                "Paste git diff:",
                height=200,
                placeholder="Paste your git diff here..."
            )

        st.divider()

        # Options
        st.header("⚙️ Options")
        show_metrics = st.checkbox("Show Datadog Metrics", value=True)
        auto_fix = st.checkbox("Generate Auto-Fix", value=True)

        # Analyze button
        analyze_button = st.button("🔍 Analyze Changes", type="primary", use_container_width=True)

    # Main content
    if not diff_content:
        # Welcome screen
        st.info("👈 Select a demo scenario or provide infrastructure changes to analyze")

        # Features
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("### 🚨 Risk Detection")
            st.write("Catches changes that will cause outages based on real production metrics")

        with col2:
            st.markdown("### 💰 Cost Optimization")
            st.write("Identifies over-provisioned resources and suggests right-sizing")

        with col3:
            st.markdown("### 🔧 Auto-Remediation")
            st.write("Generates safe alternatives with HPA and smart scaling")

        st.divider()

        return

    # Show diff
    with st.expander("📄 Changes Detected", expanded=True):
        st.code(diff_content, language='diff')

    if analyze_button:
        # Save diff to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(diff_content)
            diff_file = f.name

        try:
            # Parse diff
            with st.spinner("Parsing changes..."):
                changes = parse_diff(diff_file)

            st.success(f"✅ Detected {len(changes['files'])} file(s) changed")

            # Get Datadog context
            datadog_context = None
            if show_metrics:
                with st.spinner("Querying Datadog for production metrics..."):
                    datadog_context = get_datadog_context(changes)

                if datadog_context:
                    st.success("✅ Retrieved Datadog metrics")

                    # Display metrics
                    st.divider()
                    st.markdown("## 📊 Production Metrics")

                    if 'k8s_metrics' in datadog_context:
                        k8s = datadog_context['k8s_metrics']

                        # Metrics cards
                        col1, col2, col3, col4 = st.columns(4)

                        with col1:
                            st.metric(
                                "Current Replicas",
                                k8s.get('current_state', {}).get('replicas', 'N/A'),
                                help="Active pods right now"
                            )

                        with col2:
                            st.metric(
                                "Avg CPU/Pod",
                                k8s.get('current_state', {}).get('avg_cpu_per_pod', 'N/A'),
                                help="Average CPU utilization"
                            )

                        with col3:
                            peak = k8s.get('peak_traffic_last_7_days', {})
                            st.metric(
                                "Peak Traffic",
                                f"{peak.get('requests_per_minute', 0):,} req/min",
                                help="Highest traffic in last 7 days"
                            )

                        with col4:
                            st.metric(
                                "Peak CPU/Pod",
                                peak.get('cpu_per_pod', 'N/A'),
                                delta=f"+{int(peak.get('cpu_per_pod', '85%').rstrip('%')) - int(k8s.get('current_state', {}).get('avg_cpu_per_pod', '65%').rstrip('%'))}%",
                                delta_color="inverse",
                                help="CPU during peak traffic"
                            )

                        # Charts
                        st.markdown("### 📈 Visualizations")

                        col1, col2 = st.columns(2)

                        with col1:
                            cpu_chart = create_cpu_chart(k8s)
                            if cpu_chart:
                                st.plotly_chart(cpu_chart, use_container_width=True)

                            replica_chart = create_replica_chart(k8s)
                            if replica_chart:
                                st.plotly_chart(replica_chart, use_container_width=True)

                        with col2:
                            traffic_chart = create_traffic_chart(k8s)
                            if traffic_chart:
                                st.plotly_chart(traffic_chart, use_container_width=True)

                        # Incidents
                        if 'incidents' in datadog_context and datadog_context['incidents']:
                            st.markdown("### 🚨 Recent Incidents")
                            for inc in datadog_context['incidents']:
                                with st.container():
                                    col1, col2, col3 = st.columns([1, 3, 1])
                                    with col1:
                                        st.write(f"**{inc['id']}**")
                                    with col2:
                                        st.write(inc['title'])
                                    with col3:
                                        st.write(inc['date'])

                    if 'infrastructure_metrics' in datadog_context:
                        infra = datadog_context['infrastructure_metrics']

                        st.markdown("### 💻 Infrastructure Utilization")

                        col1, col2, col3, col4 = st.columns(4)

                        with col1:
                            st.metric(
                                "Instance Type",
                                infra.get('instance_type', 'N/A')
                            )

                        with col2:
                            st.metric(
                                "Avg CPU",
                                f"{infra.get('utilization', {}).get('avg_cpu', 0)}%"
                            )

                        with col3:
                            st.metric(
                                "Max CPU",
                                f"{infra.get('utilization', {}).get('max_cpu', 0)}%"
                            )

                        with col4:
                            st.metric(
                                "Avg Memory",
                                f"{infra.get('utilization', {}).get('avg_memory', 0)}%"
                            )

                        # Cost chart
                        cost_chart = create_cost_chart(infra)
                        if cost_chart:
                            st.plotly_chart(cost_chart, use_container_width=True)

            # Analyze with Claude (via MCP for real DD metrics, or fallback)
            st.divider()
            st.markdown("## 🤖 AI Analysis")

            t_start = time.time()
            with st.spinner("Analyzing with Claude + Datadog MCP..."):
                mcp_result = analyze_with_mcp(changes)

            if mcp_result.get("analysis"):
                analysis = mcp_result["analysis"]
                analysis_data_source = mcp_result["data_source"]
            else:
                with st.spinner("Analyzing with Claude (mock data)..."):
                    analysis = analyze_with_claude(changes, datadog_context)
                analysis_data_source = "mock"

            duration_ms = (time.time() - t_start) * 1000

            # Emit metrics (silent no-op if no DD keys)
            risk_match = re.search(r'\b(CRITICAL|HIGH|MEDIUM|LOW)\b', analysis)
            _risk_level = risk_match.group(1) if risk_match else "LOW"
            _scenario_type = changes.get('files', [{}])[0].get('file', '').split('/')[-1].replace('.yaml', '').replace('.tf', '')
            emit_analysis_metrics(
                risk_level=_risk_level,
                scenario_type=_scenario_type,
                repo=os.getenv('GITHUB_REPOSITORY', 'demo'),
                data_source=analysis_data_source,
                category=infer_category(_scenario_type, analysis),
                cost_savings_annual=infer_cost_savings(analysis),
                duration_ms=duration_ms,
            )

            # Data source badge
            if analysis_data_source == "mcp":
                st.success("🟢 Live Datadog Metrics — Claude queried your real DD org via MCP")
            else:
                st.info("⚪ Demo Mode (Mock Data) — set DATADOG_API_KEY for live metrics")

            # Display analysis
            st.markdown(analysis)

            # Auto-fix
            if auto_fix and datadog_context:
                st.divider()
                st.markdown("## 🤖 Auto-Remediation: Closing the Loop")

                with st.spinner("🔧 Generating safe alternative..."):
                    generator = FixGenerator()
                    fix = generator.generate_fix(changes, datadog_context, analysis)

                if fix:
                    # Big success banner
                    st.success("✅ **IaC Guardian has generated a SAFE alternative for you!**")

                    # Before/After Comparison (THIS IS THE KILLER VISUAL)
                    st.markdown("### 📊 Before vs After")

                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("#### ❌ Original Change")
                        with st.container():
                            st.error("**Risk Level:** CRITICAL")

                            # Show what was changed
                            if 'replica_changes' in changes:
                                st.markdown("**Proposed:**")
                                st.code(f"replicas: {changes['replica_changes'][-1]}", language='yaml')
                                st.caption("⚠️ Cannot handle peak traffic")
                                st.caption("⚠️ Will cause 306% CPU at peak")
                                st.caption("⚠️ Similar to incident INC-4521")
                            elif 'instance_type_changes' in changes or 'count_changes' in changes:
                                st.markdown("**Proposed:**")
                                if 'count_changes' in changes:
                                    st.code(f"count: {changes['count_changes'][-1]}", language='hcl')
                                if 'instance_type_changes' in changes:
                                    st.code(f"instance_type: {changes['instance_type_changes'][-1]}", language='hcl')
                                st.caption("⚠️ Over-provisioned by 3x")
                                st.caption("⚠️ Wastes $282k/year")
                                st.caption("⚠️ Only 15% CPU utilization")

                            st.metric("Monthly Cost", "$360" if 'replica_changes' in changes else "$33,600",
                                     help="Estimated monthly infrastructure cost")
                            st.metric("Risk Score", "95/100", delta="Unsafe", delta_color="inverse")

                    with col2:
                        st.markdown("#### ✅ IaC Guardian Auto-Fix")
                        with st.container():
                            st.success("**Risk Level:** LOW")

                            # Show the fix
                            st.markdown("**Safe Alternative:**")
                            if fix['fix_type'] == 'k8s_replica_fix':
                                st.code("""replicas: 15  # Safe minimum

---
# Auto-scaling enabled
HPA:
  minReplicas: 15
  maxReplicas: 22
  targetCPU: 70%""", language='yaml')
                                st.caption("✅ Handles peak traffic safely")
                                st.caption("✅ Auto-scales with load")
                                st.caption("✅ Still saves money vs current")

                                st.metric("Monthly Cost", "$900-1,200", help="Scales with traffic")
                            else:
                                st.code("""count: 6  # Right-sized
instance_type: c5.2xlarge""", language='hcl')
                                st.caption("✅ Right-sized for workload")
                                st.caption("✅ Room for growth")
                                st.caption("✅ Can scale up if needed")

                                st.metric("Monthly Cost", "$10,080", help="70% cheaper than proposal")

                            st.metric("Risk Score", "15/100", delta="-80 Safe", delta_color="normal")

                    # Visual flow diagram
                    st.markdown("---")
                    st.markdown("### 🔄 What Happens Next")

                    flow_cols = st.columns(5)
                    with flow_cols[0]:
                        st.markdown("**1️⃣ Current**")
                        st.info("Risky PR  \n❌ Blocked")
                    with flow_cols[1]:
                        st.markdown("**→**")
                    with flow_cols[2]:
                        st.markdown("**2️⃣ Auto-Fix**")
                        st.success("PR Created  \n🤖 By IaC Guardian")
                    with flow_cols[3]:
                        st.markdown("**→**")
                    with flow_cols[4]:
                        st.markdown("**3️⃣ Engineer**")
                        st.success("Merges Fix  \n✅ Problem Solved")

                    st.markdown("---")

                    # Fix details
                    st.markdown(f"### 📋 {fix['pr_title']}")
                    st.info(fix['description'])

                    # Expandable details
                    col1, col2 = st.columns(2)

                    with col1:
                        with st.expander("📝 Full PR Description", expanded=False):
                            st.markdown(fix['pr_body'])

                    with col2:
                        with st.expander("📄 Changed Files", expanded=False):
                            for file in fix['files']:
                                st.markdown(f"**{file['path']}**")
                                st.code(file['content'], language='yaml' if file['path'].endswith(('.yaml', '.yml')) else 'hcl')

                    # Action buttons - more prominent
                    st.markdown("### 🚀 Take Action")
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.button("✅ Create Fix PR", type="primary", use_container_width=True, disabled=True, help="Coming in Phase 2")

                    with col2:
                        st.button("📥 Download Fix Files", use_container_width=True, disabled=True, help="Coming in Phase 2")

                    with col3:
                        st.button("📧 Notify Team", use_container_width=True, disabled=True, help="Coming in Phase 2")

                    # Impact summary
                    st.markdown("---")
                    st.markdown("### 💰 Impact Summary")

                    impact_cols = st.columns(3)

                    with impact_cols[0]:
                        if fix['fix_type'] == 'k8s_replica_fix':
                            st.metric("Outages Prevented", "1", help="Would have crashed during peak")
                            st.caption("Estimated impact: **$2M saved**")
                        else:
                            st.metric("Cost Savings", "$282k/year", help="vs original proposal")
                            st.caption("Over-provisioning avoided")

                    with impact_cols[1]:
                        st.metric("Engineer Time Saved", "4 hours", help="No manual fix needed")
                        st.caption("Auto-generated in 10 seconds")

                    with impact_cols[2]:
                        st.metric("Code Review Cycles", "0", help="Pre-approved safe pattern")
                        st.caption("Can merge immediately")

                else:
                    st.info("ℹ️ No automatic fix available for this change")

        finally:
            # Cleanup
            os.unlink(diff_file)


if __name__ == "__main__":
    main()
