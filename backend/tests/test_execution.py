import threading

from helpers import get_job, make_job
from sqlalchemy import func, select

from app.db.models import JobAttempt, NotificationOutbox
from app.domain.enums import JobStatus, JobType


def test_execute_flaky_succeeds_first_attempt(session_factory, execution_service) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 0})
    assert execution_service.execute(job_id) is True
    job = get_job(session_factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.attempts == 1
    assert job.progress == 100
    assert job.result == {"succeeded_on_attempt": 1}


def test_execute_sleep_records_result(session_factory, execution_service) -> None:
    job_id = make_job(session_factory, type=JobType.SLEEP.value, payload={"duration_seconds": 1, "steps": 4})
    execution_service.execute(job_id)
    job = get_job(session_factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.result["steps"] == 4


def test_execute_non_retryable_fails_without_dead_letter(session_factory, execution_service, queue) -> None:
    job_id = make_job(session_factory, type=JobType.ALWAYS_FAIL.value, payload={})
    execution_service.execute(job_id)
    job = get_job(session_factory, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.error_code == "INVALID_INPUT"
    assert job.dead_lettered_at is None
    assert queue.dead_letter_depth() == 0


def test_execute_records_attempt_and_notification(session_factory, execution_service, session) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 0})
    execution_service.execute(job_id)
    attempts = session.execute(
        select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == job_id)
    ).scalar_one()
    notifications = session.execute(
        select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.job_id == job_id)
    ).scalar_one()
    assert attempts == 1
    assert notifications == 1


def test_terminal_job_is_not_reexecuted(session_factory, execution_service) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 0})
    assert execution_service.execute(job_id) is True
    assert execution_service.execute(job_id) is False
    assert get_job(session_factory, job_id).attempts == 1


def test_concurrent_delivery_runs_job_exactly_once(session_factory, execution_service, session) -> None:
    job_id = make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 0})
    results: list[bool] = []

    def run() -> None:
        results.append(execution_service.execute(job_id))

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    job = get_job(session_factory, job_id)
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.attempts == 1
    assert results.count(True) == 1
    attempts = session.execute(
        select(func.count()).select_from(JobAttempt).where(JobAttempt.job_id == job_id)
    ).scalar_one()
    assert attempts == 1
