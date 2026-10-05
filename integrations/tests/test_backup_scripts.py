"""The backup scripts, run for real against a fake ``docker``.

What these defend is the property that makes a backup trustworthy: it uploads only a dump it could read back,
checks that S3 holds every byte, and otherwise fails LOUDLY and uploads nothing. A script that quietly saves a
broken file is worse than none. Postgres and S3 are replaced by a small shell shim; the scripts are not.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SH = shutil.which("sh") or "sh"
SCRIPTS = ["backup.sh", "backup-status.sh", "backup-heartbeat.sh", "restore-drill.sh", "restore.sh", "install-backups.sh"]

DOCKER_SHIM = r"""#!/bin/sh
args="$*"
case "$args" in
  *pg_dump*)
    [ -z "${FAKE_DUMP_FAIL:-}" ] || exit 1
    head -c "${FAKE_DUMP_BYTES:-30000}" /dev/zero ;;
  *pg_restore*--list*)
    cat > /dev/null
    [ -z "${FAKE_LIST_FAIL:-}" ] || exit 1
    if [ -n "${FAKE_NO_TABLES:-}" ]; then echo "; nothing here"; else echo "; Data for Name: t; TABLE DATA public t"; fi ;;
  *"integrations.backup.s3 put"*)
    cat > "$FAKE_DIR/uploaded"
    echo "$args" | sed 's/.* put //' > "$FAKE_DIR/key"
    echo "${FAKE_STORED:-$(wc -c < "$FAKE_DIR/uploaded" | tr -d ' ')}" ;;
  *"integrations.backup.s3 latest"*)
    [ -z "${FAKE_LATEST_FAIL:-}" ] || { echo "no backups found" >&2; exit 1; }
    echo "${FAKE_LATEST:-daily/2026/10/05/autoca-x.dump 3.0h 1234}" ;;
  *"integrations.backup.s3 list"*)
    echo "daily/2026/10/05/autoca-x.dump 3.0h 1234" ;;
  *) echo "unexpected docker call: $args" >&2; exit 99 ;;
esac
"""


@pytest.fixture
def sandbox(tmp_path):
    """A throwaway copy of the repo's deploy/ scripts, with fake docker and sudo first on the PATH."""
    (tmp_path / "deploy").mkdir()
    for name in SCRIPTS:
        shutil.copy(REPO_ROOT / "deploy" / name, tmp_path / "deploy" / name)
    (tmp_path / ".env.prod").write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(DOCKER_SHIM)
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    for shim in bin_dir.iterdir():
        shim.chmod(0o755)
    (tmp_path / "state").mkdir()
    return tmp_path


def run(sandbox, script, **env):
    full_env = {**os.environ, "PATH": f"{sandbox / 'bin'}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(sandbox / "state")}
    full_env.update(env)
    # The arguments are fixed by this test, not user input.
    return subprocess.run(  # noqa: S603
        [SH, str(sandbox / "deploy" / script)], cwd=sandbox, env=full_env, capture_output=True, text=True, timeout=60
    )


def uploaded(sandbox):
    return (sandbox / "state" / "uploaded").exists()


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_script_parses(script):
    result = subprocess.run([SH, "-n", str(REPO_ROOT / "deploy" / script)], capture_output=True, text=True)  # noqa: S603

    assert result.returncode == 0, result.stderr


def test_a_good_dump_is_checked_uploaded_and_reported(sandbox):
    result = run(sandbox, "backup.sh")

    assert result.returncode == 0, result.stderr
    match = re.search(r"^backup ok: (daily/\d{4}/\d{2}/\d{2}/autoca-\d{8}T\d{6}Z\.dump) \(30000 bytes\)$", result.stdout, re.M)
    assert match, result.stdout
    assert (sandbox / "state" / "key").read_text().strip() == match.group(1)
    assert (sandbox / "state" / "uploaded").stat().st_size == 30000


def test_a_dump_too_small_to_be_real_is_refused_and_nothing_is_uploaded(sandbox):
    result = run(sandbox, "backup.sh", FAKE_DUMP_BYTES="100")

    assert result.returncode == 1
    assert "only 100 bytes" in result.stderr
    assert not uploaded(sandbox)


def test_a_dump_that_cannot_be_read_back_is_never_uploaded(sandbox):
    result = run(sandbox, "backup.sh", FAKE_LIST_FAIL="1")

    assert result.returncode == 1
    assert "cannot read the dump" in result.stderr
    assert not uploaded(sandbox)


def test_a_dump_with_no_table_data_is_never_uploaded(sandbox):
    result = run(sandbox, "backup.sh", FAKE_NO_TABLES="1")

    assert result.returncode == 1
    assert "no table data" in result.stderr
    assert not uploaded(sandbox)


def test_a_failed_pg_dump_stops_the_job(sandbox):
    result = run(sandbox, "backup.sh", FAKE_DUMP_FAIL="1")

    assert result.returncode == 1
    assert "pg_dump did not finish" in result.stderr
    assert not uploaded(sandbox)


def test_an_upload_that_s3_holds_incompletely_fails(sandbox):
    result = run(sandbox, "backup.sh", FAKE_STORED="29999")

    assert result.returncode == 1
    assert "S3 holds 29999 bytes but the dump is 30000" in result.stderr
    assert "backup ok" not in result.stdout


def test_status_is_ok_when_the_newest_backup_is_recent(sandbox):
    result = run(sandbox, "backup-status.sh")

    assert result.returncode == 0, result.stderr
    assert "OK: the newest backup is 3.0 hours old" in result.stdout


def test_status_warns_when_the_newest_backup_is_over_26_hours_old(sandbox):
    result = run(sandbox, "backup-status.sh", FAKE_LATEST="daily/old.dump 30.5h 99")

    assert result.returncode == 1
    assert "30.5 hours old" in result.stderr


def test_status_warns_when_there_are_no_backups_at_all(sandbox):
    result = run(sandbox, "backup-status.sh", FAKE_LATEST_FAIL="1")

    assert result.returncode == 1
    assert "no backups at all" in result.stderr
