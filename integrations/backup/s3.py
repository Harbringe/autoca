"""The backup tool: put, get, list and measure database dumps kept in S3.

Run inside the web container, where the instance's IAM role signs the requests (no keys anywhere):

    python -m integrations.backup.s3 put daily/2026/10/05/autoca-....dump  < dump      upload from stdin
    python -m integrations.backup.s3 get daily/2026/10/05/autoca-....dump  > dump      download to stdout
    python -m integrations.backup.s3 latest                                           newest backup and its age
    python -m integrations.backup.s3 list 10                                          the ten newest
    python -m integrations.backup.s3 age-metric                                       publish the age to CloudWatch

The bucket is ``BACKUP_BUCKET``. The server's standing permission is to put and list, never to read or delete: the
web container shares the instance role, so anything on the role is reachable by the internet-facing process,
and a compromised web process must not be able to read every dump or erase them. The bucket is versioned, so
it cannot overwrite them either. ``get`` (restores and drills) needs a TEMPORARY read policy that an
administrator attaches to the role for the duration; see docs/AWS.md.

``age-metric`` is the dead man's switch. It publishes how many hours old the newest backup is, every half
hour. An alarm fires when that passes ~26 hours, and ALSO when the numbers stop arriving, which is what a
dead server looks like. Both are things a backup that merely logs "ok" cannot tell you.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

BUCKET_ENV = "BACKUP_BUCKET"
REGION_ENV = "BACKUP_REGION"
DEFAULT_REGION = "ap-south-1"
DEFAULT_PREFIX = "daily/"
METRIC_NAMESPACE = "Autoca/Backup"
METRIC_NAME = "BackupAgeHours"
#: Published when there is no backup at all, so "none" reads as a very old one instead of as missing data.
NO_BACKUP_AGE_HOURS = 9999.0


def bucket_name() -> str:
    name = os.environ.get(BUCKET_ENV, "").strip()
    if not name:
        raise SystemExit(f"backup: {BUCKET_ENV} is not set (the name of the backups bucket)")
    return name


def _region() -> str:
    return os.environ.get(REGION_ENV, DEFAULT_REGION)


def _client(service: str):
    import boto3

    return boto3.client(service, region_name=_region())


def pick_latest(objects):
    """The newest object (by LastModified), or None."""
    return max(objects, key=lambda o: o["LastModified"], default=None)


def age_hours(now: datetime.datetime, last_modified: datetime.datetime) -> float:
    return max((now - last_modified).total_seconds() / 3600.0, 0.0)


def list_objects(client, bucket: str, prefix: str = DEFAULT_PREFIX) -> list[dict]:
    found: list[dict] = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        found.extend(page.get("Contents", []))
    return found


def put(client, bucket: str, key: str, stream) -> int:
    """Upload ``stream`` as ``key``, encrypted at rest, and return the size S3 reports back.

    The size is read from a listing, not a HEAD request: HEAD needs read permission, which the server
    deliberately does not hold on this bucket.
    """
    client.upload_fileobj(stream, bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})
    for obj in list_objects(client, bucket, key):
        if obj["Key"] == key:
            return int(obj["Size"])
    raise SystemExit(f"backup: {key} is not in the bucket after the upload")


def get(client, bucket: str, key: str, out) -> None:
    from botocore.exceptions import ClientError

    try:
        client.download_fileobj(bucket, key, out)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"AccessDenied", "403"}:
            raise SystemExit(
                "backup: the server's role may not read backups, by design. For a restore or a drill, attach the "
                "temporary policy autoca-backups-restore to the role, run it, then detach it (docs/AWS.md)."
            ) from exc
        raise


def newest_age(client, bucket: str, now: datetime.datetime) -> tuple[dict | None, float]:
    newest = pick_latest(list_objects(client, bucket))
    if newest is None:
        return None, NO_BACKUP_AGE_HOURS
    return newest, age_hours(now, newest["LastModified"])


def publish_age(cloudwatch, hours: float) -> None:
    cloudwatch.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{"MetricName": METRIC_NAME, "Value": float(hours), "Unit": "None"}],
    )


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="integrations.backup.s3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("put").add_argument("key")
    sub.add_parser("get").add_argument("key")
    sub.add_parser("latest")
    sub.add_parser("age-metric")
    listing = sub.add_parser("list")
    listing.add_argument("count", nargs="?", type=int, default=10)
    args = parser.parse_args(argv)

    bucket = bucket_name()

    if args.command == "put":
        size = put(_client("s3"), bucket, args.key, sys.stdin.buffer)
        print(size)
        return 0

    if args.command == "get":
        get(_client("s3"), bucket, args.key, sys.stdout.buffer)
        sys.stdout.buffer.flush()
        return 0

    s3 = _client("s3")
    now = _now()

    if args.command == "latest":
        newest, hours = newest_age(s3, bucket, now)
        if newest is None:
            print("no backups found", file=sys.stderr)
            return 1
        print(f"{newest['Key']} {hours:.1f}h {newest['Size']}")
        return 0

    if args.command == "list":
        objects = sorted(list_objects(s3, bucket), key=lambda o: o["LastModified"], reverse=True)
        for obj in objects[: args.count]:
            print(f"{obj['Key']} {age_hours(now, obj['LastModified']):.1f}h {obj['Size']}")
        if not objects:
            print("no backups found", file=sys.stderr)
            return 1
        return 0

    # age-metric
    _, hours = newest_age(s3, bucket, now)
    publish_age(_client("cloudwatch"), hours)
    print(f"published {METRIC_NAME}={hours:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
