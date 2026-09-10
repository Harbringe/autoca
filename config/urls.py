"""URL routing.

Feature apps (banking, ledger, gst, classify) are not routed: they have no
views in this phase.
"""

from django.contrib import admin
from django.urls import path

from core import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("auth/csrf/", views.csrf, name="csrf"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/mfa/setup/", views.mfa_setup, name="mfa-setup"),
    path("auth/mfa/verify/", views.mfa_verify, name="mfa-verify"),
    path("api/me/", views.me, name="me"),
    path("admin/", admin.site.urls),
]
