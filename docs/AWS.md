# Running AutoCA on AWS

One small server runs everything: the web app, the API, the database, Redis and the HTTPS proxy, all as containers described in `compose.prod.yaml`. This is the day-to-day guide.

## Branches

There are three, and only three. Everything else is deleted when it is merged.

| Branch | What it is |
|---|---|
| `dev` | Where work happens. Push here freely. CI runs on it. |
| `main` | Stable: changes arrive from `dev` once CI is green. (Render and Vercel, the old setup, still build from this one until they are retired.) |
| `prod` | Exactly what the server runs. The server follows this branch (`git pull`, `deploy/deploy.sh`). |

Promote by fast-forward, never by rewriting history, so each branch is always a prefix of the one before it:

```
git switch main && git merge --ff-only dev  && git push && git switch dev
git switch prod && git merge --ff-only main && git push && git switch dev
```

Then deploy on the server: `sh deploy/deploy.sh`.

## Where things are

| | |
|---|---|
| Server | EC2 `autoca-app`, Mumbai (`ap-south-1`), reached with **Session Manager** (EC2 console -> Connect). There is no SSH. |
| Code | `/srv/autoca` (a clone of the repo, branch `prod`, read-only deploy key) |
| Settings | `/srv/autoca/.env.prod`, `.env.owner`, `.env.db` (never committed, mode 600) |
| Files | S3 bucket `autoca-files-<account-id>`, reached by the server's role (no keys) |
| Logs | CloudWatch Logs group `/autoca/prod`, 90 days, and `ac logs` on the server |
| Web address | `https://app.caworkbench.site` (and `api.caworkbench.site`, same thing) |

## The `ac` helper

`ac` is a shortcut for `docker compose --env-file .env.prod -f compose.prod.yaml` run from `/srv/autoca`. Without it, plain `docker compose` picks up the **development** file and fails.

```
ac ps                          what is running, and is it healthy
ac logs -f --tail 100 web      watch the app live (Ctrl+C to stop); also: caddy, db, redis, migrate
ac logs -f                     watch everything
```

To see only problems: `ac logs -f --tail 200 web | grep -iE "error|warning|exception|Traceback"`.

CloudWatch keeps the same lines after a restart: console -> CloudWatch -> Log groups -> `/autoca/prod` -> **Start tailing** (Live Tail) to watch in the browser, or search a stream by name (`autoca-web-1`, `autoca-caddy-1`, ...).

## Change a setting

Settings are read when a container is **created**. `ac restart web` does NOT pick up a new value; recreating does.

```
cd /srv/autoca
sh deploy/set-env.sh GROQ_API_KEY          # asks for the value, typing hidden; never in your shell history
ac up -d --force-recreate web              # apply it
```

- `deploy/set-env.sh` only changes a setting that is already in the file. A brand-new setting is added by hand: `nano .env.prod`.
- Changing `APP_HOST` or `API_HOST` also needs Caddy recreated: `ac up -d --force-recreate caddy web`, plus a DNS record for the new name, plus the same name in `DJANGO_ALLOWED_HOSTS`, `FRONTEND_URL` and `CSRF_TRUSTED_ORIGINS`.
- **Do not change** `DJANGO_SECRET_KEY` (signs everyone out), `KMS_LOCAL_MASTER_KEY` or `BLIND_INDEX_KEY` (stored bank account numbers become unreadable) on a deployment that has data.
- The database passwords are set once, when the database is first created. Changing the files does not change the passwords inside the database.

## The three permanent keys

`DJANGO_SECRET_KEY`, `KMS_LOCAL_MASTER_KEY` and `BLIND_INDEX_KEY` are generated once. The last two protect stored bank account numbers, so a copy outside this server (a password manager) is essential.

```
sh deploy/show-keys.sh      # shows them once, waits while you copy them, then wipes the screen and scrollback
sh deploy/new-keys.sh       # replaces all three; ONLY while no firm exists (it refuses otherwise)
```

Do not `cat` or `grep` them on screen and then copy the terminal into a chat, ticket or email: the whole screen comes with them. If a key is ever exposed after data exists, it cannot simply be replaced (that would make stored account numbers unreadable); it needs a planned re-encryption.

## Update to new code

```
cd /srv/autoca
sh deploy/deploy.sh
```

It pulls, rebuilds, starts everything (the migrate step runs first, every time), waits, shows the status and checks `https://<app host>/healthz`. A failing check prints what to look at.

### Going back

```
git log --oneline -8                        # find the last good commit
git checkout <that commit>
ac build && ac up -d
```

Later, `git checkout prod` returns to the branch (`deploy.sh` needs to be on the branch, because it pulls). Migrations that already ran are not undone by going back; a change that added columns or tables is harmless to older code, but ask before going back across one that removed anything.

## Restart

- One service: `ac restart web` (same settings), or `ac up -d --force-recreate web` (re-read settings).
- Whole server: EC2 console -> Instance state -> **Reboot**. Docker starts at boot and every service has `restart: unless-stopped`, so everything comes back by itself. The address does not change (Elastic IP). Give it a minute, then `ac ps`.

## Backups

The database lives in a Docker volume on the server's disk, so it is backed up two independent ways.

**1. A nightly dump to S3** (the main one). A systemd timer runs `deploy/backup.sh` at 02:00 IST: it dumps the database, checks the dump can be read back (`pg_restore --list`), uploads it to the backups bucket (`BACKUP_BUCKET`, versioned, encrypted, dumps expire after 35 days), and checks S3 holds every byte. It stops, loudly, at the first thing that does not check out, and uploads nothing it could not read back. The server's role may put, get and list that bucket but **never delete**, so a compromised server cannot erase its own backups.

**2. Daily disk snapshots** (a second net). An AWS Data Lifecycle Manager policy snapshots the whole server disk daily and keeps 7. It also covers the settings files.

```
sudo sh deploy/backup.sh           take one now
sh deploy/backup-status.sh 20      the newest 20, and a warning if the latest is over 26 hours old
sh deploy/restore-drill.sh         prove they work: fresh backup -> scratch database -> compare -> drop. Monthly.
sh deploy/restore.sh <S3 key>      replace the REAL database from a backup (asks you to type RESTORE)
journalctl -u autoca-backup -n 50  what the nightly job said
systemctl list-timers 'autoca-*'   when it next runs
```

**The alarm.** A second timer publishes "how many hours old is the newest backup" to CloudWatch (`Autoca/Backup`, `BackupAgeHours`) every 30 minutes. A CloudWatch alarm emails you when it passes 26, AND when the numbers stop arriving, which is what a dead server looks like. A job that only logs "ok" can tell you neither.

**The keys are not in the dump, on purpose.** Without `KMS_LOCAL_MASTER_KEY` and `BLIND_INDEX_KEY` the stored bank account numbers cannot be read, which is why they live in your password manager, apart from the data. To recover on a new server: create it as in the setup, run `deploy/init-env.sh ... --carry-secrets`, put the SAME three keys into `.env.prod`, start it, then `sh deploy/restore.sh <key>`.

## Not set up yet

- **AWS KMS.** Account numbers are encrypted under `KMS_LOCAL_MASTER_KEY`, which lives in `.env.prod`. Moving that to AWS KMS is a later step.
