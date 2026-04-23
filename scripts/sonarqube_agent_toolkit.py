#!/usr/bin/env python3
"""
SonarQube Agent Toolkit - Tools for agents to access and manage SonarQube issues.

Usage:
    python sonarqube_agent_toolkit.py get-issues [--severity CRITICAL] [--file path/to/file.py] [--format json|markdown]
    python sonarqube_agent_toolkit.py get-issue <issue-key>
    python sonarqube_agent_toolkit.py analyze-and-export [--format json|markdown|csv]
    python sonarqube_agent_toolkit.py rule-info <rule-id>
"""

import json
import sys
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
import requests

SONARQUBE_URL = "http://localhost:9000"
SONARQUBE_TOKEN = "squ_bf009385c27bf559fdb5fa9b2090a4447adced04"
PROJECT_KEY = "PlantIQ"

# Severity levels in priority order
SEVERITY_ORDER = {"BLOCKER": 0, "CRITICAL": 1, "MAJOR": 2, "MINOR": 3, "INFO": 4}


def fetch_issues(severity_filter: Optional[str] = None, file_path: Optional[str] = None) -> List[Dict]:
    """Fetch issues from SonarQube API."""
    url = f"{SONARQUBE_URL}/api/issues/search"
    params = {
        "componentKeys": PROJECT_KEY,
        "ps": 500,
    }
    
    if severity_filter:
        params["severities"] = severity_filter
    
    if file_path:
        # Convert file path to component format
        component = f"{PROJECT_KEY}:{file_path}"
        params["components"] = component
    
    try:
        response = requests.get(url, auth=(SONARQUBE_TOKEN, ""), params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("issues", [])
    except Exception as e:
        print(f"✗ Error fetching issues: {e}", file=sys.stderr)
        sys.exit(1)


def get_issue_detail(issue_key: str) -> Dict:
    """Get detailed information about a specific issue."""
    url = f"{SONARQUBE_URL}/api/issues/search"
    params = {"issues": issue_key}
    
    try:
        response = requests.get(url, auth=(SONARQUBE_TOKEN, ""), params=params)
        response.raise_for_status()
        data = response.json()
        issues = data.get("issues", [])
        return issues[0] if issues else {}
    except Exception as e:
        print(f"✗ Error fetching issue: {e}", file=sys.stderr)
        sys.exit(1)


def get_rule_info(rule_id: str) -> Dict:
    """Get information about a SonarQube rule."""
    url = f"{SONARQUBE_URL}/api/rules/show"
    params = {"key": rule_id}
    
    try:
        response = requests.get(url, auth=(SONARQUBE_TOKEN, ""), params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("rule", {})
    except Exception as e:
        print(f"✗ Error fetching rule info: {e}", file=sys.stderr)
        return {}


def run_analysis() -> bool:
    """Run SonarQube analysis on the project."""
    cmd = [
        "docker", "run", "--rm", "--network", "host",
        "-v", f"{Path.cwd()}:/usr/src",
        "sonarsource/sonar-scanner-cli",
        "-Dsonar.host.url=http://localhost:9000",
        f"-Dsonar.login={SONARQUBE_TOKEN}",
        "-Dsonar.projectKey=PlantIQ",
        "-Dsonar.sources=."
    ]
    
    print("Running SonarQube analysis...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"✗ Analysis failed: {result.stderr}", file=sys.stderr)
        return False
    
    print("✓ Analysis completed", file=sys.stderr)
    return True


def format_issue_text(issue: Dict) -> str:
    """Format an issue for human-readable output."""
    rule_key = issue.get("rule", "UNKNOWN")
    severity = issue.get("severity", "UNKNOWN")
    file_path = issue.get("component", "").split(":", 1)[-1]
    line = issue.get("line", "?")
    message = issue.get("message", "No description")
    key = issue.get("key", "")
    
    return (
        f"[{severity}] {rule_key}\n"
        f"Location: {file_path}:{line}\n"
        f"Message: {message}\n"
        f"Key: {key}"
    )


def format_issues_json(issues: List[Dict]) -> str:
    """Format issues as JSON."""
    return json.dumps(issues, indent=2)


def format_issues_markdown(issues: List[Dict]) -> str:
    """Format issues as Markdown."""
    lines = ["# SonarQube Issues\n"]
    
    # Group by severity
    by_severity = {}
    for issue in issues:
        severity = issue.get("severity", "UNKNOWN")
        if severity not in by_severity:
            by_severity[severity] = []
        by_severity[severity].append(issue)
    
    # Sort by severity priority
    for severity in sorted(by_severity.keys(), key=lambda s: SEVERITY_ORDER.get(s, 999)):
        count = len(by_severity[severity])
        lines.append(f"## {severity} ({count})\n")
        
        for issue in by_severity[severity]:
            rule_key = issue.get("rule", "UNKNOWN")
            file_path = issue.get("component", "").split(":", 1)[-1]
            line = issue.get("line", "?")
            message = issue.get("message", "")
            
            lines.append(f"### {rule_key}")
            lines.append(f"- **File:** `{file_path}:{line}`")
            lines.append(f"- **Message:** {message}\n")
    
    return "\n".join(lines)


def cmd_get_issues(args):
    """Get issues command."""
    issues = fetch_issues(args.severity, args.file)
    
    if args.format == "json":
        print(format_issues_json(issues))
    elif args.format == "markdown":
        print(format_issues_markdown(issues))
    else:
        for issue in issues:
            print(format_issue_text(issue))
            print()


def cmd_get_issue(args):
    """Get single issue command."""
    issue = get_issue_detail(args.issue_key)
    if issue:
        print(format_issue_text(issue))
        
        # Add rule info
        rule_id = issue.get("rule", "")
        if rule_id:
            print(f"\n**Rule Information:**\n")
            rule_info = get_rule_info(rule_id)
            if rule_info:
                print(f"Type: {rule_info.get('type', 'N/A')}")
                print(f"Severity: {rule_info.get('severity', 'N/A')}")
                print(f"HTML Description: {rule_info.get('htmlDesc', 'N/A')[:500]}...")
    else:
        print(f"✗ Issue {args.issue_key} not found", file=sys.stderr)
        sys.exit(1)


def cmd_analyze_and_export(args):
    """Analyze project and export issues."""
    if run_analysis():
        # After analysis, fetch issues
        issues = fetch_issues()
        
        if args.format == "json":
            print(format_issues_json(issues))
        elif args.format == "markdown":
            print(format_issues_markdown(issues))
        else:
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Rule", "Severity", "File", "Line", "Message"])
            
            for issue in issues:
                writer.writerow([
                    issue.get("rule", ""),
                    issue.get("severity", ""),
                    issue.get("component", "").split(":", 1)[-1],
                    issue.get("line", ""),
                    issue.get("message", "")
                ])
            
            print(output.getvalue())


def cmd_rule_info(args):
    """Get rule information."""
    rule_info = get_rule_info(args.rule_id)
    
    if rule_info:
        print(json.dumps(rule_info, indent=2))
    else:
        print(f"✗ Rule {args.rule_id} not found", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SonarQube Agent Toolkit - Tools for agents to manage issues"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Get issues command
    get_issues_parser = subparsers.add_parser("get-issues", help="Get issues from SonarQube")
    get_issues_parser.add_argument("--severity", help="Filter by severity (BLOCKER, CRITICAL, MAJOR, MINOR, INFO)")
    get_issues_parser.add_argument("--file", help="Filter by file path")
    get_issues_parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    get_issues_parser.set_defaults(func=cmd_get_issues)
    
    # Get issue command
    get_issue_parser = subparsers.add_parser("get-issue", help="Get details about a specific issue")
    get_issue_parser.add_argument("issue_key", help="Issue key (e.g., AZ26fdLngO_SFcTyFtxu)")
    get_issue_parser.set_defaults(func=cmd_get_issue)
    
    # Analyze and export command
    analyze_parser = subparsers.add_parser("analyze-and-export", help="Run analysis and export results")
    analyze_parser.add_argument("--format", choices=["json", "markdown", "csv"], default="json")
    analyze_parser.set_defaults(func=cmd_analyze_and_export)
    
    # Rule info command
    rule_parser = subparsers.add_parser("rule-info", help="Get information about a rule")
    rule_parser.add_argument("rule_id", help="Rule ID (e.g., python:S1192)")
    rule_parser.set_defaults(func=cmd_rule_info)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
    
    args.func(args)


if __name__ == "__main__":
    main()
