"""The team, firm and owner replies are described in the API schema, and the description matches the replies."""

from __future__ import annotations

import pytest

from api.tests.conftest import sign_in
from teams import schemas
from teams.tests.test_team import TEAM, V1, _lead_client, _on_team, admin, lead  # noqa: F401

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def _keys(serializer_class) -> set:
    return set(serializer_class().fields)


def test_the_schema_types_every_team_firm_and_owner_reply():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]

    def ref(path, method, status="200"):
        content = paths[path][method]["responses"][status].get("content", {})
        return content.get("application/json", {}).get("schema", {}).get("$ref", "")

    assert ref("/api/v1/team/members/", "get").endswith("/MembersResponse")
    assert ref("/api/v1/team/members/", "post", "201").endswith("/InviteCreated")
    assert ref("/api/v1/team/members/{id}/", "get").endswith("/Member")
    assert ref("/api/v1/team/members/{id}/work/", "get").endswith("/MemberWorkResponse")
    assert ref("/api/v1/team/clients/", "get").endswith("/TeamClientsResponse")
    assert ref("/api/v1/team/events/", "get").endswith("/TeamEventsResponse")
    assert ref("/api/v1/firm/", "get").endswith("/FirmResponse")
    assert ref("/api/v1/firm/owner/", "post").endswith("/OwnerTransferred")
    detail = schema["components"]["schemas"]["TeamEventDetail"]
    assert {"actor", "member", "client", "from", "to"} <= set(detail["properties"])


def test_the_described_shapes_are_the_shapes_returned(client_record, admin, lead):
    _lead_client(client_record, lead)
    _on_team(client_record.firm, lead, "clerk@example.test")
    http = sign_in(admin.user)

    members = http.get(f"{TEAM}/members/").json()
    assert set(members) == _keys(schemas.MembersResponseSerializer)
    assert set(members["results"][0]) == _keys(schemas.MemberWithWorkSerializer)
    assert set(members["results"][0]["work"]) == _keys(schemas.WorkTotalsSerializer)
    assert set(members["can"]) == _keys(schemas.MembersCanSerializer)
    assert set(members["metrics"][0]) == _keys(schemas.MetricSerializer)
    assert set(members["leads"][0]) == _keys(schemas.PersonSerializer)

    work = http.get(f"{TEAM}/members/{lead.pk}/work/").json()
    assert set(work) == _keys(schemas.MemberWorkResponseSerializer)
    assert set(work["open_work"][0]) == _keys(schemas.OpenWorkSerializer)

    clients = http.get(f"{TEAM}/clients/").json()
    assert set(clients) == _keys(schemas.TeamClientsResponseSerializer)
    assert set(clients["results"][0]) == _keys(schemas.TeamClientSerializer)

    firm = http.get(f"{V1}/firm/").json()
    assert set(firm) == _keys(schemas.FirmResponseSerializer)
    assert set(firm["counts"]) == _keys(schemas.FirmCountsSerializer)

    invited = http.post(f"{TEAM}/members/", {"email": "n@example.test", "role": "STAFF", "manager": str(lead.pk)}, format="json").json()
    events = http.get(f"{TEAM}/events/").json()
    assert set(events["results"][0]) == _keys(schemas.TeamEventSerializer)
    assert set(events["results"][0]["detail"]) <= set(schemas.TeamEventDetailSerializer().fields) | {"from"}

    assert set(invited) == _keys(schemas.InviteCreatedSerializer)
    assert set(http.get(f"{TEAM}/invites/").json()["results"][0]) == _keys(schemas.InviteRecordSerializer)
