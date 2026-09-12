"""Local development settings.

The dev database is the project's Supabase free-tier Postgres. Note its two
operational quirks: the project pauses after 7 days of inactivity (see
scripts/supabase_keepalive.py), and the pooled connection string requires
DATABASE_IS_POOLED=1.
"""

from .base import *  # noqa: F401,F403
from .base import env_bool

DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

# Dev over http://localhost, so no HTTPS-only cookie flags.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

INTERNAL_IPS = ["127.0.0.1"]

# `npm run dev` serves the shell from 5173 and proxies the API here. Its POSTs
# arrive with an Origin of the dev server, which CSRF must accept in development.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Serve the freshly built bundle without collectstatic.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
