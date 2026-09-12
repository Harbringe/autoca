"""Nothing identifying reaches a log line.

Exceptions in this codebase are written to be read, and they quote the data
that broke: "Balance chain broke at row 30 (26-07-2025, 'NEFT/MB/AXOMB2070...')".
That is right for the person looking at the failed job and wrong for a log
aggregator that keeps ninety days of everything. This filter runs every record
through the same masking the classifier uses before a model sees a narration
-- one implementation, so the two cannot disagree about what counts as
identifying.

Installed on the root logger's handler, so it covers third-party loggers too:
a database driver echoing a failed statement, a client library logging a
request body.
"""

from __future__ import annotations

import logging

from core.masking import mask_text


class MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 -- a bad format string is not our problem here
            return True
        record.msg = mask_text(message)
        record.args = ()
        if record.exc_text:
            record.exc_text = mask_text(record.exc_text)
        return True
