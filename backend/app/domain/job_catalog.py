import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.domain.enums import JobType
from app.domain.errors import NonRetryableError, RetryableError, UnknownJobTypeError


@dataclass
class ExecutionContext:
    job_id: str
    attempt: int
    settings: Settings
    check_cancelled: Callable[[], None]
    report_progress: Callable[[int], None]
    sleeper: Callable[[float], None] = field(default=time.sleep)


JobHandler = Callable[[dict[str, Any], ExecutionContext], dict[str, Any]]


def _coerce_int(payload: dict[str, Any], key: str, default: int, minimum: int) -> int:
    raw = payload.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer") from error
    if value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return value


def _coerce_float(payload: dict[str, Any], key: str, default: float, minimum: float) -> float:
    raw = payload.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a number") from error
    if value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return value


def _run_steps(steps: int, step_seconds: float, context: ExecutionContext) -> None:
    for index in range(steps):
        context.check_cancelled()
        context.sleeper(step_seconds)
        context.report_progress(int((index + 1) / steps * 100))


def _normalize_sleep(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {
        "duration_seconds": _coerce_float(payload, "duration_seconds", settings.job_sleep_default_seconds, 0.0),
        "steps": _coerce_int(payload, "steps", settings.handler_progress_steps, 1),
    }


def _normalize_report(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {"pages": _coerce_int(payload, "pages", settings.job_report_default_pages, 1)}


def _normalize_flaky(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {"fail_times": _coerce_int(payload, "fail_times", 1, 0)}


def _normalize_always_fail(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {}


def _normalize_llm_summary(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {
        "prompt": str(payload.get("prompt", "")),
        "tokens": _coerce_int(payload, "tokens", settings.job_llm_default_tokens, 1),
        "simulate_rate_limit": bool(payload.get("simulate_rate_limit", False)),
    }


def _handle_sleep(payload: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    duration = float(payload["duration_seconds"])
    steps = int(payload["steps"])
    _run_steps(steps, duration / steps, context)
    return {"slept_seconds": duration, "steps": steps}


def _handle_report(payload: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    pages = int(payload["pages"])
    _run_steps(pages, context.settings.handler_step_seconds, context)
    return {"report_ref": f"report://{context.job_id}", "pages": pages}


def _handle_flaky(payload: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    fail_times = int(payload["fail_times"])
    context.check_cancelled()
    if context.attempt <= fail_times:
        raise RetryableError("TRANSIENT_FAILURE", f"flaky job failing on attempt {context.attempt}")
    return {"succeeded_on_attempt": context.attempt}


def _handle_always_fail(payload: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    raise NonRetryableError("INVALID_INPUT", "job type always_fail never succeeds by design")


def _handle_llm_summary(payload: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    tokens = int(payload["tokens"])
    if payload["simulate_rate_limit"] and context.attempt == 1:
        raise RetryableError("PROVIDER_RATE_LIMIT", "language model provider rate limit, retry with backoff")
    steps = context.settings.handler_progress_steps
    _run_steps(steps, context.settings.handler_step_seconds, context)
    prompt = payload["prompt"]
    summary = f"summary of {len(prompt)} character prompt" if prompt else "summary of empty prompt"
    return {"summary": summary, "tokens_used": tokens}


_NORMALIZERS: dict[JobType, Callable[[dict[str, Any], Settings], dict[str, Any]]] = {
    JobType.SLEEP: _normalize_sleep,
    JobType.REPORT: _normalize_report,
    JobType.FLAKY: _normalize_flaky,
    JobType.ALWAYS_FAIL: _normalize_always_fail,
    JobType.LLM_SUMMARY: _normalize_llm_summary,
}

_HANDLERS: dict[JobType, JobHandler] = {
    JobType.SLEEP: _handle_sleep,
    JobType.REPORT: _handle_report,
    JobType.FLAKY: _handle_flaky,
    JobType.ALWAYS_FAIL: _handle_always_fail,
    JobType.LLM_SUMMARY: _handle_llm_summary,
}


def normalize_payload(job_type: JobType, payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    normalizer = _NORMALIZERS.get(job_type)
    if normalizer is None:
        raise UnknownJobTypeError(f"unknown job type {job_type}")
    return normalizer(payload, settings)


def get_handler(job_type: JobType) -> JobHandler:
    handler = _HANDLERS.get(job_type)
    if handler is None:
        raise UnknownJobTypeError(f"unknown job type {job_type}")
    return handler
