"""ToolRegistry — central registry for discovering and retrieving tools by name."""

from __future__ import annotations

from agentmesh.tools.base import BaseTool


class ToolNotFoundError(Exception):
    """Raised when a requested tool is not registered."""

    def __init__(self, name: str, known_tools: list[str]) -> None:
        self.name = name
        self.known_tools = known_tools
        super().__init__(
            f"Tool '{name}' is not registered. "
            f"Available tools: {', '.join(sorted(known_tools)) or 'none'}"
        )


class ToolRegistry:
    """Registry for AgentMesh tools.

    Tools are registered by name and retrieved by name.
    A default global registry is created at module level and pre-populated
    with all built-in tools.

    Usage::

        registry = ToolRegistry()
        registry.register(EchoTool())
        tool = registry.get("echo")
        result = await tool.execute(context)
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance. Overwrites any existing tool with the same name."""
        if not tool.name:
            raise ValueError(f"Tool {tool.__class__.__name__} has no name defined.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Return the tool registered under ``name``.

        Raises:
            ToolNotFoundError: If no tool with that name is registered.
        """
        if name not in self._tools:
            raise ToolNotFoundError(name=name, known_tools=list(self._tools.keys()))
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tool instances, sorted by name."""
        return sorted(self._tools.values(), key=lambda t: t.name)

    def tool_names(self) -> set[str]:
        """Return the set of all registered tool names."""
        return set(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={sorted(self._tools.keys())}>"


def _build_default_registry() -> ToolRegistry:
    """Build the default registry pre-populated with all built-in tools."""
    from agentmesh.tools.echo import EchoTool
    from agentmesh.tools.filesystem import FilesystemTool
    from agentmesh.tools.http_tool import HttpTool
    from agentmesh.tools.llm import LLMTool
    from agentmesh.tools.shell import ShellTool

    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(HttpTool())
    registry.register(FilesystemTool())
    registry.register(ShellTool())
    registry.register(LLMTool())
    return registry


# Module-level default registry — import this everywhere
default_registry: ToolRegistry = _build_default_registry()
