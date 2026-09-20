# Teams, client assignment and work tracking: design

## What we're building
A firm is run like a small company:
- **Firm admin:** sees and manages everything.
- **Senior CA:** leads a team and is responsible for some of the firm's clients. They assign their clients to their staff, invite staff onto their team, switch team members off and on, track their team's work, and approve entries for their own clients.
- **Staff / Read-only:** belong to one Senior CA's team. They see and work only on the clients they've been assigned.

## Decisions (confirmed with the user)
1. Assignment **limits visibility**, enforced server-side on every client endpoint, report and export.
2. The structure is team lead plus client team. Each Staff and Read-only member reports to one Senior CA. Each client has one **lead** (a Senior CA or firm admin) and any number of assigned team members.
3. A Senior CA can: assign their clients to their own staff, invite Staff or Read-only users onto their team, and deactivate or reactivate their own team members.
4. Approving and correcting entries, and accepting proposed ledgers, are limited to **the client's lead or a firm admin**.

## Decisions I made (easy to change before build)
- **Existing members keep seeing everything.** `scope_all_clients` keeps `default=True` in the model, so current members and test fixtures are unchanged. Only the invite path passes `False`, and firm admins can switch it off per person. It's also how you'd give a Read-only auditor the whole firm.
- **A client with no lead behaves as it does today:** any approver in the firm may sign off. Existing clients start with no lead, so no Senior CA loses approval on deploy. The Team page flags clients with no lead so the admin can set one.
- **The database won't stop cross-firm links.** Postgres foreign key checks aren't subject to RLS, so `manager`, `lead` and `ClientAssignment.membership` could point at another firm's rows. `core/team.py` checks firm (and team) equality before every save, serializers scope their querysets, and the isolation suite tries a cross-firm value for each of these foreign keys.
- **Activity events are written in the same transaction as the action.** If the event can't be written, the action fails too, so work counts never silently drop rows.
- **Invite acceptance** is throttled per token (not per IP) with `core/throttle.py`. The token is consumed under `select_for_update`, so it can only be used once. The response sends the invitee into authenticator setup; they're never signed in without a second factor.
- **Invites are links, not emails.** There's no mail sending yet. The inviter gets a single-use link, valid for 7 days, to send however they like. The invitee sets a name and password, then enrols their authenticator as usual. If the email already has an account, they're simply added to the firm.
- **Moving a staff member to another Senior CA** takes them off the old lead's clients by default. The dialog shows how many clients are affected and offers "keep".
- **Deactivating a Senior CA** is blocked while they still lead clients or have team members. The firm admin reassigns first, and the dialog walks through it. Nothing is ever left orphaned.
- **Changing a client's lead** keeps the assigned staff. The new lead can remove them.
- **A firm admin can't deactivate or demote themselves**, and a firm always keeps at least one active firm admin.
- **Work is counted from a new append-only activity log**, not from the fields that already exist. `reviewed_by` is overwritten by the approver, so today's data can't say who placed a row. Uploads, approvals and corrections are backfilled from the existing fields. Placements are counted from the release date onward.
- **Hidden clients return 404, not 403**, so their existence isn't leaked.
- **Jobs:** firm admins see all of them; everyone else sees only jobs they started.

## Data model (all firm-scoped, under RLS, with isolation factories)
| Change | Notes |
|---|---|
| `FirmMembership.manager` → `FirmMembership` (nullable) | Only for Staff / Read-only; must be an active Senior CA or firm admin in the same firm |
| `Client.lead` → `FirmMembership` (nullable) | Must be an active Senior CA or firm admin |
| `ClientAssignment(client, membership, assigned_by, assigned_at)` | Unique per (client, membership) |
| `InviteToken(email, full_name, role, manager, token_hash, expires_at, used_at, created_by)` | Only a hash of the token is stored |
| `ActivityEvent(client?, user, kind, quantity, subject_id, at)` | Append-only (immutable trigger, like the journals) |
| `TeamEvent(kind, actor, member?, client?, detail JSON, at)` | Append-only history of every assignment, remapping, invite and deactivation |

`ActivityEvent.kind` values: `statement.uploaded`, `row.placed` (quantity includes rows a learned rule placed in the same action), `entry.approved`, `entry.corrected`, `ledger.created`, `rule.created`, `proposal.decided`, `model.run`.

## Visibility: one function, used everywhere
`core/access.py`:
- `visible_clients(membership)`:
  - A firm admin, or a member with all-clients access, sees every client.
  - A Senior CA sees clients they lead, plus clients they're assigned to.
  - Staff and Read-only see clients they're assigned to.
- `get_visible_client(request, id)` returns the client or a 404.
- `can_sign_off(membership, client)`: firm admin, or `client.lead == membership`.

It replaces `FirmMembership.accessible_clients()`, which now delegates to it, and applies to:
- `ClientScopedMixin` (bank accounts, statements, ledgers, vendors, rules, review queue)
- `ClientViewSet`
- `StatementUploadView`, `ApprovalView`, `ReportView`
- `ReconciliationView`, which checks the account's client
- `TallyExportView`, which checks the statement's client
- `JournalEntryViewSet`, `TransactionViewSet` and `ClassificationViewSet`, whose querysets are filtered by client
- `JobViewSet`

`can_sign_off` is enforced **inside** `ledger.approval.approve` / `correct` and `classify.proposals`, as well as in the views. That matches the existing "checked twice" rule.

A sweep test **walks the DRF router registry**. It lists every collection and calls every client-nested route as an unassigned Staff member, expecting an empty list or a 404. Id-addressed collections like `/journal-entries/`, `/transactions/` and `/classifications/` are included, so a future endpoint that forgets the rule fails the build.

## Permissions (`core/rbac.py` stays the single source)
New codenames: `team.view`, `team.assign`, `member.invite`, `member.deactivate`, `member.manage`.
- Firm admin: all of them.
- Senior CA: `team.view`, `team.assign`, `member.invite`, `member.deactivate`. Each one is limited to their own team and the clients they lead, in `core/team.py`.
- `member.manage` (change role, change manager, all-clients access, change a client's lead) is firm admin only.

## API: `/api/v1/team/`
| Method + path | Who | What |
|---|---|---|
| `GET members/` | admin: everyone; CA: self and their team | person, role, manager, active, all-clients flag, client count, last sign-in, work totals for `?from&to` |
| `POST members/` (invite) | admin; CA (role Staff/RO, manager = self) | returns the invite link once |
| `PATCH members/{id}/` | admin: role, manager, all-clients, active; CA: active (own team only) | guard rails above; `keep_client_assignments` when changing manager |
| `GET members/{id}/activity/?from&to` | admin; CA (own team); anyone (self) | totals by kind, per-client breakdown, daily series, open work on their clients |
| `GET clients/` | admin: all; CA: clients they lead | lead, assigned members, open work (unresolved / pending approval) |
| `PUT clients/{id}/lead/` | admin | |
| `POST clients/{id}/members/`, `DELETE clients/{id}/members/{mid}/` | admin; CA (own clients, own team) | |
| `GET events/` | admin: all; CA: those involving their team or clients | history |
| `GET invites/`, `DELETE invites/{id}/` | admin; CA (their own invites) | pending invites, revoke |
| `POST /auth/invite/accept/` (public) | invitee | token + name + password → signed in, then MFA enrolment |

## Frontend
- **Team** (sidebar, for admins and Senior CAs), in four tabs:
  - **People:** grouped by Senior CA, with an "Unassigned" group for admins. A person panel shows role, manager, clients, work for the chosen period, and actions.
  - **Clients:** each client with its lead and team chips; add or remove people; admins change the lead.
  - **Work:** a per-person table of uploads / placed / approved / corrected / open, with a period picker (this week, this month, custom).
  - **History:** the team event log.
- **Invite dialog:** email, name, role, team; then shows a copyable link.
- **Accept invite page:** `/app/invite/:token`.
- **Clients page:** adds a Lead column. Staff with no assigned clients see "You haven't been assigned any clients yet. Ask your Senior CA."
- **My work** (for everyone): your own activity and your clients' open work.
- Approve buttons are hidden unless you're allowed to sign off for that client. The server re-checks.
- The super admin console's member access view uses the same rule. That needs one extra directory function (`superadmin install` again).

## Build order (each step shippable, with its tests green)
1. **Model and migrations:** manager, lead, assignment, events, activity; RLS; factories; backfill.
2. **`core/access.py`:** applied to every endpoint; sign-off rule in approval and proposals; sweep test.
3. **Activity events:** emitted from ingest, review, approval, correction, rules, ledgers and model runs.
4. **Team service and API:** members, assignments, invites, events, activity.
5. **Frontend:** Team page, invite flow, My work, and the Clients page and approval changes.
6. **Super admin:** member-access update.
