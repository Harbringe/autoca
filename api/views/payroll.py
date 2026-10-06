"""Employees, and booking a month of salaries."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.payroll import (
    EmployeeSerializer,
    PayrollRunCreateSerializer,
    PayrollRunSerializer,
)
from api.views.base import ClientScopedMixin
from ledger import payroll
from ledger.models import Employee, PayrollRun


@extend_schema(tags=["payroll"])
class EmployeeViewSet(
    ClientScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """The people the client pays a salary to. Each gets an account of their own on their first salary run."""

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve", "PATCH": "journal.approve", "PUT": "journal.approve"}
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return super().get_queryset().filter(firm_id=self.request.firm.pk)

    def create(self, request, *args, **kwargs):
        body = EmployeeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        made = payroll.add_employee(self.client, body.validated_data["name"], membership=request.membership)
        return Response(EmployeeSerializer(made).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        employee = self.get_object()
        if set(request.data) - {"is_active"}:
            raise serializers.ValidationError({"non_field_errors": "Only is_active can be changed."})
        employee.is_active = bool(request.data.get("is_active", employee.is_active))
        employee.save(update_fields=["is_active"])
        return Response(EmployeeSerializer(employee).data)


@extend_schema(tags=["payroll"])
class PayrollRunViewSet(ClientScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Monthly salary runs, each booked as one journal entry."""

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve"}
    queryset = PayrollRun.objects.all()
    serializer_class = PayrollRunSerializer

    def get_queryset(self):
        return super().get_queryset().filter(firm_id=self.request.firm.pk).prefetch_related("lines__employee")

    @extend_schema(
        summary="Book a month of salaries",
        description=(
            "One journal entry dated the last day of the month: Dr Salaries and the employer's PF and ESI, Cr PF Payable, "
            "ESI Payable, TDS Payable (section 192) and each employee's own account for their net. The figures are as typed "
            "from the salary sheet. Once per month; refused inside sealed books. Needs `journal.approve`."
        ),
        request=PayrollRunCreateSerializer,
        responses={201: PayrollRunSerializer},
    )
    def create(self, request, *args, **kwargs):
        body = PayrollRunCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        wanted = [line["employee"] for line in data["lines"]]
        found = {e.pk: e for e in Employee.objects.filter(firm_id=request.firm.pk, client=self.client, pk__in=wanted)}
        missing = [str(pk) for pk in wanted if pk not in found]
        if missing:
            raise serializers.ValidationError({"lines": f"Not employees of this client: {', '.join(missing)}."})
        items = [
            payroll.SalaryInput(
                employee=found[line["employee"]],
                gross_paise=line["gross_paise"],
                pf_employee_paise=line["pf_employee_paise"],
                pf_employer_paise=line["pf_employer_paise"],
                esi_employee_paise=line["esi_employee_paise"],
                esi_employer_paise=line["esi_employer_paise"],
                tds_paise=line["tds_paise"],
                other_deduction_paise=line["other_deduction_paise"],
            )
            for line in data["lines"]
        ]
        run = payroll.post_run(self.client, data["year"], data["month"], items, membership=request.membership)
        return Response(PayrollRunSerializer(self.get_queryset().get(pk=run.pk)).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Take a month of salaries out of the books", responses={204: None})
    @action(detail=True, methods=["post"], url_path="remove", permission_classes=[CanApprove])
    def remove(self, request, client_id=None, pk=None):
        payroll.remove_run(get_object_or_404(self.get_queryset(), pk=pk), membership=request.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)
