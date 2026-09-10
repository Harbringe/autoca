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
    # First-party
    "core",
    "integrations",
    # Feature apps: structure only in this phase, no models yet.
    "banking",
    "ledger",
    "gst",
    "classify",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
# Integrations: the adapter registry.
#
# Each value is the dotted path of a class implementing the matching interface
# in integrations/<name>/base.py. Swapping a dev adapter for its AWS beta
# counterpart is a change to this dict (via env var) and nothing else.
# ---------------------------------------------------------------------------

INTEGRATIONS = {
    "storage": env("STORAGE_BACKEND", "integrations.storage.r2.R2StorageAdapter"),
    "ocr": env("OCR_BACKEND", "integrations.ocr.stub.StubOCRAdapter"),
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
    "llm": {},
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
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "autoca.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "autoca.tenancy": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
