from flask import current_app, request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from app.api.deps import current_user_id, get_session
from app.core.pagination import InvalidCursorError
from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.errors import PayloadTooLargeError, TooManyActiveJobsError
from app.schemas.common import MessageSchema
from app.schemas.jobs import (
    CancelResultSchema,
    CancelSchema,
    JobAcceptedSchema,
    JobEventsSchema,
    JobQuerySchema,
    JobSchema,
    JobSubmitSchema,
    JobSummaryCountsSchema,
    PaginatedJobsSchema,
)
from app.services.job_cancellation_service import JobCancellationService
from app.services.job_read_service import JobReadService
from app.services.job_submission_service import JobSubmissionService

_IDEMPOTENCY_HEADER = "Idempotency-Key"
_EVENTS_LIMIT = 200

jobs_blueprint = Blueprint(
    "jobs", "jobs", url_prefix="/jobs", description="Submit, inspect and cancel asynchronous jobs"
)


@jobs_blueprint.route("")
class JobCollection(MethodView):
    @jobs_blueprint.arguments(JobSubmitSchema)
    @jobs_blueprint.response(202, JobAcceptedSchema)
    @jobs_blueprint.alt_response(413, schema=MessageSchema)
    @jobs_blueprint.alt_response(422, schema=MessageSchema)
    @jobs_blueprint.alt_response(429, schema=MessageSchema)
    def post(self, body: dict) -> dict:
        service = JobSubmissionService(get_session(), current_app.config["APP_SETTINGS"])
        try:
            job = service.submit(
                user_id=current_user_id(),
                job_type=JobType(body["type"]),
                payload=body.get("payload") or {},
                priority=JobPriority(body["priority"]),
                max_attempts=body.get("max_attempts"),
                idempotency_key=request.headers.get(_IDEMPOTENCY_HEADER),
            )
        except PayloadTooLargeError as error:
            abort(413, message=str(error))
        except TooManyActiveJobsError as error:
            abort(429, message=str(error))
        except ValueError as error:
            abort(422, message=str(error))
        return {"job_id": str(job.id), "status": job.status, "status_url": f"/jobs/{job.id}"}

    @jobs_blueprint.arguments(JobQuerySchema, location="query")
    @jobs_blueprint.response(200, PaginatedJobsSchema)
    @jobs_blueprint.alt_response(400, schema=MessageSchema)
    def get(self, query: dict) -> dict:
        service = JobReadService(get_session())
        status = JobStatus(query["status"]) if query.get("status") else None
        job_type = JobType(query["type"]) if query.get("type") else None
        try:
            return service.list_jobs(
                user_id=current_user_id(),
                status=status,
                job_type=job_type,
                cursor=query.get("cursor"),
                limit=query["limit"],
            )
        except InvalidCursorError as error:
            abort(400, message=str(error))


@jobs_blueprint.route("/summary")
class JobSummaryView(MethodView):
    @jobs_blueprint.response(200, JobSummaryCountsSchema)
    def get(self) -> dict:
        return JobReadService(get_session()).summary(current_user_id())


@jobs_blueprint.route("/<uuid:job_id>")
class JobItem(MethodView):
    @jobs_blueprint.response(200, JobSchema)
    @jobs_blueprint.alt_response(404, schema=MessageSchema)
    def get(self, job_id):
        job = JobReadService(get_session()).get(job_id, current_user_id())
        if job is None:
            abort(404, message="job not found")
        return job


@jobs_blueprint.route("/<uuid:job_id>/cancel")
class JobCancel(MethodView):
    @jobs_blueprint.arguments(CancelSchema)
    @jobs_blueprint.response(200, CancelResultSchema)
    @jobs_blueprint.alt_response(202, schema=CancelResultSchema)
    @jobs_blueprint.alt_response(404, schema=MessageSchema)
    @jobs_blueprint.alt_response(409, schema=MessageSchema)
    def post(self, body: dict, job_id):
        outcome = JobCancellationService(get_session()).cancel(job_id, current_user_id(), body.get("reason"))
        if not outcome.found:
            abort(404, message="job not found")
        if outcome.conflict:
            abort(409, message="the job has already reached a terminal state and cannot be cancelled")
        status_code = 202 if outcome.status == JobStatus.CANCELLING else 200
        return {"job_id": str(job_id), "status": outcome.status.value}, status_code


@jobs_blueprint.route("/<uuid:job_id>/events")
class JobEvents(MethodView):
    @jobs_blueprint.response(200, JobEventsSchema)
    @jobs_blueprint.alt_response(404, schema=MessageSchema)
    def get(self, job_id) -> dict:
        events = JobReadService(get_session()).events(job_id, current_user_id(), _EVENTS_LIMIT)
        if events is None:
            abort(404, message="job not found")
        return {"items": events}
