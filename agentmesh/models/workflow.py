"""Workflow ORM model."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentmesh.persistence import Base


class WorkflowStatus(str, enum.Enum):
    """Workflow lifecycle states."""

    CREATED = "CREATED"
    COMPILING = "COMPILING"
    COMPILED = "COMPILED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Workflow(Base):
    """A workflow represents a complete execution plan consisting of tasks."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status"),
        nullable=False,
        default=WorkflowStatus.CREATED,
        index=True,
    )
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    compiled_graph: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="workflow",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    logs: Mapped[list["WorkflowLog"]] = relationship(
        "WorkflowLog",
        back_populates="workflow",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<Workflow {self.id} status={self.status}>"


# Import here to avoid circular imports — these are needed for relationship resolution
from agentmesh.models.task import Task  # noqa: E402, F401
from agentmesh.models.log import WorkflowLog  # noqa: E402, F401
