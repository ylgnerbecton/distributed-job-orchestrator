import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from app.api.deps import (
    current_user_id,
    get_cancellation_service,
    get_read_service,
    get_submission_service,
)
from app.core.pagination import InvalidCursorError
from app.domain.enums import JobStatus, JobType
from app.domain.errors import PayloadTooLargeError, TooManyActiveJobsError
from app.schemas.common import ErrorResponse
from app.schemas.jobs import (
    CancelRequest,
    CancelResult,
    JobAccepted,
    JobEvents,
    JobRead,
    JobSubmit,
    JobSummary,
    JobSummaryCounts,
)
from app.schemas.pagination import PaginatedResponse
from app.services.job_cancellation_service import JobCancellationService
from app.services.job_read_service import JobReadService
from app.services.job_submission_service import JobSubmissionService

router = APIRouter(prefix="/jobs", tags=["jobs"])

_EVENTS_LIMIT = 200
_NOT_FOUND = {404: {"model": ErrorResponse}}


@router.post(
    "",
    status_code=202,
    response_model=JobAccepted,
    responses={413: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def submit_job(
    body: JobSubmit,
    service: JobSubmissionService = Depends(get_submission_service),
    user_id: str = Depends(current_user_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobAccepted:
    try:
        job = await service.submit(
            user_id=user_id,
            job_type=body.type,
            payload=body.payload,
            priority=body.priority,
            max_attempts=body.max_attempts,
            idempotency_key=idempotency_key,
        )
    except PayloadTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except TooManyActiveJobsError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return JobAccepted(job_id=job.id, status=JobStatus(job.status), status_url=f"/jobs/{job.id}")


@router.get("", response_model=PaginatedResponse[JobSummary])
async def list_jobs(
    service: JobReadService = Depends(get_read_service),
    user_id: str = Depends(current_user_id),
    status: JobStatus | None = Query(default=None),
    type: JobType | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[JobSummary]:
    try:
        return await service.list_jobs(user_id=user_id, status=status, job_type=type, cursor=cursor, limit=limit)
    except InvalidCursorError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/summary", response_model=JobSummaryCounts)
async def job_summary(
    service: JobReadService = Depends(get_read_service),
    user_id: str = Depends(current_user_id),
) -> JobSummaryCounts:
    return await service.summary(user_id)


@router.get("/{job_id}", response_model=JobRead, responses=_NOT_FOUND)
async def get_job(
    job_id: uuid.UUID,
    service: JobReadService = Depends(get_read_service),
    user_id: str = Depends(current_user_id),
) -> JobRead:
    job = await service.get(job_id, user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post(
    "/{job_id}/cancel",
    response_model=CancelResult,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def cancel_job(
    job_id: uuid.UUID,
    body: CancelRequest,
    response: Response,
    service: JobCancellationService = Depends(get_cancellation_service),
    user_id: str = Depends(current_user_id),
) -> CancelResult:
    outcome = await service.cancel(job_id, user_id, body.reason)
    if not outcome.found:
        raise HTTPException(status_code=404, detail="job not found")
    if outcome.conflict or outcome.status is None:
        raise HTTPException(
            status_code=409, detail="the job has already reached a terminal state and cannot be cancelled"
        )
    if outcome.status == JobStatus.CANCELLING:
        response.status_code = 202
    return CancelResult(job_id=job_id, status=outcome.status)


@router.get("/{job_id}/events", response_model=JobEvents, responses=_NOT_FOUND)
async def job_events(
    job_id: uuid.UUID,
    service: JobReadService = Depends(get_read_service),
    user_id: str = Depends(current_user_id),
) -> JobEvents:
    events = await service.events(job_id, user_id, _EVENTS_LIMIT)
    if events is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobEvents(items=events)
