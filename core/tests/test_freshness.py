"""The few seconds' memory for the overview and alerts, and the middleware that makes it forget after a person's change. No database."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core import freshness
from core.middleware.freshness import FreshnessMiddleware


@pytest.fixture(autouse=True)
def sharing_on(settings, monkeypatch):
    settings.FRESHNESS_TTL = 10
    # Without a database there is no transaction to wait for; the commit is "now". (The test against the real database is in api/tests.)
    monkeypatch.setattr("core.middleware.freshness.transaction.on_commit", lambda fn: fn())


def counter():
    calls = []

    def compute():
        calls.append(1)
        return {"n": len(calls)}

    return calls, compute


def test_the_same_question_is_worked_out_once_and_shared():
    calls, compute = counter()
    first = freshness.remember("firm-a", "overview", ["m1"], compute)
    second = freshness.remember("firm-a", "overview", ["m1"], compute)
    assert first == second == {"n": 1} and len(calls) == 1


def test_a_different_person_or_name_or_firm_is_a_different_answer():
    calls, compute = counter()
    freshness.remember("firm-a", "overview", ["m1"], compute)
    freshness.remember("firm-a", "overview", ["m2"], compute)  # another person
    freshness.remember("firm-a", "alerts", ["m1"], compute)  # another question
    freshness.remember("firm-b", "overview", ["m1"], compute)  # another firm
    assert len(calls) == 4


def test_a_change_makes_everything_remembered_for_that_firm_unreadable_and_no_other_firm():
    calls, compute = counter()
    freshness.remember("firm-a", "overview", ["m1"], compute)
    freshness.remember("firm-b", "overview", ["m1"], compute)
    freshness.bump("firm-a")
    again_a = freshness.remember("firm-a", "overview", ["m1"], compute)
    again_b = freshness.remember("firm-b", "overview", ["m1"], compute)
    assert len(calls) == 3  # firm-a worked out again, firm-b still shared
    assert again_a == {"n": 3} and again_b == {"n": 2}
    freshness.bump("firm-a")
    freshness.bump("firm-a")
    assert freshness.version("firm-a") >= 3


def test_nothing_is_shared_when_the_setting_is_zero(settings):
    settings.FRESHNESS_TTL = 0
    calls, compute = counter()
    freshness.remember("firm-a", "overview", ["m1"], compute)
    freshness.remember("firm-a", "overview", ["m1"], compute)
    assert len(calls) == 2


def test_a_failure_leaves_nothing_remembered_and_the_next_try_works():
    state = {"fail": True}

    def compute():
        if state["fail"]:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        freshness.remember("firm-a", "overview", ["m1"], compute)
    state["fail"] = False
    assert freshness.remember("firm-a", "overview", ["m1"], compute) == "ok"


def test_requests_that_arrive_together_cost_one_computation():
    calls = []
    gate = threading.Event()

    def slow():
        calls.append(1)
        gate.wait(5)
        return "shared"

    results = []
    threads = [threading.Thread(target=lambda: results.append(freshness.remember("firm-a", "overview", ["m1"], slow))) for _ in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.3)  # all five are asking; one is working, four are waiting for it
    gate.set()
    for t in threads:
        t.join(10)
    assert results == ["shared"] * 5 and len(calls) == 1


def test_a_waiter_does_not_wait_out_the_clock_when_the_other_request_failed():
    started = time.monotonic()
    holder_in = threading.Event()
    release = threading.Event()

    def failing():
        holder_in.set()
        release.wait(5)
        raise RuntimeError("boom")

    outcome = []

    def holder():
        try:
            freshness.remember("firm-a", "overview", ["m1"], failing)
        except RuntimeError:
            outcome.append("holder failed")

    t = threading.Thread(target=holder)
    t.start()
    holder_in.wait(5)
    threading.Timer(0.3, release.set).start()
    assert freshness.remember("firm-a", "overview", ["m1"], lambda: "worked out itself") == "worked out itself"
    t.join(5)
    assert outcome == ["holder failed"] and time.monotonic() - started < 4  # nowhere near the 8 s wait


def _after(method, path, status=200, firm="firm-a"):
    request = getattr(RequestFactory(), method.lower())(path)
    if firm is not None:
        request.firm = SimpleNamespace(pk=firm)
    FreshnessMiddleware(lambda r: HttpResponse(status=status))(request)


def test_a_successful_change_through_the_api_moves_the_firms_version_on():
    before = freshness.version("firm-m")
    _after("POST", "/api/v1/clients/", firm="firm-m")
    assert freshness.version("firm-m") == before + 1
    for method in ("PUT", "PATCH", "DELETE"):
        _after(method, "/api/v1/clients/x/", firm="firm-m")
    assert freshness.version("firm-m") == before + 4


def test_reads_failures_other_paths_and_anonymous_requests_change_nothing():
    before = freshness.version("firm-n")
    _after("GET", "/api/v1/clients/", firm="firm-n")
    _after("POST", "/api/v1/clients/", status=400, firm="firm-n")
    _after("POST", "/api/v1/clients/", status=500, firm="firm-n")
    _after("POST", "/auth/login/", firm="firm-n")
    _after("POST", "/api/v1/clients/", firm=None)
    assert freshness.version("firm-n") == before


def test_a_change_under_one_client_forgets_that_clients_results_and_not_the_others():
    a, b = "client-a", "client-b"
    calls_a, compute_a = counter()
    calls_b, compute_b = counter()
    freshness.remember("firm-c", "detail", [a], compute_a, ttl=60, client_id=a)
    freshness.remember("firm-c", "detail", [b], compute_b, ttl=60, client_id=b)
    freshness.bump("firm-c", a)
    freshness.remember("firm-c", "detail", [a], compute_a, ttl=60, client_id=a)
    freshness.remember("firm-c", "detail", [b], compute_b, ttl=60, client_id=b)
    assert len(calls_a) == 2 and len(calls_b) == 1  # a was worked out again; b's was kept


def test_a_change_under_a_client_still_forgets_what_spans_clients():
    calls, compute = counter()
    freshness.remember("firm-d", "overview", ["m1"], compute)
    freshness.bump("firm-d", "client-a")
    freshness.remember("firm-d", "overview", ["m1"], compute)
    assert len(calls) == 2


def test_a_firm_level_change_forgets_every_clients_results():
    calls_a, compute_a = counter()
    calls_b, compute_b = counter()
    freshness.remember("firm-e", "detail", ["a"], compute_a, ttl=60, client_id="client-a")
    freshness.remember("firm-e", "detail", ["b"], compute_b, ttl=60, client_id="client-b")
    freshness.bump("firm-e")  # the team, a new client: not under any one client
    freshness.remember("firm-e", "detail", ["a"], compute_a, ttl=60, client_id="client-a")
    freshness.remember("firm-e", "detail", ["b"], compute_b, ttl=60, client_id="client-b")
    assert len(calls_a) == 2 and len(calls_b) == 2


def test_the_middleware_reads_the_client_from_the_address_and_moves_only_that_clients_version():
    cid = "11111111-2222-3333-4444-555555555555"
    other = "99999999-2222-3333-4444-555555555555"
    calls, compute = counter()
    calls_other, compute_other = counter()
    freshness.remember("firm-f", "detail", [cid], compute, ttl=60, client_id=cid)
    freshness.remember("firm-f", "detail", [other], compute_other, ttl=60, client_id=other)
    _after("POST", f"/api/v1/clients/{cid.upper()}/assistant/pause/", firm="firm-f")  # an upper-case address is the same client
    freshness.remember("firm-f", "detail", [cid], compute, ttl=60, client_id=cid)
    freshness.remember("firm-f", "detail", [other], compute_other, ttl=60, client_id=other)
    assert len(calls) == 2 and len(calls_other) == 1


def test_a_change_that_is_not_under_a_client_moves_the_structural_version():
    cid = "11111111-2222-3333-4444-555555555555"
    calls, compute = counter()
    freshness.remember("firm-g", "detail", [cid], compute, ttl=60, client_id=cid)
    _after("POST", "/api/v1/clients/", firm="firm-g")  # creating a client: nothing in the address names one
    freshness.remember("firm-g", "detail", [cid], compute, ttl=60, client_id=cid)
    assert len(calls) == 2
