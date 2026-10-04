# Running AutoCA on AWS

One small server runs everything: the web app, the API, the database, Redis and the HTTPS proxy, all as containers described in `compose.prod.yaml`. This is the day-to-day guide. How it was built and why is in the commit history of the `aws-deploy` branch.

## Where things are

| | |
|---|---|
| Server | EC2 `autoca-app`, Mumbai (`ap-south-1`), reached with **Session Manager** (EC2 console -> Connect). There is no SSH. |
| Code | `/srv/autoca` (a clone of the repo, branch `aws-deploy`, read-only deploy key) |
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

Later, `git checkout aws-deploy` returns to the branch (`deploy.sh` needs to be on the branch, because it pulls). Migrations that already ran are not undone by going back; a change that added columns or tables is harmless to older code, but ask before going back across one that removed anything.

## Restart

- One service: `ac restart web` (same settings), or `ac up -d --force-recreate web` (re-read settings).
- Whole server: EC2 console -> Instance state -> **Reboot**. Docker starts at boot and every service has `restart: unless-stopped`, so everything comes back by itself. The address does not change (Elastic IP). Give it a minute, then `ac ps`.

## Not set up yet

- **Backups.** The database lives in a Docker volume on the server's disk. Nothing copies it elsewhere yet. A nightly dump to S3 and a tested restore are the next job, and must exist before real client data does.
- **AWS KMS.** Account numbers are encrypted under `KMS_LOCAL_MASTER_KEY`, which lives in `.env.prod`. Moving that to AWS KMS is a later step.
