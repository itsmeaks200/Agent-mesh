"""Pydantic schemas for Workflow API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ── Request Schemas ──────────────────────────────────────────────────────────


class TaskSpec(BaseModel):
    """A single task specification within a workflow request."""

    id: str = Field(..., min_length=1, max_length=100, description="Unique task identifier")
    tool: str = Field(..., min_length=1, max_length=50, description="Tool to execute")
    params: dict = Field(default_factory=dict, description="Tool-specific parameters")
    depends_on: list[str] = Field(
        default_factory=list, description="List of task IDs this task depends on"
    )


class WorkflowCreateRequest(BaseModel):
    """Request to create a workflow from an explicit task specification."""

    tasks: list[TaskSpec] = Field(..., min_length=1, description="List of tasks to execute")

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "tasks": [
                    {
                        "id": "fetch_data",
                        "tool": "http",
                        "params": {"url": "https://api.example.com/data", "method": "GET"},
                        "depends_on": [],
                    },
                    {
                        "id": "process",
                        "tool": "llm",
                        "params": {"prompt": "Summarize: {{fetch_data.output}}"},
                        "depends_on": ["fetch_data"],
                    },
                ]
            }
        ]
    }}


class AgentRunRequest(BaseModel):
    """Request to create a workflow from natural language (Phase 6)."""

    request: str = Field(
        ..., min_length=1, max_length=5000, description="Natural language request"
    )


# ── Response Schemas ─────────────────────────────────────────────────────────


class TaskResultResponse(BaseModel):
    """Serialized task result."""

    id: UUID
    task_id: UUID
    data: dict | None = None
    status: str
    duration_ms: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    """Serialized task within a workflow response."""

    id: UUID
    task_key: str
    tool_name: str
    params: dict
    status: str
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: int = 300
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    worker_id: str | None = None
    depends_on_keys: list[str] = Field(
        default_factory=list, description="Task keys this task depends on"
    )
    result: TaskResultResponse | None = None

    model_config = {"from_attributes": True}


class WorkflowResponse(BaseModel):
    """Serialized workflow response."""

    id: UUID
    status: str
    request_text: str | None = None
    total_tasks: int = 0
    completed_tasks: int = 0
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    tasks: list[TaskResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class WorkflowSummaryResponse(BaseModel):
    """Lightweight workflow response for list endpoints (no tasks)."""

    id: UUID
    status: str
    request_text: str | None = None
    total_tasks: int = 0
    completed_tasks: int = 0
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    """Paginated list of workflows."""

    workflows: list[WorkflowSummaryResponse]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    """Standardized error response."""

    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Wrapper for error responses."""

    error: ErrorDetail


# ── Compile Schemas ──────────────────────────────────────────────────────────


class CompileErrorDetail(BaseModel):
    """A single compilation error."""

    code: str
    message: str
    details: dict = Field(default_factory=dict)


class CompileResponse(BaseModel):
    """Result of compiling a workflow specification."""

    valid: bool = Field(description="Whether the workflow compiled successfully")
    execution_order: list[list[str]] = Field(
        default_factory=list,
        description="Tasks grouped by topological level (parallel batches)",
    )
    topological_sort: list[str] = Field(
        default_factory=list,
        description="Full linear topological ordering",
    )
    total_tasks: int = 0
    total_levels: int = 0
    graph: dict = Field(
        default_factory=dict,
        description="Serialized adjacency representation of the DAG",
    )
    errors: list[CompileErrorDetail] = Field(
        default_factory=list,
        description="Compilation errors (empty when valid=True)",
    )
