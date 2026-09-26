"""Check that removing the statement-review client's statements also removed the stored files.

    python scripts/qa_statement_cleanup.py --keys     # before cleanup: remember the stored-file keys
    python scripts/qa_statement_cleanup.py --verify   # after: each file must be gone (removes stragglers)

The keys go to web/qa/private/ (gitignored). They name a firm, a client and a document by
id only; nothing in them is from the statement's contents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from core.db.session import firm_context  # noqa: E402
from documents.models import Document  # noqa: E402
from integrations.registry import get_storage  # noqa: E402

PRIVATE = ROOT / "web" / "qa" / "private"
FIRM = json.loads((ROOT / "web" / "qa" / ".qa-firm").read_text())["firm"]
KEYS = PRIVATE / "storage-keys.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    storage = get_storage()

    if args.keys:
        with firm_context(FIRM):
            keys = [k for k in Document.objects.values_list("storage_key", flat=True) if k]
        PRIVATE.mkdir(parents=True, exist_ok=True)
        KEYS.write_text(json.dumps(keys))
        print(f"{len(keys)} stored file(s) recorded; {sum(storage.exists(k) for k in keys)} exist now.")
        return 0

    keys = json.loads(KEYS.read_text())
    lingering = [k for k in keys if storage.exists(k)]
    for key in lingering:
        storage.delete(key)
    with firm_context(FIRM):
        left = Document.objects.exclude(storage_key="").count()
    print(f"{len(keys)} recorded; {len(lingering)} were still stored (now deleted); {left} document record(s) remain.")
    return 1 if lingering else 0


if __name__ == "__main__":
    raise SystemExit(main())
