"""The backup tool: it must put, find the newest, and raise the alarm when there is none or it is stale.

S3 and CloudWatch are replaced by small fakes: what is under test is the tool's logic and the exact calls it
makes (encryption on upload, the metric's name and value), not Amazon.
"""

from __future__ import annotations

import datetime
import io

import pytest

from integrations.backup import s3 as backup

UTC = datetime.UTC
NOW = datetime.datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def obj(key, hours_old, size=1000):
    return {"Key": key, "Size": size, "LastModified": NOW - datetime.timedelta(hours=hours_old)}


class FakeS3:
    def __init__(self, objects=()):
        self.objects = list(objects)
        self.uploads = []
        self.downloads = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        outer = self

        class Paginator:
            def paginate(self, Bucket, Prefix):  # noqa: N803 -- boto3's own parameter names
                items = [o for o in outer.objects if o["Key"].startswith(Prefix)]
                # two pages, to prove the tool follows them
                yield {"Contents": items[:1]}
                yield {"Contents": items[1:]}
                yield {}

        return Paginator()

    def upload_fileobj(self, stream, bucket, key, ExtraArgs):  # noqa: N803
        data = stream.read()
        self.uploads.append((bucket, key, data, ExtraArgs))
        self.objects.append({"Key": key, "Size": len(data), "LastModified": NOW})

    def head_object(self, Bucket, Key):  # noqa: N803
        # The server holds no read permission on the bucket, so the tool must never ask.
        raise AssertionError("put must not need s3:GetObject")

    def download_fileobj(self, bucket, key, out):
        self.downloads.append((bucket, key))
        out.write(b"PGDMP-contents")


class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


def test_the_newest_backup_wins_whatever_the_order():
    objects = [obj("daily/a", 30), obj("daily/b", 2), obj("daily/c", 55)]

    assert backup.pick_latest(objects)["Key"] == "daily/b"
    assert backup.pick_latest([]) is None


def test_age_is_in_hours_and_never_negative():
    assert backup.age_hours(NOW, NOW - datetime.timedelta(hours=26, minutes=30)) == pytest.approx(26.5)
    assert backup.age_hours(NOW, NOW + datetime.timedelta(minutes=5)) == 0.0   # a clock a little ahead


def test_listing_follows_every_page_and_only_the_daily_prefix():
    client = FakeS3([obj("daily/a", 1), obj("daily/b", 2), obj("other/x", 3)])

    keys = [o["Key"] for o in backup.list_objects(client, "bkt")]

    assert keys == ["daily/a", "daily/b"]


def test_an_upload_is_encrypted_and_reports_the_size_s3_holds():
    client = FakeS3()

    size = backup.put(client, "bkt", "daily/2026/10/05/x.dump", io.BytesIO(b"x" * 321))

    assert size == 321
    bucket, key, data, extra = client.uploads[0]
    assert (bucket, key, len(data)) == ("bkt", "daily/2026/10/05/x.dump", 321)
    assert extra == {"ServerSideEncryption": "AES256"}


def test_a_refused_read_explains_the_temporary_policy_instead_of_a_stack_trace():
    from botocore.exceptions import ClientError

    class Denied(FakeS3):
        def download_fileobj(self, bucket, key, out):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")

    with pytest.raises(SystemExit, match="autoca-backups-restore"):
        backup.get(Denied(), "bkt", "daily/k", io.BytesIO())


def test_download_streams_to_the_destination():
    client, out = FakeS3(), io.BytesIO()

    backup.get(client, "bkt", "daily/k", out)

    assert out.getvalue() == b"PGDMP-contents" and client.downloads == [("bkt", "daily/k")]


def test_no_backup_at_all_reads_as_a_very_old_one_not_as_missing_data():
    newest, hours = backup.newest_age(FakeS3(), "bkt", NOW)

    assert newest is None and hours == backup.NO_BACKUP_AGE_HOURS


def test_the_published_metric_is_the_age_the_alarm_watches():
    cw = FakeCloudWatch()

    backup.publish_age(cw, 3.25)

    assert cw.calls == [
        {"Namespace": "Autoca/Backup", "MetricData": [{"MetricName": "BackupAgeHours", "Value": 3.25, "Unit": "None"}]}
    ]


def test_the_cli_needs_a_bucket(monkeypatch):
    monkeypatch.delenv("BACKUP_BUCKET", raising=False)

    with pytest.raises(SystemExit, match="BACKUP_BUCKET"):
        backup.main(["latest"])


def test_the_cli_latest_prints_key_age_and_size_and_fails_when_empty(monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_BUCKET", "bkt")
    monkeypatch.setattr(backup, "_now", lambda: NOW)
    client = FakeS3([obj("daily/old", 40, 5), obj("daily/new", 3, 777)])
    monkeypatch.setattr(backup, "_client", lambda service: client)

    assert backup.main(["latest"]) == 0
    assert capsys.readouterr().out.strip() == "daily/new 3.0h 777"

    monkeypatch.setattr(backup, "_client", lambda service: FakeS3())
    assert backup.main(["latest"]) == 1


def test_the_cli_age_metric_publishes_the_real_age(monkeypatch, capsys):
    monkeypatch.setenv("BACKUP_BUCKET", "bkt")
    monkeypatch.setattr(backup, "_now", lambda: NOW)
    cw = FakeCloudWatch()
    clients = {"s3": FakeS3([obj("daily/new", 7.5)]), "cloudwatch": cw}
    monkeypatch.setattr(backup, "_client", lambda service: clients[service])

    assert backup.main(["age-metric"]) == 0

    assert cw.calls[0]["MetricData"][0]["Value"] == pytest.approx(7.5)
    assert "BackupAgeHours=7.5" in capsys.readouterr().out
