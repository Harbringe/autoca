"""An S3 deployment on AWS carries no access keys: the instance's role signs the requests.

That only works if the adapter hands boto3 ``None``, not an empty string. boto3 treats an empty
string as an explicit credential, so a settings file with ``STORAGE_ACCESS_KEY_ID=`` would make
every file operation fail with a signature error.
"""

from __future__ import annotations

import boto3
import pytest

from integrations.storage.s3 import S3StorageAdapter


@pytest.fixture
def built_with(monkeypatch):
    seen = {}

    def fake_client(service, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(boto3, "client", fake_client)
    return seen


@pytest.mark.parametrize("empty", [None, ""])
def test_unset_or_empty_keys_leave_boto3_to_use_the_instance_role(built_with, empty):
    adapter = S3StorageAdapter(bucket="b", region="ap-south-1", access_key_id=empty, secret_access_key=empty)

    adapter.client

    assert built_with["aws_access_key_id"] is None
    assert built_with["aws_secret_access_key"] is None
    assert built_with["region_name"] == "ap-south-1"


def test_explicit_keys_are_still_passed_through(built_with):
    adapter = S3StorageAdapter(bucket="b", region="ap-south-1", access_key_id="AKIA-X", secret_access_key="s")

    adapter.client

    assert built_with["aws_access_key_id"] == "AKIA-X"
    assert built_with["aws_secret_access_key"] == "s"
