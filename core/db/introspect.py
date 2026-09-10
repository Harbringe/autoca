"""Discovery of firm-scoped models and their live RLS state.

The isolation test suite is built on this rather than on a hand-maintained list
of tables. That is the whole point: a list would go stale the first time someone
added a model in a hurry, and the failure mode of a stale list is a table with
no policy and no test -- silently. Enumerating ``FirmScopedModel`` subclasses
means the suite grows by itself, and a new table is covered the moment it exists.
"""

from __future__ import annotations

from django.apps import apps
from django.db import DEFAULT_DB_ALIAS, connections


def firm_scoped_models():
    """Every concrete model that declares itself firm-scoped."""
    from core.models import FirmScopedModel

    return [
        m
        for m in apps.get_models()
        if issubclass(m, FirmScopedModel) and not m._meta.abstract
    ]


def firm_scoped_tables() -> set[str]:
    tables = {m._meta.db_table for m in firm_scoped_models()}
    # The tenant root is scoped by its own primary key rather than a firm_id
    # column, so it does not subclass FirmScopedModel -- but it is absolutely
    # firm-scoped and must be covered.
    tables.add("core_firm")
    return tables


def models_with_firm_fk_not_scoped():
    """Models that have a ``firm`` relation but skipped the base class.

    This is the trap the suite is really watching for. Such a model looks
    tenant-aware to a reviewer, gets no RLS policy, and is invisible to any
    enumeration keyed on the base class.
    """
    from core.models import FirmScopedModel

    offenders = []
    for model in apps.get_models():
        if model._meta.abstract or issubclass(model, FirmScopedModel):
            continue
        for field in model._meta.get_fields():
            if getattr(field, "related_model", None) is not None:
                related = field.related_model
                if related is not None and related._meta.label == "core.Firm":
                    offenders.append(model)
                    break
    return offenders


def rls_state(table: str, using: str = DEFAULT_DB_ALIAS):
    """(enabled, forced, policy_count) as Postgres currently sees it."""
    with connections[using].cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relrowsecurity, c.relforcerowsecurity,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s
            """,
            [table],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return bool(row[0]), bool(row[1]), int(row[2])
