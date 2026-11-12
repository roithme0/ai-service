"""Execution error helpers for evaluations."""

from pydantic import BaseModel


class ExecutionError(BaseModel):
    stage: str
    type: str
    exception_types: list[str]
    message: str


class CaseExecutionError(Exception):
    def __init__(self, stage: str, error: Exception) -> None:
        super().__init__(stage)
        self.stage = stage
        self.error = error


def exception_types(error: BaseException) -> list[str]:
    name = type(error).__name__
    safe_name = name if name.isidentifier() and len(name) <= 100 else "UnknownError"
    names = [safe_name]
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            names.extend(exception_types(nested))
    return names


def wrapped_execution_error(error: BaseException) -> CaseExecutionError | None:
    if isinstance(error, CaseExecutionError):
        return error
    if isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        return wrapped_execution_error(error.exceptions[0])
    return None
