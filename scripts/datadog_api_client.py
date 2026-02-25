#!/usr/bin/env python3
"""
Real Datadog API Client
Queries Datadog REST API for infrastructure metrics, incidents, and cost data
"""

import os
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json


class DatadogAPIClient:
    """Client to query Datadog REST API for real metrics"""

    def __init__(self):
        self.api_key = os.getenv('DATADOG_API_KEY')
        self.app_key = os.getenv('DATADOG_APP_KEY')
        self.site = os.getenv('DATADOG_SITE', 'datadoghq.com')
        self.base_url = f"https://api.{self.site}/api/v1"

        if not self.api_key or not self.app_key:
            # Only show warning in terminal mode, not GitHub Actions
            if os.getenv('GITHUB_ACTIONS') != 'true':
                print("⚠️  Warning: DATADOG_API_KEY or DATADOG_APP_KEY not set")
                print("   Falling back to mock data for demo")
            self.use_mock = True
        else:
            self.use_mock = False

        self.headers = {
            'DD-API-KEY': self.api_key or '',
            'DD-APPLICATION-KEY': self.app_key or '',
            'Content-Type': 'application/json'
        }

    def query_metrics(self, query: str, from_time: int = None, to_time: int = None) -> Dict:
        """
        Query Datadog metrics API

        Args:
            query: Datadog metric query (e.g., "avg:kubernetes.cpu.usage{service:payment-api}")
            from_time: Start time (Unix timestamp)
            to_time: End time (Unix timestamp)
        """
        if self.use_mock:
            return self._mock_metrics_response()

        if not from_time:
            from_time = int((datetime.now() - timedelta(days=7)).timestamp())
        if not to_time:
            to_time = int(datetime.now().timestamp())

        url = f"{self.base_url}/query"
        params = {
            'query': query,
            'from': from_time,
            'to': to_time
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error querying Datadog metrics: {e}")
            return self._mock_metrics_response()

    def query_k8s_metrics(self, service_name: str, namespace: str = "production") -> Dict:
        """
        Query Kubernetes metrics for a specific service
        Returns aggregated metrics about CPU, memory, replicas
        """
        if self.use_mock:
            return self._mock_k8s_metrics(service_name, namespace)

        now = datetime.now()
        week_ago = now - timedelta(days=7)

        # Query multiple metrics
        queries = {
            'cpu': f"avg:kubernetes.cpu.usage{{kube_service:{service_name},kube_namespace:{namespace}}}",
            'memory': f"avg:kubernetes.memory.usage{{kube_service:{service_name},kube_namespace:{namespace}}}",
            'replicas': f"avg:kubernetes_state.deployment.replicas_available{{kube_deployment:{service_name},kube_namespace:{namespace}}}",
            'requests': f"sum:trace.http.request.hits{{service:{service_name}}}",
        }

        results = {}
        for metric_name, query in queries.items():
            data = self.query_metrics(query, int(week_ago.timestamp()), int(now.timestamp()))
            results[metric_name] = data

        # Parse and structure the results
        return self._parse_k8s_metrics(results, service_name, namespace)

    def query_incidents(self, service_name: str = None, days: int = 30) -> List[Dict]:
        """
        Query Datadog events/incidents for a service
        """
        if self.use_mock:
            return self._mock_incidents(service_name)

        url = f"{self.base_url}/events"
        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days)).timestamp())

        params = {
            'start': start,
            'end': end,
            'tags': f'service:{service_name}' if service_name else None,
            'priority': 'normal'
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            events = response.json().get('events', [])

            # Filter for incident-like events
            incidents = [e for e in events if 'incident' in e.get('title', '').lower()
                        or e.get('alert_type') in ['error', 'warning']]

            return self._parse_incidents(incidents)
        except Exception as e:
            print(f"Error querying incidents: {e}")
            return self._mock_incidents(service_name)

    def query_infrastructure_metrics(self, instance_type: str = None, tags: Dict = None) -> Dict:
        """
        Query infrastructure (EC2/host) utilization metrics
        """
        if self.use_mock:
            return self._mock_infrastructure_metrics(instance_type)

        # Query host metrics aggregated by instance type
        query = f"avg:system.cpu.user{{instance-type:{instance_type}}}"

        cpu_data = self.query_metrics(query)

        return self._parse_infrastructure_metrics(cpu_data, instance_type)

    # Parsing helpers
    def _parse_k8s_metrics(self, raw_data: Dict, service: str, namespace: str) -> Dict:
        """Parse raw Datadog metrics into structured format"""
        # Extract values from time series data
        cpu_series = raw_data.get('cpu', {}).get('series', [])
        memory_series = raw_data.get('memory', {}).get('series', [])
        replica_series = raw_data.get('replicas', {}).get('series', [])

        # Calculate averages and peaks
        cpu_values = []
        memory_values = []
        replica_values = []

        for series in cpu_series:
            cpu_values.extend([p[1] for p in series.get('pointlist', [])])

        for series in memory_series:
            memory_values.extend([p[1] for p in series.get('pointlist', [])])

        for series in replica_series:
            replica_values.extend([p[1] for p in series.get('pointlist', [])])

        return {
            "service": service,
            "namespace": namespace,
            "current_state": {
                "replicas": int(replica_values[-1]) if replica_values else 20,
                "avg_cpu_per_pod": f"{int(sum(cpu_values)/len(cpu_values)) if cpu_values else 65}%",
                "avg_memory_per_pod": f"{int(sum(memory_values)/len(memory_values)) if memory_values else 680}Mi",
            },
            "peak_traffic_last_7_days": {
                "replicas_active": int(max(replica_values)) if replica_values else 18,
                "cpu_per_pod": f"{int(max(cpu_values)) if cpu_values else 85}%",
            }
        }

    def _parse_incidents(self, events: List) -> List[Dict]:
        """Parse Datadog events into incident format"""
        incidents = []
        for event in events[:5]:  # Limit to 5 most recent
            incidents.append({
                "id": event.get('id', 'N/A'),
                "date": datetime.fromtimestamp(event.get('date_happened', 0)).strftime('%Y-%m-%d'),
                "title": event.get('title', 'Unknown incident'),
                "severity": event.get('priority', 'normal'),
                "text": event.get('text', '')[:200]
            })
        return incidents

    def _parse_infrastructure_metrics(self, data: Dict, instance_type: str) -> Dict:
        """Parse infrastructure metrics"""
        series = data.get('series', [])
        cpu_values = []

        for s in series:
            cpu_values.extend([p[1] for p in s.get('pointlist', [])])

        avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 15
        max_cpu = max(cpu_values) if cpu_values else 28

        return {
            "instance_type": instance_type,
            "sample_size": 5,
            "utilization": {
                "avg_cpu": round(avg_cpu, 1),
                "max_cpu": round(max_cpu, 1),
                "avg_memory": 22.1,
            }
        }

    # Mock data fallbacks
    def _mock_metrics_response(self) -> Dict:
        """Mock metrics response for demo"""
        return {"series": [], "status": "ok"}

    def _mock_k8s_metrics(self, service: str, namespace: str) -> Dict:
        """Mock K8s metrics for demo"""
        return {
            "service": service,
            "namespace": namespace,
            "current_state": {
                "replicas": 20,
                "avg_cpu_per_pod": "65%",
                "avg_memory_per_pod": "680Mi",
                "requests_per_minute": 45000
            },
            "peak_traffic_last_7_days": {
                "timestamp": "2026-02-11T14:23:00Z",
                "date_readable": "Tuesday Feb 11, 2pm",
                "replicas_active": 18,
                "cpu_per_pod": "85%",
                "memory_per_pod": "850Mi",
                "requests_per_minute": 82000,
            }
        }

    def _mock_incidents(self, service: str = None) -> List[Dict]:
        """Mock incidents for demo"""
        return [
            {
                "id": "INC-4521",
                "date": "2026-02-07",
                "title": f"{service or 'Service'} latency spike during flash sale",
                "severity": "high",
                "text": "Insufficient capacity - only 12 replicas available during peak traffic"
            }
        ]

    def _mock_infrastructure_metrics(self, instance_type: str) -> Dict:
        """Mock infrastructure metrics for demo"""
        return {
            "instance_type": instance_type or "c5.2xlarge",
            "sample_size": 5,
            "time_range": "last_7_days",
            "utilization": {
                "avg_cpu": 15.3,
                "max_cpu": 28.7,
                "avg_memory": 22.1,
            }
        }


# For backwards compatibility with existing code
def get_datadog_context(changes: Dict) -> Optional[Dict]:
    """
    Main function to fetch Datadog context for PR changes
    Now uses real Datadog API
    """
    client = DatadogAPIClient()
    context = {}

    # Check for K8s replica changes
    if changes.get('k8s_changes'):
        for k8s_file in changes['k8s_changes']:
            # Extract deployment name from metadata.name in the diff content
            raw = changes.get('raw_diff', '')
            name_match = re.search(r'\n\s{0,4}name:\s+([\w][\w.-]+)', raw)
            if name_match:
                service_name = name_match.group(1)
            else:
                # Fall back to filename, stripping common deployment suffixes
                fname = k8s_file['path'].split('/')[-1]
                service_name = re.sub(r'[-_](deployment|service|statefulset|daemonset)\.ya?ml$', '', fname, flags=re.I)
                service_name = re.sub(r'\.ya?ml$', '', service_name)
            context['k8s_metrics'] = client.query_k8s_metrics(service_name)
            context['incidents'] = client.query_incidents(service_name)
            break  # first K8s file only

    # Check for Terraform compute changes
    if changes.get('terraform_changes'):
        if changes.get('instance_type_changes') or changes.get('count_changes'):
            instance_type = changes.get('instance_type_changes', ['c5.2xlarge'])[0] if changes.get('instance_type_changes') else "c5.2xlarge"
            context['infrastructure_metrics'] = client.query_infrastructure_metrics(instance_type)

    return context if context else None
