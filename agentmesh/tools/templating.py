"""Minimal templating so a tool's string params can reference upstream results.

`{{task_key}}` substitutes that task's whole result `data` dict (JSON-encoded);
`{{task_key.field}}` pulls just that field, inlined as-is if it's already a
string. Unknown references are left untouched rather than raised, so a typo'd
placeholder shows up in the output instead of failing the task outright.
"""

from __future__ import annotations

import json
import re

from agentmesh.tools.base import ToolResult

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*(\w+)(?:\.(\w+))?\s*\}\}")


def render_template(text: str, dependencies: dict[str, ToolResult]) -> str:
    def _replace(match: re.Match) -> str:
        task_key, field = match.group(1), match.group(2)
        dep = dependencies.get(task_key)
        if dep is None or dep.data is None:
            return match.group(0)
        value = dep.data.get(field) if field else dep.data
        return value if isinstance(value, str) else json.dumps(value, default=str)

    return _TEMPLATE_PATTERN.sub(_replace, text)
