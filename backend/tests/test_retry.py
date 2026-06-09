from helpers import get_job, make_job, set_job_columns
from sqlalchemy import func, select

from app.core.clock import now as clock_now
from app.db.models import Job, NotificationOutbox
from app.domain.enums import JobStatus, JobType

_TERMINAL = {
    JobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.EXPIRED.value,
}


def _drain(session_factory, execution_service, retry_service, job_id, max_cycles: int = 12) -> Job:
    for _ in range(max_cycles):
        execution_service.execute(job_id)
        job = get_job(session_factory, job_id)
        if job.status in _TERMINAL:
            return job
        if job.status == JobStatus.RETRYING.value:
            set_job_columns(session_factory, job_id, next_attempt_at=clock_now())
            retry_service.promote_due(10)
    return get_job(session_factory, job_id)


def test_retry_schedules_next_attempt(session_factory, execution_service) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 5}, max_attempts=5)
    execution_service.execute(job_id)
    job = get_job(session_factory, job_id)
    assert job.status == JobStatus.RETRYING.value
    assert job.attempts == 1
    assert job.next_attempt_at is not None
    assert job.error_code == "TRANSIENT_FAILURE"


def test_flaky_succeeds_after_retries(session_factory, execution_service, retry_service) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 1}, max_attempts=5)
    job = _drain(session_factory, execution_service, retry_service, job_id)
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.attempts == 2
    assert job.result == {"succeeded_on_attempt": 2}


def test_exhausted_retries_fail_and_dead_letter(
    session_factory, execution_service, retry_service, queue, session
) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 9}, max_attempts=3)
    job = _drain(session_factory, execution_service, retry_service, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.attempts == 3
    assert job.dead_lettered_at is not None
    assert queue.dead_letter_depth() == 1
    failures = session.execute(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(NotificationOutbox.job_id == job_id, NotificationOutbox.event_type == "failed")
    ).scalar_one()
    assert failures == 1


def test_llm_rate_limit_is_retried_then_succeeds(session_factory, execution_service, retry_service) -> None:
    job_id = make_job(
        session_factory,
        type=JobType.LLM_SUMMARY.value,
        payload={"prompt": "report", "tokens": 5, "simulate_rate_limit": True},
        max_attempts=5,
    )
    job = _drain(session_factory, execution_service, retry_service, job_id)
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.attempts == 2
