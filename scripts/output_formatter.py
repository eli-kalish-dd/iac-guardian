#!/usr/bin/env python3
"""
Output Formatter
Formats analysis output with professional styling for GitHub PR comments
"""

from typing import Dict, Optional


class OutputFormatter:
    """Formats analysis output for GitHub PR comments"""

    @staticmethod
    def format_analysis(analysis: str, fix_pr_url: Optional[str] = None, metadata: Dict = None) -> str:
        """
        Format analysis with professional GitHub styling

        Args:
            analysis: Raw analysis text from Claude
            fix_pr_url: URL to auto-generated fix PR (if available)
            metadata: Additional data (risk score, etc.)
        """
        # Extract risk level from analysis
        risk_level = OutputFormatter._extract_risk_level(analysis)
        risk_score = metadata.get('risk_score', '8.5') if metadata else '8.5'

        # Build formatted output
        output = []

        # Header with badges
        output.append(OutputFormatter._format_header(risk_level, risk_score))

        # Fix PR callout (if available) - put at top for visibility
        if fix_pr_url:
            output.append(OutputFormatter._format_fix_pr_callout(fix_pr_url))

        # Main analysis
        output.append(OutputFormatter._format_main_analysis(analysis))

        # Footer
        output.append(OutputFormatter._format_footer())

        return "\n\n".join(output)

    @staticmethod
    def _extract_risk_level(analysis: str) -> str:
        """Extract risk level from analysis text"""
        analysis_upper = analysis.upper()
        if 'CRITICAL' in analysis_upper or 'DO NOT MERGE' in analysis_upper:
            return 'CRITICAL'
        elif 'HIGH RISK' in analysis_upper or 'SEVERE' in analysis_upper:
            return 'HIGH'
        elif 'MEDIUM' in analysis_upper or 'MODERATE' in analysis_upper:
            return 'MEDIUM'
        elif 'LOW' in analysis_upper:
            return 'LOW'
        return 'MEDIUM'

    @staticmethod
    def _format_header(risk_level: str, risk_score: str) -> str:
        """Format header with badges"""
        # Risk level colors
        colors = {
            'CRITICAL': 'critical',
            'HIGH': 'red',
            'MEDIUM': 'orange',
            'LOW': 'green'
        }
        color = colors.get(risk_level, 'orange')

        # Risk emoji
        emojis = {
            'CRITICAL': '🚨',
            'HIGH': '⚠️',
            'MEDIUM': '⚡',
            'LOW': '✅'
        }
        emoji = emojis.get(risk_level, '⚡')

        header = f"""# {emoji} IaC Guardian Analysis

![Risk](https://img.shields.io/badge/Risk-{risk_level}-{color}?style=for-the-badge) ![Score](https://img.shields.io/badge/Score-{risk_score}%2F10-{color}) ![Powered by](https://img.shields.io/badge/Datadog%20%2B%20Claude-blueviolet)
"""
        return header

    @staticmethod
    def _format_fix_pr_callout(fix_pr_url: str) -> str:
        """Format fix PR callout box"""
        callout = f"""> [!TIP]
> **🔧 Auto-Fix Available:** {fix_pr_url}
>
> Close this PR and merge the fix instead.
"""
        return callout

    @staticmethod
    def _format_main_analysis(analysis: str) -> str:
        """Format main analysis with collapsible sections"""
        # The analysis from Claude is already pretty good, but we can enhance it
        # by wrapping certain sections in collapsible details

        # Check if analysis has specific sections we want to make collapsible
        formatted = analysis

        # Wrap long recommendations in collapsible sections
        if '## Recommendations' in formatted or '## ✅ Recommendations' in formatted:
            # Find and wrap the recommendations section
            formatted = OutputFormatter._make_section_collapsible(
                formatted,
                'Recommendations',
                '💡 View Detailed Recommendations'
            )

        # Make cost impact analysis collapsible
        if '## Cost Impact' in formatted or '## 💰 Cost Impact' in formatted:
            formatted = OutputFormatter._make_section_collapsible(
                formatted,
                'Cost Impact',
                '💰 View Cost Analysis'
            )

        return formatted

    @staticmethod
    def _make_section_collapsible(text: str, section_name: str, summary: str) -> str:
        """Wrap a section in a collapsible details block"""
        return f"""<details>
<summary><b>{summary}</b></summary>

{text}
</details>"""

    @staticmethod
    def _format_footer() -> str:
        """Format footer with attribution"""
        footer = """
---
<sub>🤖 Powered by [IaC Guardian](https://github.com/DataDog/iac-guardian) • Datadog + Claude AI</sub>
"""
        return footer

    @staticmethod
    def format_for_github_concise(analysis: str, fix_pr_url: Optional[str] = None, metadata: Dict = None) -> str:
        """
        Ultra-concise format for GitHub PR comments

        Format:
        - Risk badge
        - 1-2 sentence reason
        - Bullet point remediation
        - Optional fix link
        """
        risk_level = OutputFormatter._extract_risk_level(analysis)

        # Risk emoji
        emojis = {
            'CRITICAL': '🚨',
            'HIGH': '⚠️',
            'MEDIUM': '⚡',
            'LOW': '✅'
        }
        emoji = emojis.get(risk_level, '⚡')

        # Extract key reason (look for "Why This is Risky" section)
        reason = OutputFormatter._extract_concise_reason(analysis, risk_level)

        # Extract remediation (look for "What To Do" section)
        remediation = OutputFormatter._extract_concise_remediation(analysis)

        # Build concise comment
        output = []
        output.append(f"## {emoji} IaC Guardian: **{risk_level} RISK**")
        output.append("")
        output.append(f"**Why:** {reason}")
        output.append("")
        output.append("**Action:**")
        output.append(remediation)

        if fix_pr_url and 'simulated' not in fix_pr_url.lower():
            output.append("")
            output.append(f"🔧 **[View Auto-Fix PR]({fix_pr_url})**")

        output.append("")
        output.append("<sub>🤖 Powered by Datadog + Claude AI</sub>")

        return "\n".join(output)

    @staticmethod
    def _extract_concise_reason(analysis: str, risk_level: str) -> str:
        """Extract 1-2 sentence reason from analysis"""
        # Look for "Why This is Risky" section
        lines = analysis.split('\n')
        reason_lines = []
        in_reason = False

        for line in lines:
            if 'why this is risky' in line.lower():
                in_reason = True
                continue
            if in_reason:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith('##'):  # Next section
                    break
                # Collect non-empty, non-header lines
                if stripped and not stripped.startswith('**') and not stripped.startswith('#'):
                    reason_lines.append(stripped)
                    # Stop after collecting some text
                    if len(' '.join(reason_lines)) > 150:
                        break

        reason = ' '.join(reason_lines) if reason_lines else "Infrastructure change detected with potential risk."

        # Truncate if too long
        if len(reason) > 400:
            # Try to end at a sentence
            truncated = reason[:397]
            last_period = truncated.rfind('.')
            if last_period > 150:
                reason = truncated[:last_period+1]
            else:
                reason = truncated + "..."

        return reason

    @staticmethod
    def _extract_concise_remediation(analysis: str) -> str:
        """Extract bullet point remediation from analysis"""
        lines = analysis.split('\n')
        remediation = []
        in_remediation = False

        for line in lines:
            if 'what to do' in line.lower():
                in_remediation = True
                continue
            if in_remediation:
                stripped = line.strip()
                if stripped.startswith('##'):  # Next section
                    break
                if stripped.startswith('-') or stripped.startswith('*'):
                    # Clean up bullet points
                    cleaned = stripped.lstrip('-*').strip()
                    if cleaned and not cleaned.startswith('**'):
                        # Further clean up bold markers
                        cleaned = cleaned.replace('**', '')
                        remediation.append(f"- {cleaned}")
                elif stripped and not stripped.startswith('#'):
                    # Also capture non-bullet text
                    cleaned = stripped.replace('**', '')
                    if cleaned and len(remediation) == 0:  # First line can be non-bullet
                        remediation.append(f"- {cleaned}")

                if len(remediation) >= 2:  # Max 2 bullets for conciseness
                    break

        return '\n'.join(remediation) if remediation else "- Review and address the identified risks before merging"

    @staticmethod
    def format_for_terminal(analysis: str, fix_pr_url: Optional[str] = None) -> str:
        """
        Format for terminal output (no HTML/badges)

        Args:
            analysis: Raw analysis
            fix_pr_url: Fix PR URL if available
        """
        output = []

        # Terminal-friendly header
        risk_level = OutputFormatter._extract_risk_level(analysis)
        emojis = {
            'CRITICAL': '🚨',
            'HIGH': '⚠️',
            'MEDIUM': '⚡',
            'LOW': 'ℹ️'
        }
        emoji = emojis.get(risk_level, '⚡')

        output.append(f"\n{'='*80}")
        output.append(f"{emoji}  IaC GUARDIAN ANALYSIS - {risk_level} RISK")
        output.append(f"{'='*80}\n")

        # Fix PR section
        if fix_pr_url:
            output.append(f"🔧 AUTO-FIX AVAILABLE: {fix_pr_url}\n")
            output.append(f"{'─'*80}\n")

        # Main analysis
        output.append(analysis)

        # Footer
        output.append(f"\n{'─'*80}")
        output.append("🤖 Powered by Datadog + Claude AI")
        output.append(f"{'='*80}\n")

        return "\n".join(output)
