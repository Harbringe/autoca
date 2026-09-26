# Platform layer

This app is how the AutoCA platform owner runs the platform. The owner is a superuser who belongs to no firm. Their panel is the Django admin at `/admin/`.

There used to be a separate console at `/app/superadmin`. It is gone. The admin replaced it.

## What the admin does

| Section | Can do |
|---|---|
| Users | Create a login, reset a password, activate or deactivate. Never delete |
| Profiles | Edit the person. Put them in a firm, move them to another, take them out. Set role, who they report to, whether they see every client, and whether they own the firm |
| Firms | Create, rename, activate or deactivate. See the firm's people and clients. Never delete |
| Firm memberships | Read every firm's people in one list. Opening a row goes to that person's profile |
| Clients | Read every firm's clients: name, financial year, lead, who is assigned, and how many bank accounts and statements. Never edit |
| Audit logs, Jobs | Read only |
| TOTP and static devices | Manage second factors |

A firm's books are not in the admin at all. That covers statements, ledgers, classifications and journals, which the firm handles in the app.

The admin shows which clients a person works on but cannot change it. The firm's own administrator makes those assignments in the app.

## How it reads across firms

Row-level security limits the application to one firm per transaction. That rule is unchanged.

The admin's lists read through views in the `app` schema, defined in `superadmin/sql.py`. The views are owned by `autoca_platform_reader`, a role that cannot log in and bypasses RLS. Each view:

- returns directory columns only, never a statement, ledger or bank detail;
- filters with `WHERE app.superadmin_can_read()`, so in Postgres anyone but the platform owner gets zero rows;
- is a `security_barrier` view, so a caller's own filter cannot run before that check.

The application role is granted SELECT on the views and nothing more. PostgreSQL can update a single-table view automatically, and an update through one of these would run as the RLS-bypassing owner. Without that restriction, a read path could become a way to write across firms.

The `Platform*` models in `superadmin/models.py` are unmanaged models over these views. Their `save` and `delete` raise.

## How it writes

Writes never go through the views. They go through the functions at the end of `teams/service.py`:

- `platform_assign`
- `platform_update`
- `platform_remove`
- `platform_update_firm`

Each function opens the tenant context of the one firm it changes and applies that firm's own rules:

- The firm always keeps an active administrator.
- Anyone who still leads people or clients hands them over before stepping down.
- The owner is only replaced, never removed.
- A team leader must belong to the same firm.
- An account belongs to one firm.

Every change is recorded as a team event, with the platform as the actor.

To move a person between firms, the service removes them in one firm's context and adds them in the other's, inside a single transaction. `firm_context` clears itself on exit, which is what allows this.

The profile form rehearses each change first and rolls it back. That way a broken rule shows up as a message on the form rather than a server error.

## Set up (once per environment)

1. In the Supabase SQL editor, as `postgres`, run `superadmin/setup_sql/role.sql`.
2. Run `python manage.py migrate --database=owner`.
3. Run `python manage.py superadmin install`. You only need this if you migrated before step 1.
4. Run `python manage.py superadmin grant you@example.com`. To create a new account that belongs to no firm, add `--create --name "You" --password "..."`.
5. Sign in at `/admin/`.

If step 1 hasn't been run, the views are missing and the platform sections are empty. Users and Profiles still work.

Other commands: `superadmin status`, `superadmin list`, `superadmin revoke <email>`.

## Hooks in existing code

| File | Hook |
|---|---|
| `config/settings/base.py` | `"superadmin"` in `INSTALLED_APPS`; `FIRMLESS_ACCESS` and `ADMIN_ACCESS` |
| `core/middleware/tenancy.py` | `_firmless_allowed()`. It is generic, and does nothing when `FIRMLESS_ACCESS` is unset |
| `core/adminsite.py` | reads `ADMIN_ACCESS`. With it unset, Django's own `is_staff` rule applies |
| `web/src/routes` | sends a firmless session to `/admin/` |
| `pytest.ini` | `superadmin` in `testpaths` |

`core` never imports this app. The settings above are the only connection.

## Tests

- `superadmin/tests/test_superadmin.py` covers who can open the admin, what the views return and refuse, and the admin sections.
- `teams/tests/test_platform.py` covers the service rules.
- View tests skip on a Postgres cluster where `setup_sql/role.sql` has not been run.
