"""Celery-over-Redis queue adapter -- the development-tier backend.

Broker is Upstash Redis on the free tier: 500K commands/month, 256MB. Ample for
solo development; worth watching once real document processing starts, because
Celery's own bookkeeping consumes commands even when idle. The broker URL must be rediss:// with ?ssl_cert_reqs=required so kombu
verifies Upstash's certificate; plain rediss:// is TLS but unauthenticated.
"""

from .base import EnqueuedJob, QueueAdapter


class CeleryRedisQueueAdapter(QueueAdapter):
    def __init__(self, broker_url=None, **_ignored):
        self.broker_url = broker_url

    def enqueue(self, task_name, firm_id, *args, **kwargs):
        from config.celery import app

        # firm_id travels in the envelope, not in the task body, so a worker
        # can establish tenant context before it deserialises anything else.
        result = app.send_task(
            task_name,
            args=args,
            kwargs=kwargs,
            headers={"firm_id": str(firm_id)},
        )
        return EnqueuedJob(job_id=result.id, task_name=task_name, firm_id=str(firm_id))
