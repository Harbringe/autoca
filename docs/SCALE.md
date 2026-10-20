# Scale and load testing

A throwaway second database (and, for load tests, a second copy of the app) on the production server, filled with fake rows, so the
slow screens show themselves before a client's data does. Nothing in it is real and nothing in it is connected to the live database.

Four tests, in the order to run them:

| Test | Command | What it tells you |
| --- | --- | --- |
| Data volume | `fill`, then `time` | Whether a screen's query gets slow as rows pile up (300k, 1M, 3M bank rows). |
| Many people at once | `load run` | How response times and errors grow with 5, 20, 50 people using the app together. |
| Big uploads | `load uploads` | Whether several large statements at once (like a 238-page one) exhaust memory or time out. |
| The assistant worker | `assistant` | How fast it clears a big queue, and what posting costs, with a fake model that answers at once. |

## Where to run it: not on the live server

Run it on a **separate, throwaway server of the same size** (a t3.small), not on the live one. The live t3.small has 1.9 GB of memory and the live
app and its worker use most of it (about 1.4 GB in use, about 500 MB available when idle), while the scratch database, tool and app are allowed
480 + 256 + 512 MB. A stress test that needs more memory than the server has makes the operating system kill a process, and the largest is the live
site. The scale script now **refuses** a step when the server has too little memory free for it, so on the live server it will stop at `up`.

1. In the AWS console (region ap-south-1) launch an EC2 instance: Amazon Linux 2023, t3.small, 20 GB disk, **no inbound ports**, and an instance profile
   with `AmazonSSMManagedInstanceCore` so you can open a Session Manager shell. Name it `autoca-scale-test`.
2. Open a Session Manager shell on it and run `curl -fsSL https://raw.githubusercontent.com/Harbringe/autoca/dev/scripts/scale/bootstrap-ec2.sh | sh`
   (installs Docker and git, clones the repository, builds the same app image).
3. `cd /srv/autoca/scripts/scale` and follow "Run it" below, from `sh scale.sh check`.
4. **Terminate the instance when you are done.**

A separate server cannot slow the live site, so there is nothing to watch on it. To see what real clients would feel, use the probe described under
"The client's own experience" below on the live site.

## The client's own experience

What a client feels is the server's answers plus their own browser drawing them. The first is measured by `load run` on the test server. The second
(the Review screen drawing a 2,500-row queue, for example) does not depend on the server's load and is measured in a real browser: open the screen with
the browser's Performance panel, or ask for the page's paint and long-task timings. Run that against a client with a long queue.

## How it is kept apart from the live site

- A separate Compose project (`autoca-scale`): its own Postgres, network and volume. No port is published.
- Fresh random passwords and keys, written to `.env.scale` next to the script, and deleted by `down`. No live key is used.
- The database is named `autoca_scale_test`; `fill.py`, `timing.py`, `load.py` and `assistant.py` refuse to run against any other name.
- Capped: database 480 MB and half a CPU, tool 256 MB and half a CPU, scratch app 512 MB and 0.75 CPU, so the live containers keep
  the rest of the 2 GB server. A t3.small earns CPU credits slowly and they are shared: run it when nobody is working.
- The people the load script signs in as exist only in the scratch database (`load-N@scale.invalid`), with a session made directly for the
  scratch app, so none of it can sign in anywhere else.
- Every run samples the CPU and memory of **all** containers, the live ones too, and prints the peaks at the end. If the server has less than
  250 MB of memory left (`SCALE_MIN_FREE_MB`) the test stops itself and kills the scratch containers (not the database).

## Before you start, and while it runs

1. Pick a quiet time. Tell people not to work during the heavy runs (the 50-person phase and the uploads).
2. On any machine, in a separate window, watch the live site: `sh scripts/scale/watch-live.sh` (prints a line for every `/healthz` answer over 1.5 s or
   not 200, and a summary every five minutes). Its baseline is about 50 to 170 ms. **If it prints SLOW or FAILED more than once in a row, press
   Ctrl+C on the test and run `sh scale.sh down`.**
3. `sudo docker stats` on the server shows the same live containers if you want to see it directly.

## Run it (Session Manager shell on the server)

```sh
# 1. Get the scripts (read-only; this does not change the running site)
# (no sudo for git: root has no deploy key on the server; Docker is the only thing that needs sudo)
cd /srv/autoca && git fetch origin dev
rm -rf /tmp/scale && mkdir /tmp/scale && git archive origin/dev scripts/scale | tar -x -C /tmp/scale
cd /tmp/scale/scripts/scale

sh scale.sh check            # disk and memory to spare, and what the live containers are using
sh scale.sh up               # start the scratch database and build its tables

# 2. Data volume: start small, then 1000000, then 3000000 (a fill adds rows; `down` and `up` first to start over)
sh scale.sh fill --txns 300000
sh scale.sh stats            # table sizes
sh scale.sh time             # the timing table (add --plans for the EXPLAIN output)
sh scale.sh top              # slowest statements seen

# 3. Many people at once (needs the data above; the app starts in about 15 s)
sh scale.sh web-up
sh scale.sh load run --users 5,20,50 --seconds 60

# 4. Big uploads: statements of 238 pages (about 2,600 rows each), two at the same time, then four
sh scale.sh load uploads --concurrency 2 --pages 238
sh scale.sh load uploads --concurrency 4 --pages 238

# 5. The assistant worker with a fake model (0.4 s pretend wait per call; FAKE_LLM_SECONDS changes it)
sh scale.sh assistant --rows 5000 --parallel 4

sh scale.sh web-down         # stop the scratch app
sh scale.sh down             # when finished: deletes the database, its volume, the app and its passwords
```

Do not press Ctrl+C during a `fill`: it prints only at the end. `sudo` is needed for Docker; run with `sudo env ...` if a variable has to be passed.

## Reading the results

- **`time`**: each row is one screen's query, as the app's own login under row-level security. Look for a query whose time grows faster than the
  rows (compare 300k with 1M), a `SEQ SCAN` flag on a big table, and the "whole queue" row, which is what the Review screen downloads.
- **`load run`**: one table per phase (people at once) with count, errors, p50, p95, p99 and worst latency per request, and a verdict. The limits are
  p95 at most 1,500 ms and errors at most 1%. The first phase that fails is where the app starts to lag on this server. The mix is the screens a CA
  uses most (review queue, statements, ledgers, parties, reports); a request the app answers with an error on the first try is reported and left out,
  so a wrong path does not pass for slowness. People think 1 to 4 s between requests, so 50 people is far fewer than 50 requests a second.
- **`load uploads`**: one line per upload (size, rows, HTTP status, seconds, rows saved) and a `WRONG` flag if the job did not succeed or saved a different
  number of rows than the statement printed. Watch the scratch app's memory peak in the summary: it was 1.7 GB for a 238-page statement before the
  extractor released pages, and should now be a small fraction of that.
- **`assistant`**: rows read per second with N batches at once, and how many went straight into the books. The fake model is instant, so this is the app's own
  cost (claiming, applying, posting), not the provider's.
- **Peaks**: the last block of every run lists each container's highest CPU and memory. The live containers (not named `autoca-scale-*`) are the ones to
  look at for harm: their memory should not climb and their CPU should stay low.

## What this does not tell you

It measures this server (a t3.small with a shared, credit-limited CPU) with a scratch app capped to leave room for the live one, so it understates what the
live app could use and overstates how much a test may take. The browser's own time (page load, rendering a long list) is not measured here: the Review
screen downloads its whole queue, so compare the "review queue (500)" row with how long that screen takes in a real browser.
