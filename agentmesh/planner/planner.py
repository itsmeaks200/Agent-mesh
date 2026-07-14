"""WorkflowPlanner — turns a natural language request into a validated workflow.

Pipeline:
    1. Build a prompt from the live tool catalog + few-shot examples.
    2. Call Gemini with ``response_mime_type: "application/json"``.
    3. Parse the response into a list of ``TaskSpec``.
    4. Compile the specs with ``WorkflowCompiler`` to catch unknown tools,
       missing dependencies, cycles, and schema errors.
    5. On any failure, feed the error back to the model as corrective
       feedback and retry (up to ``max_retries`` times).

The actual model call is injectable via ``generate_fn`` so the retry/parse/
validate loop can be tested deterministically without a live API key or the
``google-generativeai`` package installed.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import structlog
from pydantic import ValidationError

from agentmesh.compiler.compiler import WorkflowCompiler
from agentmesh.compiler.errors import CompilationError, MultipleCompilationErrors
from agentmesh.config import get_settings
from agentmesh.planner.prompts import build_system_prompt, build_user_prompt
from agentmesh.schemas.workflow import TaskSpec
from agentmesh.tools.registry import ToolRegistry, default_registry

log = structlog.get_logger(__name__)

DEFAULT_MODEL = "gemini-2.0-flash"

# (system_prompt, user_prompt) -> raw model text
GenerateFn = Callable[[str, str], Awaitable[str]]


class PlannerError(Exception):
    """Raised when the planner cannot produce a valid workflow."""


class WorkflowPlanner:
    """Converts natural language into a list of validated ``TaskSpec``.

    Args:
        registry:     Tool catalog used both to build the prompt and to
                       validate the model's output. Defaults to the global registry.
        model_name:   Gemini model to call. Defaults to ``DEFAULT_MODEL``.
        max_retries:  Number of corrective re-prompts after an initial failed
                       attempt (so ``max_retries=2`` means up to 3 total calls).
        generate_fn:  Optional override for the model call itself — mainly for
                       tests. Signature: ``async (system_prompt, user_prompt) -> str``.
                       When omitted, calls Gemini via ``google-generativeai``.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        model_name: str | None = None,
        max_retries: int = 2,
        generate_fn: GenerateFn | None = None,
    ) -> None:
        self._registry = registry or default_registry
        self._model_name = model_name or DEFAULT_MODEL
        self._max_retries = max_retries
        self._generate_fn = generate_fn

    async def plan(self, request: str) -> list[TaskSpec]:
        """Turn a natural language request into a validated list of ``TaskSpec``.

        Raises:
            PlannerError: If no valid workflow could be produced within the
                          retry budget, or if the model call itself fails
                          (e.g. missing API key, missing SDK, API error).
        """
        generate = self._generate_fn or self._default_generate
        system_prompt = build_system_prompt(self._registry)

        feedback: str | None = None
        last_raw_text = ""
        last_error = "unknown error"

        for attempt in range(self._max_retries + 1):
            user_prompt = build_user_prompt(request, feedback=feedback)
            log.debug(
                "Planner prompt",
                attempt=attempt, system_prompt=system_prompt, user_prompt=user_prompt,
            )

            try:
                raw_text = await generate(system_prompt, user_prompt)
            except PlannerError:
                raise
            except Exception as exc:
                raise PlannerError(f"Model call failed: {exc}") from exc

            last_raw_text = raw_text
            log.debug("Planner model response", attempt=attempt, raw_text=raw_text[:2000])

            try:
                task_specs = _parse_response(raw_text)
                _validate_specs(task_specs, self._registry)
            except PlannerError as exc:
                last_error = str(exc)
                feedback = last_error
                log.warning(
                    "Planner attempt failed validation",
                    attempt=attempt, max_retries=self._max_retries, error=last_error,
                )
                continue

            log.info("Planner produced a valid workflow", attempt=attempt, task_count=len(task_specs))
            return task_specs

        raise PlannerError(
            f"Planner failed to produce a valid workflow after {self._max_retries + 1} attempt(s). "
            f"Last error: {last_error}. Last raw output: {last_raw_text[:500]!r}"
        )

    async def _default_generate(self, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini via google-generativeai. Overridden in tests via ``generate_fn``."""
        settings = get_settings()
        if not settings.gemini_api_key:
            raise PlannerError(
                "GEMINI_API_KEY is not set. Add it to your .env file to use the planner."
            )

        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise PlannerError(
                "google-generativeai is not installed. Run: pip install google-generativeai"
            ) from exc

        genai.configure(api_key=settings.gemini_api_key)

        model = genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )

        try:
            response = await model.generate_content_async(user_prompt)
        except Exception as exc:
            raise PlannerError(f"Gemini API error: {exc}") from exc

        return response.text


def _parse_response(raw_text: str) -> list[TaskSpec]:
    """Parse the model's raw text into a list of TaskSpec, or raise PlannerError."""
    text = raw_text.strip()
    # Models sometimes wrap JSON in markdown fences despite instructions not to.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Model returned invalid JSON: {exc}") from exc

    if not isinstance(data, dict) or "tasks" not in data:
        raise PlannerError('Model output must be a JSON object with a "tasks" array.')

    tasks_data = data["tasks"]
    if not isinstance(tasks_data, list) or not tasks_data:
        raise PlannerError('"tasks" must be a non-empty array.')

    try:
        return [TaskSpec(**task) for task in tasks_data]
    except (ValidationError, TypeError) as exc:
        raise PlannerError(f"Model output failed schema validation: {exc}") from exc


def _validate_specs(task_specs: list[TaskSpec], registry: ToolRegistry) -> None:
    """Compile the specs to catch unknown tools, missing deps, cycles, etc."""
    compiler = WorkflowCompiler(known_tools=registry.tool_names())
    try:
        compiler.compile(task_specs)
    except MultipleCompilationErrors as exc:
        messages = "; ".join(e.message for e in exc.errors)
        raise PlannerError(f"Workflow validation failed: {messages}") from exc
    except CompilationError as exc:
        raise PlannerError(f"Workflow validation failed: {exc.message}") from exc
