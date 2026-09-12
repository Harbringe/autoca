"""Re-install the balance trigger with its tenant-context fix.

The function this replaces was installed by 0002 and then corrected in
``core/db/rls.py``. Editing the helper does nothing to a database where 0002 has
already run -- the SQL was executed once, and Python is not the source of truth
for what is installed. The test database is recreated from scratch on every
schema change and so silently picked up the fix; the development database did
not, and failed on the first approval with an error the test suite could not
reproduce.

That asymmetry is the whole reason this migration exists rather than a quiet
edit. Anything that lives in the database -- a function, a trigger, a grant, a
policy -- changes only when a migration says so.

The fix itself: being deferred, the trigger fires during COMMIT, by which point
``firm_context()`` has cleared the tenant GUC on its way out, so the function's
own SELECT hit the table's RLS policy with no context. It now sets the context
from the row it is checking, which can never be wider than what the inserting
transaction already had.
"""

from django.db import migrations

from core.db.rls import balanced_entry_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0002_immutable_journal")]

    operations = [
        *balanced_entry_operations("ledger_journal_line"),
    ]
