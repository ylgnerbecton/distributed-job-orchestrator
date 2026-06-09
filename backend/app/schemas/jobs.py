from marshmallow import Schema, fields, validate

from app.domain.enums import JobPriority, JobStatus, JobType

_JOB_TYPES = [job_type.value for job_type in JobType]
_PRIORITIES = [priority.value for priority in JobPriority]
_STATUSES = [status.value for status in JobStatus]


class JobSubmitSchema(Schema):
    type = fields.Str(required=True, validate=validate.OneOf(_JOB_TYPES))
    payload = fields.Dict(load_default=dict)
    priority = fields.Str(load_default=JobPriority.NORMAL.value, validate=validate.OneOf(_PRIORITIES))
    max_attempts = fields.Int(required=False, validate=validate.Range(min=1))


class JobAcceptedSchema(Schema):
    job_id = fields.Str(required=True)
    status = fields.Str(required=True)
    status_url = fields.Str(required=True)


class JobSummarySchema(Schema):
    job_id = fields.UUID(attribute="id", data_key="job_id")
    type = fields.Str()
    status = fields.Str()
    priority = fields.Str()
    progress = fields.Int()
    attempts = fields.Int()
    max_attempts = fields.Int()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class JobSchema(JobSummarySchema):
    payload = fields.Dict()
    result = fields.Raw(allow_none=True)
    error_code = fields.Str(allow_none=True)
    error_message = fields.Str(allow_none=True)
    cancellation_requested_at = fields.DateTime(allow_none=True)
    cancel_reason = fields.Str(allow_none=True)
    dead_lettered_at = fields.DateTime(allow_none=True)
    queued_at = fields.DateTime(allow_none=True)
    started_at = fields.DateTime(allow_none=True)
    completed_at = fields.DateTime(allow_none=True)


class PaginatedJobsSchema(Schema):
    items = fields.List(fields.Nested(JobSummarySchema))
    next_cursor = fields.Str(allow_none=True)
    has_more = fields.Bool()


class JobQuerySchema(Schema):
    status = fields.Str(required=False, validate=validate.OneOf(_STATUSES))
    type = fields.Str(required=False, validate=validate.OneOf(_JOB_TYPES))
    limit = fields.Int(load_default=50, validate=validate.Range(min=1, max=200))
    cursor = fields.Str(required=False)


class CancelSchema(Schema):
    reason = fields.Str(required=False, allow_none=True)


class CancelResultSchema(Schema):
    job_id = fields.Str()
    status = fields.Str()


class JobEventSchema(Schema):
    event_type = fields.Str()
    from_status = fields.Str(allow_none=True)
    to_status = fields.Str(allow_none=True)
    detail = fields.Dict()
    created_at = fields.DateTime()


class JobEventsSchema(Schema):
    items = fields.List(fields.Nested(JobEventSchema))


class JobSummaryCountsSchema(Schema):
    counts = fields.Dict(keys=fields.Str(), values=fields.Int())
    total = fields.Int()
