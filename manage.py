#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main() -> None:
    # Amounts are printed with the rupee sign, and a Windows console defaults to
    # cp1252, which cannot encode it -- so a command that reports a figure dies
    # with a UnicodeEncodeError instead of reporting the figure. Deployment is
    # Linux, but development is not, and an error path that crashes on its own
    # error message is worse than useless.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Couldn't import Django. Is it installed and is your virtualenv active?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
