"""Settings kept in AWS Systems Manager Parameter Store, read at deploy time.

Run in a one-off web container by ``deploy/pull-secrets.sh``, where the server's IAM role signs the request (no key
is stored anywhere):

    python -m integrations.paramstore            prints KEY=VALUE lines for the settings that may live here

Only the names in :data:`MANAGED` are ever returned, whatever else sits under the path. That list is the whole
policy and is deliberately short:

* **Never** the three permanent keys (``KMS_LOCAL_MASTER_KEY``, ``BLIND_INDEX_KEY``, ``DJANGO_SECRET_KEY``) or any
  database password. Losing or changing one of those loses data or signs everyone out, so they are not something a
  deploy should be able to overwrite from a parameter that someone may edit in a console.
* Provider keys and service settings, which are replaced by changing the parameter and deploying.

The values are printed to stdout for the calling script to merge into ``.env.prod``; they are never logged, and
a value that contains a line break is refused rather than written, since it could smuggle in a second setting.
"""

from __future__ import annotations

import os
import sys

PREFIX_ENV = "PARAMETER_PREFIX"
REGION_ENV = "PARAMETER_REGION"
DEFAULT_PREFIX = "/autoca/prod/"
DEFAULT_REGION = "ap-south-1"

#: The settings a parameter may set. Add a name here to let it be managed from Parameter Store.
MANAGED = frozenset(
    {
        "LLM_API_KEY",
        "LLM_MODEL",
        "LLM_BASE_URL",
        "GROQ_API_KEY",
        "STORAGE_ACCESS_KEY_ID",
        "STORAGE_SECRET_ACCESS_KEY",
    }
)


class ParameterError(RuntimeError):
    """A parameter could not be used. The message names the parameter, never its value."""


def usable(name: str, value: str) -> bool:
    """True when ``value`` may be written as the setting ``name``. Anything with a line break may not."""
    return name in MANAGED and "\n" not in value and "\r" not in value and value != ""


def settings_from(parameters, prefix: str) -> tuple[dict[str, str], list[str]]:
    """The managed settings in ``parameters`` (each with ``Name`` and ``Value``), and the names left out and why."""
    found: dict[str, str] = {}
    skipped: list[str] = []
    for parameter in parameters:
        name = parameter["Name"].removeprefix(prefix).strip("/")
        value = parameter["Value"]
        if name not in MANAGED:
            skipped.append(f"{name} (not a managed setting)")
        elif not usable(name, value):
            skipped.append(f"{name} (empty or has a line break)")
        else:
            found[name] = value
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
