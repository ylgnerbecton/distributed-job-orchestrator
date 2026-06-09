from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED}
)


class JobPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class JobType(str, Enum):
    SLEEP = "sleep"
    REPORT = "report"
    FLAKY = "flaky"
    ALWAYS_FAIL = "always_fail"
    LLM_SUMMARY = "llm_summary"


class JobEventType(str, Enum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REQUEUED = "requeued"
    EXPIRED = "expired"


class NotificationChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    LOG = "log"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
