import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import JobPriority, JobStatus, JobType


class JobSubmit(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: JobPriority = JobPriority.NORMAL
    max_attempts: int | None = Field(default=None, ge=1)


class JobAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    status: JobStatus
    status_url: str


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, populate_by_name=True)

    job_id: uuid.UUID = Field(validation_alias="id")
    type: JobType
    status: JobStatus
    priority: JobPriority
    progress: int
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime


class JobRead(JobSummary):
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    cancellation_requested_at: datetime | None
    cancel_reason: str | None
    dead_lettered_at: datetime | None
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None


class CancelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str | None = None


class CancelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    status: JobStatus


class JobEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    event_type: str
    from_status: str | None
    to_status: str | None
    detail: dict[str, Any]
    created_at: datetime


class JobEvents(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[JobEvent]


class JobSummaryCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    counts: dict[str, int]
    total: int
