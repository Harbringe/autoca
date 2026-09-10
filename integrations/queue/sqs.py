"""AWS SQS queue adapter -- beta-tier placeholder.

Deliberately unimplemented. The file exists to make the shape of the swap
concrete: moving off Upstash means writing this one method and setting
QUEUE_BACKEND=integrations.queue.sqs.SQSQueueAdapter. Nothing outside this
directory is touched.
"""

from .base import QueueAdapter


class SQSQueueAdapter(QueueAdapter):
    def __init__(self, **options):
        self.options = options

    def enqueue(self, task_name, firm_id, *args, **kwargs):
        raise NotImplementedError(
            "The SQS adapter is a beta-phase placeholder. Implement send_message "
            "here, keeping firm_id in the message attributes so the worker can "
            "enter firm_context() before touching the database."
        )
