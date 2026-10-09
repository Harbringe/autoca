"""Settings for running a server on this machine against the LIVE database, reached through an SSM tunnel (docs/LIVE.md).

Everything is as in development, except that only a short list of management commands may run. Anything that changes the
schema, loads or wipes data, or runs the test suite (which creates and drops a database on whatever server it is pointed at)
is refused here, before it can start. The web server itself is the whole point: ``runserver``, ``check`` and a read-only look
at the migrations.

The model, the file bucket and the assistant worker are each OFF until ``.env.live`` turns them on with an explicit flag
(``LIVE_ALLOW_MODEL``, ``LIVE_ALLOW_STORAGE``, ``LIVE_ALLOW_ASSISTANT``). Off means a stub model, a storage adapter that refuses, and
no jobs. On means the real thing, so what you do here reads and writes the real bucket and sends real rows to the model.
"""

import sys

from django.core.exceptions import ImproperlyConfigured

from .dev import *  # noqa: F401,F403
from .base import env, env_bool

# The project's own .env may define DATABASE_OWNER_URL for some other database (it did: the old hosted one). Here there is one
# database, the live one through the tunnel, so the owner alias is the same connection as the default and nothing else.
DATABASES["owner"] = {**DATABASES["default"], "TEST": {"MIRROR": "default"}}  # noqa: F405

# --- The model ---------------------------------------------------------------------------------------------------------
if env_bool("LIVE_ALLOW_MODEL"):
    if not INTEGRATION_OPTIONS["llm"]["api_key"] or INTEGRATIONS["llm"].endswith("StubLLMAdapter"):  # noqa: F405
        raise ImproperlyConfigured(
            "LIVE_ALLOW_MODEL is on, but no model is configured. Put LLM_BACKEND and the key (LLM_API_KEY, or GROQ_API_KEY) in "
            ".env.live, the same as the server's."
        )
    # Real rows go to the provider named in INTEGRATIONS["llm"]; VISION_READING comes from the environment as on the server.
else:
    INTEGRATIONS = {**INTEGRATIONS, "llm": "integrations.llm.stub.StubLLMAdapter"}  # noqa: F405
    VISION_READING = False

# --- The file bucket ---------------------------------------------------------------------------------------------------
if env_bool("LIVE_ALLOW_STORAGE"):
    if not INTEGRATIONS["storage"].endswith("S3StorageAdapter") or env("STORAGE_BUCKET", "autoca-dev") == "autoca-dev":  # noqa: F405
        raise ImproperlyConfigured(
            "LIVE_ALLOW_STORAGE is on, but the bucket is not set. Put STORAGE_BACKEND=integrations.storage.s3.S3StorageAdapter, "
            "STORAGE_BUCKET and STORAGE_REGION in .env.live (the same as the server's); the project .env points at a dev store."
        )
    # Your own AWS login supplies the credentials (as the server's role does there). Keys from the project .env are for a dev store.
    INTEGRATION_OPTIONS["storage"].update(  # noqa: F405
        {"access_key_id": None, "secret_access_key": None, "endpoint_url": None}
    )
else:
    INTEGRATIONS = {**INTEGRATIONS, "storage": "integrations.storage.refused.RefusedStorageAdapter"}  # noqa: F405

# --- The assistant (the background worker) ----------------------------------------------------------------------------
# `run_assistant` reads waiting rows for every client and sends them to the model. The server runs one in its own container; a
# second one here is safe (rows are claimed with SKIP LOCKED) but it spends model calls on real rows, so it needs the model on
# and its own flag. The schema is changed by the deploy, never from a PC, so migrate stays refused whatever the flags say.
ALLOWED_COMMANDS = {"runserver", "check", "showmigrations", "diffsettings", "shell"}
if env_bool("LIVE_ALLOW_ASSISTANT"):
    if not env_bool("LIVE_ALLOW_MODEL"):
        raise ImproperlyConfigured("LIVE_ALLOW_ASSISTANT needs LIVE_ALLOW_MODEL too: the assistant is a model reader.")
    ALLOWED_COMMANDS.add("run_assistant")

_command = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
if _command is not None and _command not in ALLOWED_COMMANDS:
    raise ImproperlyConfigured(
        f"`manage.py {_command}` is refused against the live database. Allowed here: {', '.join(sorted(ALLOWED_COMMANDS))}. "
        "Use the development settings and a local database for anything else."
    )
