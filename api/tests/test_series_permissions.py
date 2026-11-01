"""Who may change a client's voucher series, formats and classes, and who may only read the audit trail."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from core.models import Role

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


@pytest.fixture
def reader(firm, client_record):
    return sign_in(member(firm, Role.READ_ONLY, "reader@example.test").user)


def test_a_read_only_person_may_read_the_series_formats_and_trail(reader, client_record):
    base = f"{V1}/clients/{client_record.pk}"
    for path in ("numbering/", "voucher-types/", "voucher-classes/", "audit-trail/"):
        assert reader.get(f"{base}/{path}").status_code == 200, path


def test_a_read_only_person_may_not_change_them(reader, client_record):
    base = f"{V1}/clients/{client_record.pk}"
    assert reader.put(f"{base}/numbering/", [{"voucher_type": "Sales", "type_name": "", "prefix": "S", "padding": 2}], format="json").status_code == 403
    assert reader.post(f"{base}/voucher-types/", {"name": "GST SALE", "parent": "Sales"}, format="json").status_code == 403
    assert reader.post(f"{base}/voucher-classes/", {"name": "X", "voucher_type": "Sales", "head_ledger": "00000000-0000-0000-0000-000000000000"}, format="json").status_code == 403


def test_a_person_outside_the_firm_sees_none_of_it(firm, client_record):
    from core.provisioning import create_firm

    other_firm = create_firm("Other Firm")
    outsider = sign_in(member(other_firm, Role.SENIOR_CA, "outsider@example.test").user)
    base = f"{V1}/clients/{client_record.pk}"
    for path in ("numbering/", "voucher-types/", "voucher-classes/", "audit-trail/"):
        assert outsider.get(f"{base}/{path}").status_code == 404, path
