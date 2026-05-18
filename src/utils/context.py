import uuid
import contextvars
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Context:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    method: str = ""


request_context: contextvars.ContextVar[Optional[Context]] = contextvars.ContextVar(
    "request_context", default=None
)


def new_context(method: str = "", headers: dict = None) -> Context:
    return Context(run_id=uuid.uuid4().hex, method=method)
