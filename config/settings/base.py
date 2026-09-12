"""
Base settings shared by every environment.

ARCHITECTURAL RULE #1 (see docs/ARCHITECTURE.md):
Every external service reaches the codebase through an adapter in
``integrations/``, selected here by env var. No vendor SDK is imported anywhere
else. Free-tier today, AWS at beta, should be a config change plus one new
adapter file.
"""

from __future__ import annotations

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# The test suite gets its own env file, because it connects as a different
# database role: autoca_test has CREATEDB (the runner builds a scratch database
# per run) while autoca_web deliberately does not. Loading .env for tests would
# silently run the suite against the development database.
_DOTENV = BASE_DIR / (
    ".env.test" if os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".test") else ".env"
)
load_dotenv(_DOTENV, override=False)


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_required(key):
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Required environment variable {key} is not set. "
            "Copy .env.example to .env and fill it in."
        )
    return value


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env_required("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # MFA
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    # API
    "rest_framework",
    "drf_spectacular",
    # First-party
    "core",
    "api",
    "integrations",
    "documents",
    # Feature apps.
    "banking",
    "ledger",
    "gst",
    "classify",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.headers.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # --- First-party. Order matters; see each module's docstring. ---
    "core.middleware.mfa.MFARequiredMiddleware",
    "core.middleware.tenancy.TenantContextMiddleware",
    "core.middleware.audit.AuditMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database
#
# Two aliases against the SAME physical database, with DIFFERENT roles:
#
#   default  -> the application role. NOT a superuser, NOT the table owner, NOT
#               granted BYPASSRLS. This is the connection that serves every web
#               request, so RLS is a wall the app cannot climb over regardless
#               of what a future bug in business logic does.
#   owner    -> the DDL/migration role. Owns the tables. Used only by
#               `manage.py migrate` and maintenance commands.
#
# Splitting them is what makes "deny by default" structural rather than
# aspirational. FORCE ROW LEVEL SECURITY is applied as well, so even the owner
# is subject to the policies.
# ---------------------------------------------------------------------------

_APP_DB_URL = env_required("DATABASE_URL")
_OWNER_DB_URL = env("DATABASE_OWNER_URL") or _APP_DB_URL

# Supabase's pooler, and pgbouncer generally, runs in transaction pooling mode.
# CONN_MAX_AGE must be 0 and server-side cursors off. This is also exactly why
# the tenancy middleware uses SET LOCAL rather than SET: transaction-scoped
# settings are the only ones that are safe under a transaction pooler.
_POOLED = env_bool("DATABASE_IS_POOLED", False)

_DB_COMMON = {
    "conn_max_age": 0 if _POOLED else 60,
    "conn_health_checks": not _POOLED,
    "ssl_require": env_bool("DATABASE_SSL_REQUIRE", True),
}

DATABASES = {
    "default": dj_database_url.parse(_APP_DB_URL, **_DB_COMMON),
    "owner": dj_database_url.parse(_OWNER_DB_URL, **_DB_COMMON),
}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = _POOLED
DATABASES["owner"]["DISABLE_SERVER_SIDE_CURSORS"] = _POOLED

# The owner alias points at the same physical database, so the test runner must
# not create a second test database for it.
DATABASES["owner"]["TEST"] = {"MIRROR": "default"}

DATABASE_ROUTERS = ["core.db.routers.OwnerMigrationRouter"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The Postgres GUC every RLS policy reads. Changing this means changing every
# policy, so it is defined in exactly one place.
TENANT_GUC = "app.firm_id"

# Keys every deterministic lookup column for an encrypted identifier -- bank
# account numbers today, GSTIN and PAN when the GST module lands. Generated once
# and kept: rotating it makes every existing blind index unfindable, which is a
# data migration, not a config change. See core/crypto.blind_index.
BLIND_INDEX_KEY = env("BLIND_INDEX_KEY", "")

# Set before the firm GUC, and only ever read by the membership bootstrap
# policy. It exists so that "which firm am I in?" can be answered under RLS
# instead of by an RLS bypass. See core/db/rls.py.
TENANT_USER_GUC = "app.user_id"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["core.auth.backends.EmailBackend"]

# Argon2PasswordHasher uses argon2id.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/auth/login/"
OTP_TOTP_ISSUER = env("OTP_TOTP_ISSUER", "AutoCA")

# Paths that answer with JSON rather than HTML. Used to decide whether a
# half-authenticated request is redirected to the MFA page or told in a body
# that it cannot proceed.
API_PATH_PREFIXES = ("/api/",)

# ...except these, which are HTML pages a person opens in a browser. They sit
# under /api/ but are documentation, not the API.
API_DOC_PATH_PREFIXES = ("/api/docs/", "/api/redoc/")

# TOTP is mandatory. These are the only paths reachable by a session that has
# passed a password check but not yet a second factor.
MFA_EXEMPT_PATH_PREFIXES = (
    "/auth/login/",
    "/auth/logout/",
    "/auth/mfa/",
    "/healthz",
    "/static/",
)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 60 * 60 * 8
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# ---------------------------------------------------------------------------
# Abuse limits
# ---------------------------------------------------------------------------

# Failed-attempt counters live in the cache. One process can count in memory;
# more than one must share a Redis so a lockout on one is a lockout on all.
# core.checks flags a deployed locmem cache.
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("CACHE_URL")}
        if env("CACHE_URL")
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "autoca"}
    )
}

# attempts within window_seconds -> locked out for lockout_seconds. Keyed on
# the address and on the account separately; see core/throttle.py.
THROTTLE_LIMITS = {
    "login": {"attempts": 10, "window_seconds": 15 * 60, "lockout_seconds": 15 * 60},
    # TOTP codes are six digits and a window is thirty seconds. django-otp
    # throttles the device itself as well; this is the address-level backstop.
    "mfa": {"attempts": 6, "window_seconds": 10 * 60, "lockout_seconds": 15 * 60},
}

# How many reverse proxies stand between the internet and this process. Zero
# means X-Forwarded-For is a header anyone could have sent and is ignored.
TRUSTED_PROXY_COUNT = int(env("TRUSTED_PROXY_COUNT", "0"))

# A bank statement PDF for a year is a few megabytes. This is a ceiling for the
# request body, not a target; the upload serializer applies a tighter one to
# the file itself and checks that it is a PDF before reading it.
MAX_STATEMENT_UPLOAD_BYTES = 25 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 5

# ---------------------------------------------------------------------------
# Browser-enforced policy
#
# Strict by default: the application shell needs nothing from any other origin
# and runs no inline script. The documentation viewer and the Django admin
# cannot live under that and get their own, still without framing.
# ---------------------------------------------------------------------------

_CSP_STRICT = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "upgrade-insecure-requests"
)
_CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
_CSP_ADMIN = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
CONTENT_SECURITY_POLICIES = {
    "default": _CSP_STRICT,
    "by_prefix": {
        "/api/docs/": _CSP_DOCS,
        "/api/redoc/": _CSP_DOCS,
        "/admin/": _CSP_ADMIN,
        # The MFA pages carry an inline SVG QR code and a small inline style.
        "/auth/mfa/": _CSP_ADMIN,
    },
}
PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "accelerometer=(), gyroscope=(), magnetometer=(), interest-cohort=()"
)

# ---------------------------------------------------------------------------
# Integrations: the adapter registry.
#
# Each value is the dotted path of a class implementing the matching interface
# in integrations/<name>/base.py. Swapping a dev adapter for its AWS beta
# counterpart is a change to this dict (via env var) and nothing else.
# ---------------------------------------------------------------------------

INTEGRATIONS = {
    "storage": env("STORAGE_BACKEND", "integrations.storage.r2.R2StorageAdapter"),
    "ocr": env("OCR_BACKEND", "integrations.ocr.stub.StubOCRAdapter"),
    "pdf": env("PDF_BACKEND", "integrations.pdf.pdfplumber_text.PdfPlumberAdapter"),
    "queue": env("QUEUE_BACKEND", "integrations.queue.celery_redis.CeleryRedisQueueAdapter"),
    "kms": env("KMS_BACKEND", "integrations.kms.local_fernet.LocalFernetKMSAdapter"),
    "llm": env("LLM_BACKEND", "integrations.llm.stub.StubLLMAdapter"),
}

INTEGRATION_OPTIONS = {
    "storage": {
        "bucket": env("STORAGE_BUCKET", "autoca-dev"),
        "endpoint_url": env("STORAGE_ENDPOINT_URL"),
        "region": env("STORAGE_REGION", "auto"),
        "access_key_id": env("STORAGE_ACCESS_KEY_ID"),
        "secret_access_key": env("STORAGE_SECRET_ACCESS_KEY"),
        "root": env("STORAGE_LOCAL_ROOT", str(BASE_DIR / ".devdata" / "storage")),
    },
    "ocr": {},
    "pdf": {},
    "queue": {
        "broker_url": env("CELERY_BROKER_URL"),
    },
    "kms": {
        # Dev only. Stands in for a KMS-wrapped data key; see
        # integrations/kms/local_fernet.py for what it is and is not.
        "master_key": env("KMS_LOCAL_MASTER_KEY"),
        # Beta:
        "key_id": env("KMS_KEY_ID"),
        "region": env("KMS_REGION"),
    },
    "llm": {
        # Groq (dev). Key from the Groq console; the model is optional.
        "api_key": env("GROQ_API_KEY"),
        "model": env("GROQ_MODEL"),
        "base_url": env("GROQ_BASE_URL"),
        "timeout_seconds": float(env("LLM_TIMEOUT_SECONDS", "30")),
    },
}

# Rows per model call. Classification is not latency-sensitive; fewer, larger
# calls share the system prompt and cost less.
LLM_BATCH_SIZE = int(env("LLM_BATCH_SIZE", "25"))

# Whether an organisation's name may be sent to the model as part of a row.
# People's names never are -- see classify/pseudonymise.py. A firm that wants
# nothing but aliases sent sets this to 0 and accepts weaker suggestions.
LLM_SHARE_BUSINESS_NAMES = env_bool("LLM_SHARE_BUSINESS_NAMES", True)

# ---------------------------------------------------------------------------
# API
#
# Session authentication, not tokens. A stolen JWT is valid until it expires and
# cannot be revoked, which is a poor trade for a product holding client
# financial records -- and the SPA is first-party, so there is no third-party
# client that a cookie would be awkward for. CSRF is enforced.
#
# Nothing is readable without authentication. There is no public corner of this
# API, so the default permission is the strict one and an endpoint opts out
# rather than opting in.
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "api.permissions.IsFirmMember",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "api.pagination.DefaultPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "api.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        # The browsable API is a genuinely useful way to poke at endpoints by
        # hand, and it is behind the same login as everything else. Off in
        # production, where it is only a way to leak field names.
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "COERCE_DECIMAL_TO_STRING": True,
    "DATETIME_FORMAT": "iso-8601",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "AutoCA API",
    "VERSION": "1.0.0",
    "DESCRIPTION": (
        "Bank statements in, approved double-entry journal entries out.\n\n"
        "### Two conventions worth knowing before you read anything else\n\n"
        "**Money is always a whole number of paise**, in a field named `*_paise`. "
        "Every amount also carries a `*_display` twin, already formatted with "
        "Indian digit grouping (`Rs 6,03,490.57`). Use the integer for arithmetic "
        "and the string for rendering, and never parse the string or format the "
        "integer yourself -- a JSON number with a decimal point becomes a float "
        "in a browser, which is exactly the rounding error the backend exists to "
        "avoid.\n\n"
        "**Nothing is final until a senior CA approves it.** Uploading a statement "
        "and classifying its rows produces *suggestions*. Only "
        "`POST /clients/{id}/approvals/` writes to the ledger, only a senior CA "
        "or firm admin may call it, and what it writes cannot afterwards be "
        "edited or deleted -- corrections are new entries that reverse and "
        "replace.\n\n"
        "### Slow work\n\n"
        "Uploading a statement returns **202 Accepted** with a job. Poll "
        "`/jobs/{id}/` or subscribe to `/jobs/{id}/events/` for server-sent "
        "events.\n\n"
        "### Errors\n\n"
        "Failures carry a stable `code` and a `detail` written to be read by a "
        "person -- the parser's messages name the row and the figure that broke, "
        "and they are passed through rather than replaced. `422` means the "
        "document could not be read; `409` means the request conflicts with the "
        "current state; `403` is a role boundary and is never disguised as a 404."
    ),
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "TAGS": [
        {"name": "session", "description": "Who is signed in and what they may do."},
        {"name": "clients", "description": "The firm's clients."},
        {"name": "statements", "description": "Uploading statements and reading their rows."},
        {"name": "review", "description": "The review queue and the decisions made against it."},
        {"name": "ledger", "description": "Approval, the permanent journal, and corrections."},
        {"name": "reports", "description": "Trial balance, P&L, balance sheet, reconciliation."},
        {"name": "jobs", "description": "Progress on work the API did not block for."},
    ],
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
        "displayRequestDuration": True,
        "docExpansion": "none",
        "filter": True,
        "tryItOutEnabled": True,
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "memory://")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_BROKER_USE_SSL = env_bool("CELERY_BROKER_USE_SSL", False)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# ---------------------------------------------------------------------------
# i18n / static
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "filters": {
        # Every record is masked before it is written. See core/logging.py.
        "mask_identifiers": {"()": "core.logging.MaskingFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["mask_identifiers"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "autoca.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "autoca.tenancy": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "autoca.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
