"""Prompt templates for the WorkflowPlanner.

The system prompt is assembled dynamically from the live ToolRegistry so the
planner never drifts out of sync with the tools actually available at
runtime — adding a new tool automatically makes it plannable.
"""

from __future__ import annotations

from agentmesh.planner.examples import build_few_shot_block
from agentmesh.tools.registry import ToolRegistry

# Lightweight parameter hints for built-in tools. Tools without an entry here
# still appear in the catalog (name + description) — this just gives the
# model a head start on the exact param keys it should use.
_PARAM_HINTS: dict[str, str] = {
    "echo": 'params: any key-value pairs, returned unchanged.',
    "http": (
        'params: {"url": string, '
        '"method": "GET"|"POST"|"PUT"|"PATCH"|"DELETE" (default "GET"), '
        '"headers": object, "body": object, "timeout": integer seconds}'
    ),
    "filesystem": 'params: {"operation": "read"|"write", "path": string, '
                  '"content": string (write only), "encoding": string (default "utf-8")}',
    "shell": 'params: {"command": string, "timeout": integer seconds (default 30), "cwd": string}',
    "llm": 'params: {"prompt": string, "model": string, "system": string, '
           '"temperature": number 0.0-2.0 (default 0.7)}',
}

SYSTEM_PROMPT_TEMPLATE = """\
You are the AgentMesh workflow planner. Convert a user's natural language \
request into a workflow: a directed acyclic graph (DAG) of tasks, where each task calls one tool.

Tool catalog (the ONLY tools you may use):
{tool_catalog}

Output format — return ONLY a single JSON object, no markdown fences, no commentary:
{{
  "tasks": [
    {{
      "id": "<unique_snake_case_task_id>",
      "tool": "<tool_name_from_catalog>",
      "params": {{ ... tool-specific parameters ... }},
      "depends_on": ["<id_of_a_task_that_must_run_first>", ...]
    }}
  ]
}}

Rules:
1. Only use tool names that appear in the tool catalog above. Never invent a tool.
2. Every "depends_on" entry must exactly match the "id" of another task in this same output.
3. Task ids must be unique, short, descriptive, snake_case strings.
4. The graph must be acyclic — depends_on chains must never loop back on themselves.
5. Tasks with no natural ordering constraint should have an empty "depends_on" list so they \
can run in parallel — prefer parallelism over unnecessary sequencing.
6. To use another task's output as input, reference it as "{{{{task_id.field}}}}" inside a \
string param (e.g. "{{{{fetch_data.body}}}}"). Only reference tasks listed in "depends_on".
7. Keep the plan minimal — do not add tasks that aren't needed to fulfill the request.
8. Return valid, parseable JSON and nothing else.

{few_shot_examples}
"""


def build_tool_catalog(registry: ToolRegistry) -> str:
    """Render the registry's tools as a bullet list with param hints for the prompt."""
    lines = []
    for tool in registry.list_tools():
        line = f"- {tool.name}: {tool.description}"
        hint = _PARAM_HINTS.get(tool.name)
        if hint:
            line += f"\n  {hint}"
        lines.append(line)
    return "\n".join(lines)


def build_system_prompt(registry: ToolRegistry) -> str:
    """Build the full system prompt: role, tool catalog, output schema, and few-shot examples."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        tool_catalog=build_tool_catalog(registry),
        few_shot_examples=build_few_shot_block(),
    )


def build_user_prompt(request: str, feedback: str | None = None) -> str:
    """Build the user-turn prompt, optionally including feedback from a failed attempt."""
    if feedback:
        return (
            f"Request: {request}\n\n"
            f"Your previous attempt was invalid for this reason: {feedback}\n"
            "Return a corrected JSON workflow that fixes this issue. "
            "Remember: JSON only, no commentary."
        )
    return f"Request: {request}"
