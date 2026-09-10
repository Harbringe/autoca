"""In-process queue adapter for tests. Records calls, runs nothing."""

from .base import EnqueuedJob, QueueAdapter


class EagerQueueAdapter(QueueAdapter):
    def __init__(self, **_ignored):
        self.calls = []

    def enqueue(self, task_name, firm_id, *args, **kwargs):
        job = EnqueuedJob(
            job_id=f"eager-{len(self.calls)}", task_name=task_name, firm_id=str(firm_id)
        )
        self.calls.append((job, args, kwargs))
        return job
