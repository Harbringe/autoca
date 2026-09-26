"""URL routing.

The REST API lives under ``/api/v1/`` and is the only interface the web
application (web/, a separate deployment) uses. The session endpoints above it are shared: the API authenticates with the
same session cookie, so signing in is one flow rather than two.

``/api/docs/`` is Swagger UI over the generated OpenAPI schema. It sits behind
the same login as everything else, because the schema names every field of every
firm-scoped table and is not something to publish.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from core import views
from teams.views import accept_invite

urlpatterns = [
    # The web application is a separate deployment; see FRONTEND_URL.
    path("", views.to_frontend, name="frontend"),
    path("healthz", views.healthz, name="healthz"),
    path("auth/csrf/", views.csrf, name="csrf"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/mfa/setup/", views.mfa_setup, name="mfa-setup"),
    path("auth/mfa/verify/", views.mfa_verify, name="mfa-verify"),
    path("auth/invite/", accept_invite, name="invite-accept"),
    path("api/me/", views.me, name="me"),
    # --- REST API ---
    path("api/v1/", include("api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path("admin/", admin.site.urls),
]
