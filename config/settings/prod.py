"""Production / staging settings.

Deployed to Render's free web service during development. The security posture
here is not "someday" work: this handles CA client financial data, so the
hardening is on from the first deploy.
"""

from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_required

DEBUG = False
IS_PRODUCTION = True

# No default in production: invitation links and the trusted CSRF origin are built
# from this, and a silent fallback to localhost would send every invitee to a
# dead link.
FRONTEND_URL = env_required("FRONTEND_URL").rstrip("/")

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# The application shell is served from this origin, so nothing legitimate
# arrives with the session cookie from a cross-site navigation.
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
X_FRAME_OPTIONS = "DENY"

# Exactly one TLS-terminating proxy in front of the app. Set explicitly per
# deployment rather than guessed; see core.http.client_ip.
TRUSTED_PROXY_COUNT = int(env("TRUSTED_PROXY_COUNT", "1"))

# The browsable API renderer is a debugging aid. In production it is only a
# way to enumerate field names, so it is removed rather than left to a comment.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

CSRF_TRUSTED_ORIGINS = sorted(
    {o.strip() for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()} | {FRONTEND_URL}
)

# In a deployed environment the app role and the owner role MUST be distinct.
# core.checks turns this into a hard system check failure rather than a comment.
