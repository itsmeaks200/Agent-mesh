"""Tools API endpoint — list all registered tools."""

from fastapi import APIRouter

from agentmesh.tools.registry import default_registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "",
    summary="List available tools",
    description="List all tools registered in the tool runtime with their names and descriptions.",
)
async def list_tools_endpoint():
    """Return all registered tools with their metadata."""
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
            }
            for tool in default_registry.list_tools()
        ],
        "total": len(default_registry),
    }
