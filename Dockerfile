# Two stages: build the frontend with Node, run the application with Python.
# The image that ships carries no Node, no compiler, and no source tree it does
# not need.

# --- frontend ---------------------------------------------------------------
FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- application --------------------------------------------------------------
FROM python:3.13-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# A non-root user. The process needs nothing root can do.
RUN addgroup --system autoca && adduser --system --ingroup autoca --home /srv/app autoca

WORKDIR /srv/app
COPY requirements/ requirements/
RUN pip install -r requirements/base.txt

COPY --chown=autoca:autoca . .
COPY --from=frontend --chown=autoca:autoca /build/dist frontend/dist

# collectstatic needs settings to import, which needs a SECRET_KEY and a
# DATABASE_URL to parse; neither is used at build time.
RUN DJANGO_SECRET_KEY=build-only DATABASE_URL=postgresql://x:x@localhost/x \
    python manage.py collectstatic --noinput

USER autoca
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# Migrations run as the owner role, once, by the `migrate` service in compose
# (or the release phase of a PaaS) -- never from every web replica at boot.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "--forwarded-allow-ips", "*"]
