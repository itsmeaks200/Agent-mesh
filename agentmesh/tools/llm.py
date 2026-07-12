"""LLMTool — generate or transform text using the Gemini API.

Requires GEMINI_API_KEY in the environment. Degrades gracefully if missing.
"""

from __future__ import annotations

import time

from agentmesh.tools.base import BaseTool, ToolContext, ToolResult

DEFAULT_MODEL = "gemini-2.0-flash"


class LLMTool(BaseTool):
    """Call the Gemini API to generate or transform text.

    Required params:
        prompt (str): The user prompt to send to the model.

    Optional params:
        model (str):       Gemini model name. Default: "gemini-2.0-flash".
        system (str):      System instruction prepended to the prompt.
        temperature (float): Sampling temperature 0.0–2.0. Default: 0.7.

    Output::

        {
          "text": "The generated response...",
          "model": "gemini-2.0-flash",
          "prompt_tokens": 42,
          "output_tokens": 128
        }

    Graceful degradation:
        If GEMINI_API_KEY is not set, returns ToolResult.failure with
        a clear message instead of crashing.
    """

    name = "llm"
    description = (
        "Call the Gemini API to generate text, summarize content, "
        "or transform data using a natural language prompt."
    )

    async def execute(self, context: ToolContext) -> ToolResult:
        start = time.monotonic()

        prompt = context.params.get("prompt", "").strip()
        if not prompt:
            return ToolResult.failure(
                error="LLMTool requires a 'prompt' parameter.",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        model_name = context.params.get("model", DEFAULT_MODEL)
        system_instruction = context.params.get("system")
        temperature = float(context.params.get("temperature", 0.7))

        # Import here to avoid hard dependency at module load
        try:
            import google.generativeai as genai
        except ImportError:
            return ToolResult.failure(
                error=(
                    "google-generativeai is not installed. "
                    "Run: pip install google-generativeai"
                ),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        from agentmesh.config import get_settings

        settings = get_settings()
        if not settings.gemini_api_key:
            return ToolResult.failure(
                error=(
                    "GEMINI_API_KEY is not set. "
                    "Add it to your .env file to use the LLM tool."
                ),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            genai.configure(api_key=settings.gemini_api_key)

            generation_config = genai.GenerationConfig(temperature=temperature)

            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_instruction,
                generation_config=generation_config,
            )

            # Build content — prepend system if provided
            response = await model.generate_content_async(prompt)

            text = response.text
            usage = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
            output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

            return ToolResult.success(
                data={
                    "text": text,
                    "model": model_name,
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                },
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        except Exception as exc:
            return ToolResult.failure(
                error=f"Gemini API error: {exc}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
