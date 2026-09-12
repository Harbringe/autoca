"""Cross-tenant isolation suite. This is a release gate, not a nice-to-have.

The suite has three layers:

1.  **Structural** -- every firm-scoped table really has ENABLE, FORCE, and a
    tenant policy in the live database. Discovered by enumerating
    ``FirmScopedModel`` subclasses, so it covers tables that do not exist yet.

2.  **Coverage** -- every firm-scoped model has a factory. This is the mechanism
    that makes the suite grow with the schema: add a model, and CI fails until
    you have said how to build one, at which point layer 3 starts attacking it.

3.  **Behavioural** -- with firm A's context active, attempt to read, write,
    update, and delete firm B's rows, and assert that none of it works.

There are only a handful of tables today. That is exactly when to prove the
pattern and wire the gate -- before there is real client data to leak.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import DatabaseError, connection
from django.db.utils import InternalError, ProgrammingError

from core.db.introspect import (
    firm_scoped_models,
    firm_scoped_tables,
    models_with_firm_fk_not_scoped,
    rls_state,
)
from core.db.session import TenantContextError, firm_context, no_firm_context
from core.models import Client, Firm, FirmMembership
from core.provisioning import create_firm
from core.tests.factories import FACTORIES

pytestmark = pytest.mark.django_db

# Postgres raises insufficient_privilege (42501) from our guard function; the
# psycopg/Django wrapper surfaces it as one of these.
DENIED = (InternalError, ProgrammingError, DatabaseError)


@pytest.fixture
def firm_a():
    return create_firm("Firm A")


@pytest.fixture
def firm_b():
    return create_firm("Firm B")


# ---------------------------------------------------------------------------
# Layer 1: structural
# ---------------------------------------------------------------------------


def test_every_firm_scoped_table_is_protected():
    """ENABLE + FORCE + at least one policy, for every scoped table."""
    problems = []
    for table in sorted(firm_scoped_tables()):
        state = rls_state(table)
        if state is None:
            problems.append(f"{table}: no such table")
            continue
        enabled, forced, policies = state
        if not enabled:
            problems.append(f"{table}: row level security is not ENABLEd")
        if not forced:
            problems.append(
                f"{table}: FORCE is off, so the table owner bypasses the policy"
            )
        if not policies:
            problems.append(f"{table}: no policy defined")
    assert not problems, "Unprotected firm-scoped tables:\n  " + "\n  ".join(problems)


def test_policies_reference_the_guard_function():
    """A policy that does not consult the tenant context is not isolation.

    Catches a policy that was created but written against something else --
    ``USING (true)`` being the memorable way to get this wrong.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, p.polname,
                   pg_get_expr(p.polqual, p.polrelid),
                   pg_get_expr(p.polwithcheck, p.polrelid)
            FROM pg_policy p
            JOIN pg_class c ON c.oid = p.polrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
            """
        )
        rows = cursor.fetchall()

    scoped = firm_scoped_tables()
    seen = set()
    problems = []
    for table, policy, using_expr, check_expr in rows:
        if table not in scoped:
            continue
        seen.add(table)
        combined = f"{using_expr or ''} {check_expr or ''}"
        if "current_firm_id" not in combined and "membership_visible" not in combined:
            problems.append(f"{table}.{policy}: USING/WITH CHECK ignores the tenant context")

    assert not problems, "\n".join(problems)
    assert seen == scoped, f"Tables with no policy at all: {sorted(scoped - seen)}"


def test_no_model_smuggles_a_firm_fk_without_the_base_class():
    """A firm FK without ``FirmScopedModel`` gets no policy and no test."""
    offenders = [m._meta.label for m in models_with_firm_fk_not_scoped()]
    assert not offenders, (
        "These models reference Firm but do not subclass FirmScopedModel, so they "
        "are invisible to RLS enrolment and to this suite: " + ", ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Layer 2: coverage
# ---------------------------------------------------------------------------


def test_every_firm_scoped_model_has_a_factory():
    missing = [m._meta.label for m in firm_scoped_models() if m not in FACTORIES]
    assert not missing, (
        "Add a factory in core/tests/factories.py for: " + ", ".join(missing) + ". "
        "Until you do, these tables are not being attacked by the isolation suite."
    )


# ---------------------------------------------------------------------------
# Layer 3: behavioural
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", firm_scoped_models(), ids=lambda m: m._meta.label)
def test_rows_are_invisible_to_another_firm(model, firm_a, firm_b):
    factory = FACTORIES[model]

    with firm_context(firm_a.pk):
        row = factory(firm_a)
        assert model.objects.filter(pk=row.pk).exists()

    with firm_context(firm_b.pk):
        assert not model.objects.filter(pk=row.pk).exists()
        assert model.objects.count() == 0


@pytest.mark.parametrize("model", firm_scoped_models(), ids=lambda m: m._meta.label)
def test_rows_cannot_be_updated_by_another_firm(model, firm_a, firm_b):
    factory = FACTORIES[model]
    with firm_context(firm_a.pk):
        row = factory(firm_a)

    with firm_context(firm_b.pk):
        # The row is not visible, so the UPDATE matches nothing. The important
        # assertion is that it does not raise *and* changes nothing -- a silent
        # zero-row update is the correct outcome here.
        assert model.objects.filter(pk=row.pk).update(**_touch(model)) == 0

    with firm_context(firm_a.pk):
        assert model.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("model", firm_scoped_models(), ids=lambda m: m._meta.label)
def test_rows_cannot_be_deleted_by_another_firm(model, firm_a, firm_b):
    factory = FACTORIES[model]
    with firm_context(firm_a.pk):
        row = factory(firm_a)

    with firm_context(firm_b.pk):
        deleted, _ = model.objects.filter(pk=row.pk).delete()
        assert deleted == 0

    with firm_context(firm_a.pk):
        assert model.objects.filter(pk=row.pk).exists()


def test_insert_for_another_firm_is_rejected(firm_a, firm_b):
    """WITH CHECK: firm B's context cannot mint a row belonging to firm A."""
    with pytest.raises(DENIED):
        with firm_context(firm_b.pk):
            Client.objects.create(firm=firm_a, name="Smuggled", fy_start="2026-04-01")


def test_row_cannot_be_moved_to_another_firm(firm_a, firm_b):
    """WITH CHECK also blocks re-parenting a row you legitimately own."""
    with firm_context(firm_a.pk):
        client = Client.objects.create(firm=firm_a, name="Real", fy_start="2026-04-01")

    with pytest.raises(DENIED):
        with firm_context(firm_a.pk):
            Client.objects.filter(pk=client.pk).update(firm_id=firm_b.pk)


def test_firm_sees_only_itself(firm_a, firm_b):
    with firm_context(firm_a.pk):
        assert list(Firm.objects.values_list("pk", flat=True)) == [firm_a.pk]
    with firm_context(firm_b.pk):
        assert list(Firm.objects.values_list("pk", flat=True)) == [firm_b.pk]


# ---------------------------------------------------------------------------
# Deny by default
# ---------------------------------------------------------------------------


def test_query_without_tenant_context_raises_loudly(firm_a):
    """The requirement: unset context must fail, never return everything."""
    with firm_context(firm_a.pk):
        Client.objects.create(firm=firm_a, name="Real", fy_start="2026-04-01")

    with pytest.raises(DENIED) as excinfo:
        with no_firm_context():
            list(Client.objects.all())

    assert "tenant context missing" in str(excinfo.value).lower()


def test_unset_context_does_not_return_rows_silently(firm_a):
    """Belt and braces: assert the failure is not an empty result set."""
    with firm_context(firm_a.pk):
        Client.objects.create(firm=firm_a, name="Real", fy_start="2026-04-01")

    with pytest.raises(DENIED):
        with no_firm_context():
            Client.objects.count()


def test_garbage_firm_id_is_rejected():
    with pytest.raises(TenantContextError):
        with firm_context("not-a-uuid"):
            pass


def test_context_cannot_be_switched_mid_transaction(firm_a, firm_b):
    with pytest.raises(TenantContextError):
        with firm_context(firm_a.pk):
            with firm_context(firm_b.pk):
                pass


def test_context_does_not_survive_its_transaction(firm_a):
    """The pooler-safety property: SET LOCAL, never SET.

    If this ever fails, one firm's context is outliving its transaction and can
    be inherited by the next request to reuse the connection. That is the single
    worst failure this codebase can have.
    """
    from core.db.session import get_current_firm_id

    with firm_context(firm_a.pk):
        assert get_current_firm_id() == str(firm_a.pk)

    assert not get_current_firm_id()


# ---------------------------------------------------------------------------
# The membership bootstrap, which is the one place with a widened predicate
# ---------------------------------------------------------------------------


def test_membership_bootstrap_reveals_only_your_own_rows(firm_a, firm_b):
    from core.db.session import user_context
    from core.provisioning import add_member, create_user

    alice = create_user("alice@example.com", "correct-horse-battery")
    bob = create_user("bob@example.com", "correct-horse-battery")
    add_member(firm_a, alice)
    add_member(firm_b, bob)

    with user_context(alice.pk):
        rows = list(FirmMembership.objects.all())
        assert [r.user_id for r in rows] == [alice.pk]
        assert rows[0].firm_id == firm_a.pk


def test_membership_bootstrap_cannot_create_a_membership(firm_a):
    """Discovering your membership must not be a route to granting one."""
    from core.db.session import user_context
    from core.provisioning import create_user

    mallory = create_user("mallory@example.com", "correct-horse-battery")

    with pytest.raises(DENIED):
        with user_context(mallory.pk):
            FirmMembership.objects.create(firm_id=firm_a.pk, user=mallory)


def test_no_context_at_all_still_denies_membership_reads(firm_a):
    """The widened membership predicate must still refuse with no context set.

    Note the fixture: there has to be a row present for this to prove anything.
    An RLS predicate is evaluated per candidate row, so against an empty table
    Postgres never calls ``app.membership_visible`` and the query returns an
    empty set rather than raising. An earlier version of this test had no data
    and passed while asserting nothing.
    """
    from core.provisioning import add_member, create_user

    add_member(firm_a, create_user("nocontext@example.com", "correct-horse-battery"))

    with pytest.raises(DENIED) as excinfo:
        with no_firm_context():
            list(FirmMembership.objects.all())

    assert "tenant context missing" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Role privileges
# ---------------------------------------------------------------------------


def test_connection_role_cannot_bypass_rls():
    """Whatever role the suite runs as, it must not be exempt from policies.

    If CI ever runs as a superuser, every isolation assertion above becomes
    vacuously true while appearing to pass. This test is what stops that.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        is_super, can_bypass = cursor.fetchone()

    assert not is_super, (
        "The test database role is a superuser, which bypasses every RLS policy. "
        "The isolation suite would pass without proving anything."
    )
    assert not can_bypass, "The test database role has BYPASSRLS."


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _touch(model) -> dict:
    """A harmless field update appropriate to ``model``."""
    names = {f.name for f in model._meta.fields}
    for candidate, value in (
        ("name", f"tampered-{uuid.uuid4().hex[:6]}"),
        ("path", "/tampered/"),
        ("role", "SENIOR_CA"),
        ("is_active", False),
        ("original_filename", "tampered.pdf"),
        ("narration", "tampered"),
        ("parser", "TAMPERED"),
        ("pattern", "TAMPERED"),
        ("canonical_name", "TAMPERED"),
        ("counterparty", "TAMPERED"),
        ("next_number", 999),
        ("tds_section", "194C"),
    ):
        if candidate in names:
            return {candidate: value}
    raise AssertionError(
        f"{model._meta.label} has no field _touch() knows how to modify. Add one "
        f"to the list above so the cross-tenant update test stays meaningful."
    )
