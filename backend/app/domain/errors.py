class JobExecutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RetryableError(JobExecutionError):
    pass


class NonRetryableError(JobExecutionError):
    pass


class JobCancelledError(Exception):
    pass


class UnknownJobTypeError(ValueError):
    pass


class PayloadTooLargeError(ValueError):
    pass
