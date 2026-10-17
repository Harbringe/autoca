# Finding out how the app behaves with many rows

A throwaway second database on the production server, filled with fake rows, so the slow screens show themselves before a
client's data does. Nothing in it is real and nothing in it is connected to the live database.

## How it is kept apart from the live site

- A separate Compose project (`autoca-scale`): its own Postgres, network and volume. No port is published.
- Fresh random passwords and keys, written to `.env.scale` next to the script, and deleted by `down`. No live key is used.
- The database is named `autoca_scale_test`; `fill.py` and `timing.py` refuse to run against any other name.
- The scratch Postgres is capped at 640 MB and half a CPU, the tool container at 384 MB and half a CPU, so the live containers keep
  the rest of the 2 GB server. Run it when nobody is working: the server's CPU credits (a t3.small earns them slowly) are shared.

## Run it (Session Manager shell on the server)

```sh
# 1. Get the scripts (read-only; this does not change the running site)
cd /srv/autoca && sudo git fetch origin dev
rm -rf /tmp/scale && mkdir /tmp/scale && sudo git archive origin/dev scripts/scale | tar -x -C /tmp/scale
cd /tmp/scale/scripts/scale

sh scale.sh check            # disk and memory to spare, and what the live containers are using
sh scale.sh up               # start the scratch database and build its tables
sh scale.sh fill --txns 300000        # start small; then 1000000, then 3000000
sh scale.sh stats            # table sizes
sh scale.sh time             # the timing table (add --plans for the EXPLAIN output)
sh scale.sh top              # slowest statements seen
sh scale.sh down             # when finished: deletes the database, its volume and its passwords
```

Watch the live site while a fill runs (`sudo docker stats`); stop with Ctrl+C and `down` if it slows.

## Reading the table

Each row of `time` is one screen's query, as the app's own login under row-level security. Look for: a query whose time grows faster than
the rows (compare 300k with 1M), a `SEQ SCAN` flag on a big table, and the "whole queue" row, which is what the Review screen downloads.
