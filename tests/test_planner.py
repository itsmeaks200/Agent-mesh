"""Tests for WorkflowPlanner — prompt construction, parsing, and retry/feedback loop.

The model call itself is injected via `generate_fn` so these tests never touch
the network or require GEMINI_API_KEY / google-generativeai to be installed.
"""

from __future__ import annotations

import json

import pytest

from agentmesh.planner.planner import PlannerError, WorkflowPlanner
from agentmesh.planner.prompts import build_system_prompt, build_tool_catalog, build_user_prompt
from agentmesh.tools.registry import default_registry


def _valid_response(*, tasks: list[dict] | None = None) -> str:
    tasks = tasks or [
        {"id": "step_1", "tool": "echo", "params": {"message": "hi"}, "depends_on": []},
    ]
    return json.dumps({"tasks": tasks})


class _ScriptedGenerate:
    """A generate_fn stand-in that yields each response in sequence, then repeats the last.

    Records every ``(system_prompt, user_prompt)`` pair it was called with, so
    tests can assert on retry feedback.
    """

    def __init__(self, *responses: str) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


def _scripted_generate(*responses: str) -> _ScriptedGenerate:
    return _ScriptedGenerate(*responses)


# ── Prompt construction ───────────────────────────────────────────────────────


class TestPromptConstruction:
    def test_tool_catalog_lists_all_registered_tools(self):
        catalog = build_tool_catalog(default_registry)
        for name in default_registry.tool_names():
            assert name in catalog

    def test_system_prompt_includes_catalog_and_examples(self):
        prompt = build_system_prompt(default_registry)
        assert "echo" in prompt
        assert "tasks" in prompt
        assert "Examples:" in prompt

    def test_user_prompt_without_feedback(self):
        prompt = build_user_prompt("Do the thing")
        assert prompt == "Request: Do the thing"

    def test_user_prompt_with_feedback_includes_correction_instruction(self):
        prompt = build_user_prompt("Do the thing", feedback="bad json")
        assert "Do the thing" in prompt
        assert "bad json" in prompt
        assert "corrected" in prompt.lower()


# ── Happy path ────────────────────────────────────────────────────────────────


class TestPlannerHappyPath:
    async def test_plan_returns_task_specs_on_first_attempt(self):
        generate = _scripted_generate(_valid_response())
        planner = WorkflowPlanner(generate_fn=generate)

        task_specs = await planner.plan("Say hi")

        assert len(task_specs) == 1
        assert task_specs[0].id == "step_1"
        assert task_specs[0].tool == "echo"
        assert len(generate.calls) == 1

    async def test_plan_handles_linear_dag(self):
        tasks = [
            {"id": "fetch", "tool": "http", "params": {"url": "https://x.test"}, "depends_on": []},
            {"id": "summarize", "tool": "llm", "params": {"prompt": "sum"}, "depends_on": ["fetch"]},
        ]
        generate = _scripted_generate(_valid_response(tasks=tasks))
        planner = WorkflowPlanner(generate_fn=generate)

        task_specs = await planner.plan("Fetch then summarize")

        assert [t.id for t in task_specs] == ["fetch", "summarize"]
        assert task_specs[1].depends_on == ["fetch"]

    async def test_plan_strips_markdown_code_fences(self):
        fenced = "```json\n" + _valid_response() + "\n```"
        generate = _scripted_generate(fenced)
        planner = WorkflowPlanner(generate_fn=generate)

        task_specs = await planner.plan("Say hi")

        assert len(task_specs) == 1


# ── Retry / self-correction ───────────────────────────────────────────────────


class TestPlannerRetries:
    async def test_invalid_json_then_valid_on_retry(self):
        generate = _scripted_generate("not json at all", _valid_response())
        planner = WorkflowPlanner(generate_fn=generate, max_retries=2)

        task_specs = await planner.plan("Say hi")

        assert len(task_specs) == 1
        assert len(generate.calls) == 2
        # Second call's user prompt should carry feedback about the failure.
        _, second_user_prompt = generate.calls[1]
        assert "invalid" in second_user_prompt.lower()

    async def test_unknown_tool_then_valid_on_retry(self):
        bad_tasks = [{"id": "a", "tool": "not_a_real_tool", "params": {}, "depends_on": []}]
        generate = _scripted_generate(_valid_response(tasks=bad_tasks), _valid_response())
        planner = WorkflowPlanner(generate_fn=generate, max_retries=2)

        task_specs = await planner.plan("Do something")

        assert len(task_specs) == 1
        assert len(generate.calls) == 2

    async def test_missing_dependency_then_valid_on_retry(self):
        bad_tasks = [
            {"id": "a", "tool": "echo", "params": {"x": 1}, "depends_on": ["does_not_exist"]},
        ]
        generate = _scripted_generate(_valid_response(tasks=bad_tasks), _valid_response())
        planner = WorkflowPlanner(generate_fn=generate, max_retries=2)

        task_specs = await planner.plan("Do something")
        assert len(task_specs) == 1

    async def test_cycle_then_valid_on_retry(self):
        cyclic_tasks = [
            {"id": "a", "tool": "echo", "params": {"x": 1}, "depends_on": ["b"]},
            {"id": "b", "tool": "echo", "params": {"x": 1}, "depends_on": ["a"]},
        ]
        generate = _scripted_generate(_valid_response(tasks=cyclic_tasks), _valid_response())
        planner = WorkflowPlanner(generate_fn=generate, max_retries=2)

        task_specs = await planner.plan("Do something")
        assert len(task_specs) == 1

    async def test_exhausted_retries_raises_planner_error(self):
        generate = _scripted_generate("still not json")
        planner = WorkflowPlanner(generate_fn=generate, max_retries=2)

        with pytest.raises(PlannerError) as exc_info:
            await planner.plan("Do something")

        assert len(generate.calls) == 3  # initial + 2 retries
        assert "failed to produce a valid workflow" in str(exc_info.value).lower()

    async def test_empty_tasks_array_is_rejected(self):
        generate = _scripted_generate(json.dumps({"tasks": []}))
        planner = WorkflowPlanner(generate_fn=generate, max_retries=0)

        with pytest.raises(PlannerError):
            await planner.plan("Do nothing")

    async def test_missing_tasks_key_is_rejected(self):
        generate = _scripted_generate(json.dumps({"steps": []}))
        planner = WorkflowPlanner(generate_fn=generate, max_retries=0)

        with pytest.raises(PlannerError):
            await planner.plan("Do nothing")


# ── Model call failure handling ───────────────────────────────────────────────


class TestPlannerModelFailure:
    async def test_generate_fn_exception_becomes_planner_error(self):
        async def broken_generate(system_prompt: str, user_prompt: str) -> str:
            raise RuntimeError("network exploded")

        planner = WorkflowPlanner(generate_fn=broken_generate)

        with pytest.raises(PlannerError, match="network exploded"):
            await planner.plan("Do something")

    async def test_missing_api_key_raises_planner_error_without_override(self):
        """With no generate_fn and no GEMINI_API_KEY configured, planning should fail clearly."""
        planner = WorkflowPlanner()  # no generate_fn -> uses _default_generate

        with pytest.raises(PlannerError, match="GEMINI_API_KEY"):
            await planner.plan("Do something")
