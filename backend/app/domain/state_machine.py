from app.domain.enums import TERMINAL_STATUSES, JobStatus

VALID_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED, JobStatus.EXPIRED}),
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.EXPIRED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.RETRYING,
            JobStatus.CANCELLING,
            JobStatus.QUEUED,
        }
    ),
    JobStatus.RETRYING: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.CANCELLING: frozenset({JobStatus.CANCELLED, JobStatus.SUCCEEDED, JobStatus.FAILED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.EXPIRED: frozenset(),
}


def can_transition(source: JobStatus, target: JobStatus) -> bool:
    return target in VALID_TRANSITIONS[source]


def is_terminal(status: JobStatus) -> bool:
    return status in TERMINAL_STATUSES
