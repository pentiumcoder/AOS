from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

FIELDS = ("task_id", "run_id", "node", "subtask_id", "agent", "attempt")

_vars: dict[str, ContextVar[Any]] = {name: ContextVar(name, default=None) for name in FIELDS}


def get(name: str) -> Any:
    return _vars[name].get()


def current() -> dict[str, Any]:
    return {name: var.get() for name, var in _vars.items()}


@contextmanager
def bind(**values: Any) -> Iterator[None]:
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise KeyError(f"unknown context fields: {sorted(unknown)}")
    tokens = [(_vars[name], _vars[name].set(value)) for name, value in values.items()]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
