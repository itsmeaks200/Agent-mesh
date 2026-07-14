"""Few-shot examples for the WorkflowPlanner prompt.

Each example pairs a natural-language request with the exact JSON the model
should produce. They cover the DAG shapes the planner needs to generalize to:
linear chains, independent parallel branches, and a diamond (fan-out/fan-in).
"""

from __future__ import annotations

import json

FEW_SHOT_EXAMPLES: list[dict] = [
    {
        "request": "Read a file called notes.txt, summarize it, and save the summary.",
        "response": {
            "tasks": [
                {
                    "id": "read_notes",
                    "tool": "filesystem",
                    "params": {"operation": "read", "path": "notes.txt"},
                    "depends_on": [],
                },
                {
                    "id": "summarize",
                    "tool": "llm",
                    "params": {"prompt": "Summarize the following text:\n\n{{read_notes.content}}"},
                    "depends_on": ["read_notes"],
                },
                {
                    "id": "save_summary",
                    "tool": "filesystem",
                    "params": {
                        "operation": "write",
                        "path": "summary.txt",
                        "content": "{{summarize.text}}",
                    },
                    "depends_on": ["summarize"],
                },
            ]
        },
    },
    {
        "request": (
            "Fetch https://api.example.com/users and https://api.example.com/orders "
            "in parallel, then combine the results into a report."
        ),
        "response": {
            "tasks": [
                {
                    "id": "fetch_users",
                    "tool": "http",
                    "params": {"url": "https://api.example.com/users", "method": "GET"},
                    "depends_on": [],
                },
                {
                    "id": "fetch_orders",
                    "tool": "http",
                    "params": {"url": "https://api.example.com/orders", "method": "GET"},
                    "depends_on": [],
                },
                {
                    "id": "combine_report",
                    "tool": "llm",
                    "params": {
                        "prompt": (
                            "Combine these two API responses into a short report.\n\n"
                            "Users: {{fetch_users.body}}\n\nOrders: {{fetch_orders.body}}"
                        )
                    },
                    "depends_on": ["fetch_users", "fetch_orders"],
                },
            ]
        },
    },
    {
        "request": (
            "Run two independent checks on a system — disk usage and memory usage — "
            "then produce one combined health report."
        ),
        "response": {
            "tasks": [
                {
                    "id": "check_disk",
                    "tool": "shell",
                    "params": {"command": "df -h"},
                    "depends_on": [],
                },
                {
                    "id": "check_memory",
                    "tool": "shell",
                    "params": {"command": "free -h"},
                    "depends_on": [],
                },
                {
                    "id": "health_report",
                    "tool": "llm",
                    "params": {
                        "prompt": (
                            "Write a one-paragraph health report from this data.\n\n"
                            "Disk: {{check_disk.stdout}}\n\nMemory: {{check_memory.stdout}}"
                        )
                    },
                    "depends_on": ["check_disk", "check_memory"],
                },
                {
                    "id": "save_report",
                    "tool": "filesystem",
                    "params": {
                        "operation": "write",
                        "path": "health_report.txt",
                        "content": "{{health_report.text}}",
                    },
                    "depends_on": ["health_report"],
                },
            ]
        },
    },
]


def build_few_shot_block() -> str:
    """Render all few-shot examples as a single prompt-ready text block."""
    parts = ["Examples:"]
    for i, example in enumerate(FEW_SHOT_EXAMPLES, start=1):
        parts.append(
            f"\nExample {i}\n"
            f"Request: {example['request']}\n"
            f"Response:\n{json.dumps(example['response'], indent=2)}"
        )
    return "\n".join(parts)
