"""Settings kept in AWS Systems Manager Parameter Store, read at deploy time.

Run in a one-off web container by ``deploy/pull-secrets.sh``, where the server's IAM role signs the request (no key
is stored anywhere):

    python -m integrations.paramstore            prints KEY=VALUE lines for the settings that may live here

Any setting can live here: create a parameter named ``/autoca/prod/<SETTING_NAME>`` and it is written into
``.env.prod`` at the next deploy, replacing what was there.

The exception is :data:`SEED_ONLY`: the three permanent keys and the web role's database URL. Losing or changing one of
those loses stored data or signs everyone out, so a parameter may *fill them in when the server has none* (a new
server, or recovery from a lost file, which makes Parameter Store a backup of them) but never replaces a value the
server already has. A difference is reported as a warning, by name only.

Output is ``KEY=VALUE`` lines, and ``?KEY=VALUE`` for a seed-only setting. Values are printed to stdout for the calling
script to merge; they are never logged, and a value that contains a line break is refused rather than written, since it
could smuggle in a second setting.
"""

from __future__ import annotations

import os
import re
import sys

PREFIX_ENV = "PARAMETER_PREFIX"
REGION_ENV = "PARAMETER_REGION"
DEFAULT_PREFIX = "/autoca/prod/"
DEFAULT_REGION = "ap-south-1"

#: Settings a parameter may fill in but never replace. See the module note.
SEED_ONLY = frozenset(
    {"KMS_LOCAL_MASTER_KEY", "BLIND_INDEX_KEY", "DJANGO_SECRET_KEY", "DATABASE_URL"}
)

#: Names that can never be set from a parameter: they steer this very mechanism, or change how a process starts or
#: which code it loads, so a stray or malicious parameter could hijack the container.
NEVER = frozenset(
    {
        PREFIX_ENV,
        REGION_ENV,
        "DJANGO_SETTINGS_MODULE",
        "DEBUG",
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "IFS",
        "BASH_ENV",
        "ENV",
        # The database owner and bootstrap credentials live in .env.owner and .env.db, apart from the web process on
        # purpose: the web process runs as a role that row-level security binds, and must never hold the owner's.
        "DATABASE_OWNER_URL",
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
        "AUTOCA_OWNER_PASSWORD",
        "AUTOCA_WEB_PASSWORD",
    }
)
#: Prefixes that are never settings: the dynamic loader, the language runtimes, and the container tooling.
#: Any name containing one of these is refused as well, so a differently spelled owner credential is caught too.
NEVER_CONTAINS = ("OWNER", "POSTGRES")
NEVER_PREFIXES = (
    "LD_",
    "DYLD_",
    "PYTHON",
    "NODE_",
    "RUBY",
    "PERL",
    "COMPOSE_",
    "DOCKER_",
    "AWS_",
    "BASH_",
)

_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,99}")


class ParameterError(RuntimeError):
    """A parameter could not be used. The message names the parameter, never its value."""


def usable(name: str, value: str) -> bool:
    """True when ``value`` may be written as the setting ``name``."""
    return (
        bool(_NAME.fullmatch(name))
        and name not in NEVER
        and not name.startswith(NEVER_PREFIXES)
        and not any(part in name for part in NEVER_CONTAINS)
        and "\n" not in value
        and "\r" not in value
        and value != ""
    )


def settings_from(parameters, prefix: str) -> tuple[dict[str, str], list[str]]:
    """The usable settings in ``parameters`` (each with ``Name`` and ``Value``), and the names left out and why.

    A seed-only setting comes back under a ``?`` prefix so the caller knows not to replace an existing value.
    """
    found: dict[str, str] = {}
    skipped: list[str] = []
    for parameter in parameters:
        name = parameter["Name"].removeprefix(prefix).strip("/")
        value = parameter["Value"]
        if not usable(name, value):
            skipped.append(f"{name} (not a setting name, empty, or has a line break)")
        else:
            found[("?" if name in SEED_ONLY else "") + name] = value
    return found, skipped


def fetch(prefix: str, region: str) -> list[dict]:
    import boto3

    client = boto3.client("ssm", region_name=region)
    out: list[dict] = []
    token = None
    while True:
        args = {"Path": prefix.rstrip("/"), "WithDecryption": True, "Recursive": False}
        if token:
            args["NextToken"] = token
        page = client.get_parameters_by_path(**args)
        out.extend(page.get("Parameters", []))
        token = page.get("NextToken")
        if not token:
            return out


def main() -> int:
    prefix = os.environ.get(PREFIX_ENV, DEFAULT_PREFIX)
    if not prefix.endswith("/"):
        prefix += "/"
    region = os.environ.get(REGION_ENV, DEFAULT_REGION)
    try:
        parameters = fetch(prefix, region)
    except Exception as exc:  # noqa: BLE001 -- boto raises many types; the type is enough to act on
        sys.stderr.write(
            f"paramstore: could not read {prefix} ({type(exc).__name__}). The settings file is unchanged.\n"
        )
        return 2
    found, skipped = settings_from(parameters, prefix)
    for note in skipped:
        sys.stderr.write(f"paramstore: left out {note}\n")
    for name in sorted(found):
        sys.stdout.write(f"{name}={found[name]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
