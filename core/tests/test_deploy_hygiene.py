"""What the deploy files promise about secrets and logs, checked as text so a later edit cannot quietly undo it."""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def compose() -> dict:
    return yaml.safe_load((REPO / "compose.prod.yaml").read_text(encoding="utf-8"))


def test_the_one_off_tools_container_does_not_log_to_cloudwatch_and_is_never_started_by_up():
    tools = compose()["services"]["tools"]
    assert tools["logging"] == {"driver": "none"}
    assert tools["profiles"] == ["tools"]  # `up` ignores a service that belongs to a profile
    assert tools["image"] == compose()["services"]["web"]["image"]


def test_the_scripts_that_print_secrets_or_a_dump_run_in_the_tools_container():
    pull = (REPO / "deploy" / "pull-secrets.sh").read_text(encoding="utf-8")
    restore = (REPO / "deploy" / "restore.sh").read_text(encoding="utf-8")
    assert re.search(r"run --rm --no-deps -T tools\b", pull)
    assert re.search(r"run --rm --no-deps -T tools\b", restore)
    for script in (pull, restore):
        assert not re.search(r"run --rm --no-deps -T web\b", script)  # web logs to CloudWatch


def test_no_other_service_that_could_print_secrets_runs_without_the_log_decision_being_visible():
    """Every long-running service logs to CloudWatch on purpose; only `tools` does not."""
    for name, service in compose()["services"].items():
        if name == "tools":
            continue
        assert "logging" in service, f"{name} has no logging setting"


def test_the_web_access_log_records_no_query_string_and_no_referer():
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r'"--access-logformat",\s*"((?:[^"\\]|\\.)*)"', dockerfile)
    assert match, "the access log format is set"
    fmt = match.group(1)
    assert "%(U)s" in fmt  # the path without the query
    for forbidden in ("%(r)s", "%(q)s", "%(f)s", "%(a)s"):  # request line, query, Referer, User-Agent
        assert forbidden not in fmt
