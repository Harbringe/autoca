# Running the app on your PC against the live database

This is for looking at real data with changes you have not shipped yet. **Everything you do in the app this way is real:** it
reads and writes the clients' actual books. The database is backed up, but a mistake is still a mistake in front of a client.
For anything experimental, use the development settings and a local database instead.

## How it is wired

```
your PC                                   the server (EC2)
 browser -> vite :5173 -> runserver :8000
                              |
                          localhost:5433  ==== SSM tunnel ====>  127.0.0.1:5432 -> the db container
```

- Nothing is opened to the internet. The database port is published on the **server's loopback only**
  (`compose.prod.yaml`, `127.0.0.1:5432:5432`), so only a process on the server, or an SSM session you start with your own AWS
  login, can reach it. The security group is untouched.
- The tunnel is an AWS Systems Manager Session Manager port-forwarding session. It is logged in CloudTrail and ends when you
  close the window.

## One-time setup

1. **Install** the AWS CLI and the Session Manager plugin, then open a new window:
   `winget install Amazon.AWSCLI` and `winget install Amazon.SessionManagerPlugin`. Run `aws configure sso` (or
   `aws configure`) with **your own** AWS user, in region `ap-south-1`.
2. **Permission.** Your AWS user needs to start a port-forwarding session on the server and nothing else. Attach this to it:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "ssm:StartSession",
         "Resource": [
           "arn:aws:ec2:ap-south-1:<ACCOUNT_ID>:instance/<INSTANCE_ID>",
           "arn:aws:ssm:ap-south-1::document/AWS-StartPortForwardingSession"
         ]
       },
       { "Effect": "Allow", "Action": ["ssm:TerminateSession", "ssm:ResumeSession"], "Resource": "arn:aws:ssm:*:*:session/${aws:username}-*" }
     ]
   }
   ```
3. **The database port must be published.** That is the `ports:` line in `compose.prod.yaml`; it takes effect with the next
   deploy (`git push origin dev:main dev:prod`, once CI is green). Until then the tunnel connects and is refused.
   **To read the three values in step 5 you also need a shell on the server for a few minutes.** Add this document to the `Resource` list
   of the first statement, and **remove it again afterwards**: a shell on the server can read and change everything.
   `"arn:aws:ssm:ap-south-1::document/SSM-SessionManagerRunShell"`
4. **Tell the script which server.** Set `AUTOCA_INSTANCE_ID` to the instance id (a Windows user variable is enough). It is not kept in the code.
5. **Fill in `.env.live`.** Copy `deploy/live.env.example` to `.env.live` (git ignores it). Take the values from the server with a
   Session Manager shell, never by pasting them into a chat or an email:
   - `DATABASE_URL`: the `DATABASE_URL` line of `.env.prod`, with the host and port changed to `localhost:5433`.
   - `KMS_LOCAL_MASTER_KEY` and `BLIND_INDEX_KEY`: the same lines of `.env.prod`.

   **These two keys decrypt every client's names, GSTINs and bank account numbers. Having them on this PC is the real cost of
   this setup.** Keep the disk encrypted (BitLocker), do not sync the project folder to a cloud drive, and delete `.env.live` when
   you stop needing it.

## Each time

```powershell
scripts\live-tunnel.ps1     # window 1: leave it open
scripts\run-live.ps1        # window 2: the API on http://localhost:8000
cd web; npm run dev         # window 3: http://localhost:5173, sign in with your real account
```

## What stops you hurting yourself

- With these settings only `runserver`, `check`, `showmigrations`, `diffsettings` and `shell` run. `migrate`, `test`,
  `loaddata`, `flush` and the background assistant are refused (`config/settings/live.py`).
- Running the tests in a window started with `run-live.ps1` is refused as well, because the suite creates and drops a database
  on whatever server it is pointed at.
- Your local code can be ahead of the live database. A field added on `dev` that is not migrated on the server fails with a
  database error on the page that uses it. That is expected until the change is deployed.
- Whatever is in the project's own `.env` (it may hold a real model key), the live settings use a stub in place of the model and a
  storage adapter that refuses every read and write. Live rows are never sent to a model from this PC, and no file is written
  that the server's bucket does not have. Pages that need a file show an error here; open them on the live site.
