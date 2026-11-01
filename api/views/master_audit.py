"""A viewset mixin that writes a master change for every create, edit and removal that goes through."""

from __future__ import annotations

from ledger.audit import record_master_change, snapshot


class MasterAuditMixin:
    """Put first in a client-scoped viewset's bases. Names ``audit_kind``, ``audit_fields`` and ``audit_label(obj)``."""

    audit_kind: str
    audit_fields: tuple[str, ...]

    def audit_label(self, obj) -> str:
        return str(obj)

    def _audit(self, action: str, obj_id, label: str, before: dict, after: dict) -> None:
        record_master_change(
            self.client, self.audit_kind, obj_id, action, label=label, before=before, after=after, actor=self.request.user
        )

    def audit_created(self, obj) -> None:
        self._audit("CREATED", obj.pk, self.audit_label(obj), {}, snapshot(obj, self.audit_fields))

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self.audit_created(serializer.instance)

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, self.audit_fields)
        super().perform_update(serializer)
        obj = serializer.instance
        self._audit("EDITED", obj.pk, self.audit_label(obj), before, snapshot(obj, self.audit_fields))

    def perform_destroy(self, instance):
        before, label, pk = snapshot(instance, self.audit_fields), self.audit_label(instance), instance.pk
        super().perform_destroy(instance)
        self._audit("REMOVED", pk, label, before, {})
