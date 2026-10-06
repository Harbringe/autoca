#!/usr/bin/env python3
"""Turn an .env file into AWS Parameter Store parameters, so you do not create them one by one in the console.

Meant to be run in AWS CloudShell (the terminal in the AWS console: already signed in, Python and boto3 included):

    1. Open CloudShell (the >_ icon at the top of the console), region Mumbai.
    2. Actions -> Upload file -> choose this script, then your env file (for example env.txt).
    3. python3 import_env.py env.txt                  shows what it would do. Writes nothing.
    4. python3 import_env.py env.txt --apply          creates the parameters.
    5. rm env.txt                                      delete the file when done.

It prints only names and what it did, never a value. Each setting becomes /autoca/prod/NAME as a SecureString.
An existing parameter is left alone unless you add --overwrite. Lines that are comments, blank, empty-valued, or whose
names are not plain setting names, or would change how a process starts (LD_*, PYTHON*, PATH, DJANGO_SETTINGS_MODULE...),
are skipped and listed. The same rules the server applies when it pulls them are applied here, so nothing is created
that the server would refuse.

The values go to AWS over the AWS SDK; they are never put on a command line or printed.
"""

from __future__ import annotations

import argparse
import re
import sys

PREFIX = "/autoca/prod/"
REGION = "ap-south-1"

# Keep in step with integrations/paramstore.py (a test checks they agree).
NEVER = frozenset(
    {
        "PARAMETER_PREFIX",
        "PARAMETER_REGION",
        "DJANGO_SETTINGS_MODULE",
        "DEBUG",
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "IFS",
        "BASH_ENV",
        "ENV",
        "DATABASE_OWNER_URL",
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
        "AUTOCA_OWNER_PASSWORD",
        "AUTOCA_WEB_PASSWORD",
    }
)
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
NAME = re.compile(r"[A-Z][A-Z0-9_]{0,99}")


def parse(text: str) -> tuple[dict[str, str], list[str]]:
    """The settings in an .env file, and notes on lines that were not usable. Values are never in the notes."""
    found: dict[str, str] = {}
    notes: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            notes.append(f"line {number}: not NAME=VALUE")
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not NAME.fullmatch(name):
            notes.append(f"line {number}: {name[:40]!r} is not a setting name")
        elif (
            name in NEVER
            or name.startswith(NEVER_PREFIXES)
            or any(part in name for part in NEVER_CONTAINS)
        ):
            notes.append(f"{name}: refused (changes how a process starts)")
        elif not value:
            notes.append(f"{name}: empty, skipped")
        else:
            found[name] = value
    return found, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create Parameter Store parameters from an .env file."
    )
    parser.add_argument("file", help="the .env file to read")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create the parameters (without it, only show the plan)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace parameters that already exist"
    )
    parser.add_argument("--prefix", default=PREFIX)
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args(argv)
    prefix = args.prefix if args.prefix.endswith("/") else args.prefix + "/"

    with open(args.file, encoding="utf-8") as handle:
        settings, notes = parse(handle.read())
    for note in notes:
        print(f"skipped  {note}")
    if not settings:
        print("Nothing to import.")
        return 1

    client = None
    existing: set[str] = set()
    if True:
        import boto3

        client = boto3.client("ssm", region_name=args.region)
        token = None
        while True:
            kwargs = {"Path": prefix.rstrip("/"), "Recursive": False}
            if token:
                kwargs["NextToken"] = token
            page = client.get_parameters_by_path(**kwargs)
            existing.update(p["Name"].removeprefix(prefix) for p in page.get("Parameters", []))
            token = page.get("NextToken")
            if not token:
                break

    created = left = 0
    for name in sorted(settings):
        exists = name in existing
        if exists and not args.overwrite:
            print(f"exists   {prefix}{name} (left as it is; add --overwrite to replace)")
            left += 1
            continue
        if not args.apply:
            print(f"would {'replace' if exists else 'create '} {prefix}{name} (SecureString)")
            continue
        client.put_parameter(
            Name=prefix + name, Value=settings[name], Type="SecureString", Overwrite=exists
        )
        print(f"{'replaced' if exists else 'created '} {prefix}{name}")
        created += 1

    if args.apply:
        print(f"Done: {created} written, {left} left as they were.")
    else:
        print("Nothing was written. Run again with --apply to create them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
