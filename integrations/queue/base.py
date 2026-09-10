"""Background job interface.

Dev:  Upstash Redis as the Celery broker (500K commands/month, 256MB)
Beta: AWS SQS or ElastiCache

The interface is deliberately narrower than Celery's. Callers get "run this
named task, for this firm, with these arguments, later" and nothing else -- no
chains, no chords, no signatures. Those are Celery-shaped concepts, and exposing
them would weld the codebase to Celery and make the SQS swap a rewrite.

Note the mandatory ``firm_id``. A queued job runs outside the request cycle, so
``TenantContextMiddleware`` is not there to set the tenant context. Carrying the
firm id in the envelope is what lets the worker re-enter ``firm_context()``
before touching the database -- and makes a job that forgot to impossible to
express.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class EnqueuedJob:
    job_id: str
    task_name: str
    firm_id: str


class QueueAdapter(abc.ABC):
    @abc.abstractmethod
    def enqueue(self, task_name: str, firm_id, *args, **kwargs) -> EnqueuedJob:
        ...

    @property
    def name(self) -> str:
        return type(self).__name__
