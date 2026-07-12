"""Top-level API router aggregating all sub-routers."""

from fastapi import APIRouter

from agentmesh.api.tools import router as tools_router
from agentmesh.api.workflows import router as workflows_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(workflows_router)
api_router.include_router(tools_router)
