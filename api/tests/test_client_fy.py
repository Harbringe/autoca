"""The financial year starts on 1 April: the books always run April to March (R1-33)."""

from __future__ import annotations

import pytest

from api.tests.conftest import member, sign_in
from core.db.session import firm_context
from core.models import Client, Role

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


@pytest.fixture
def admin_http(firm):
    return sign_in(member(firm, Role.FIRM_ADMIN, "fy-admin@example.test").user)


def test_a_new_client_must_start_its_year_on_1_april(admin_http):
    for start in ("2026-01-01", "2026-07-01", "2026-04-02"):
        response = admin_http.post(f"{V1}/clients/", {"name": f"Odd {start}", "fy_start": start}, format="json")
        assert response.status_code == 400, start
        assert "1 April" in str(response.json())

    ok = admin_http.post(f"{V1}/clients/", {"name": "April Client", "fy_start": "2026-04-01"}, format="json")
    assert ok.status_code == 201, ok.content


def test_editing_the_year_start_to_another_date_is_refused(admin_http, client_record):
    url = f"{V1}/clients/{client_record.pk}/"
    assert admin_http.patch(url, {"fy_start": "2026-01-01"}, format="json").status_code == 400
    assert admin_http.patch(url, {"fy_start": "2025-04-01"}, format="json").status_code == 200


def test_a_client_already_on_another_date_can_still_be_edited(admin_http, client_record, firm):
    import datetime

    with firm_context(firm.pk):
        Client.objects.filter(pk=client_record.pk).update(fy_start=datetime.date(2026, 1, 1))
    url = f"{V1}/clients/{client_record.pk}/"

    kept = admin_http.patch(url, {"name": "Renamed Client", "fy_start": "2026-01-01"}, format="json")
    assert kept.status_code == 200, kept.content
    assert admin_http.patch(url, {"fy_start": "2026-02-01"}, format="json").status_code == 400
