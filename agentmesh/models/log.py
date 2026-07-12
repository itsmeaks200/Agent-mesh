"""Workflow log ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentmesh.persistence import Base


class WorkflowLog(Base):
    """Append-only log entries for workflow and task events."""

    __tablename__ = "workflow_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    level: Mapped[str] = mapped_column(String(10), nullable=False)  # DEBUG/INFO/WARN/ERROR
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Relationships
    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="logs")

    def __repr__(self) -> str:
        return f"<WorkflowLog [{self.level}] {self.message[:50]}>"


# Avoid circular import
from agentmesh.models.workflow import Workflow  # noqa: E402, F401
