from app.domain.enums import TERMINAL_STATUSES, JobStatus
from app.domain.state_machine import VALID_TRANSITIONS, can_transition, is_terminal


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for status in TERMINAL_STATUSES:
        assert VALID_TRANSITIONS[status] == frozenset()
        assert is_terminal(status)


def test_every_status_is_present_in_the_transition_map() -> None:
    for status in JobStatus:
        assert status in VALID_TRANSITIONS


def test_selected_valid_transitions() -> None:
    assert can_transition(JobStatus.PENDING, JobStatus.QUEUED)
    assert can_transition(JobStatus.QUEUED, JobStatus.RUNNING)
    assert can_transition(JobStatus.RUNNING, JobStatus.RETRYING)
    assert can_transition(JobStatus.RUNNING, JobStatus.CANCELLING)
    assert can_transition(JobStatus.RUNNING, JobStatus.QUEUED)
    assert can_transition(JobStatus.RETRYING, JobStatus.QUEUED)
    assert can_transition(JobStatus.CANCELLING, JobStatus.CANCELLED)
    assert can_transition(JobStatus.CANCELLING, JobStatus.SUCCEEDED)


def test_selected_invalid_transitions() -> None:
    assert not can_transition(JobStatus.SUCCEEDED, JobStatus.RUNNING)
    assert not can_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED)
    assert not can_transition(JobStatus.PENDING, JobStatus.RUNNING)
    assert not can_transition(JobStatus.CANCELLED, JobStatus.QUEUED)
