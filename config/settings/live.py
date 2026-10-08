"""Settings for running a server on this machine against the LIVE database, reached through an SSM tunnel (docs/LIVE.md).

Everything is as in development, except that only a short list of management commands may run. Anything that changes the
schema, loads or wipes data, runs the background assistant (which would read and send real rows to the model), or runs
the test suite (which creates and drops a database on whatever server it is pointed at) is refused here, before it can
start. The web server itself is the whole point: ``runserver``, ``check`` and a read-only look at the migrations.
"""

import sys

from django.core.exceptions import ImproperlyConfigured

from .dev import *  # noqa: F401,F403

ALLOWED_COMMANDS = {"runserver", "check", "showmigrations", "diffsettings", "shell"}

_command = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
if _command is not None and _command not in ALLOWED_COMMANDS:
    raise ImproperlyConfigured(
        f"`manage.py {_command}` is refused against the live database. Allowed here: {', '.join(sorted(ALLOWED_COMMANDS))}. "
        "Use the development settings and a local database for anything else."
    )
