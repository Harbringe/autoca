# Keeping provider keys in AWS Parameter Store

The server's settings live in `.env.prod`. Provider keys (the OpenAI key, storage keys) can instead be kept in AWS
Systems Manager **Parameter Store**, encrypted, and are copied into `.env.prod` automatically at every deploy.
Rotating a key becomes: change the parameter in AWS, deploy.

Nothing about GitHub changes. GitHub still holds only what CI and deploy need; it never sees these keys.

## What lives there

Any setting the app knows. Create a parameter named `/autoca/prod/<SETTING_NAME>` and its value is written into
`.env.prod` at the next deploy, replacing what was there. "Knows" means the name is listed in `deploy/prod.env.example` (or
is already in the server's `.env.prod`); a made-up name is ignored with a line in the deploy log, so a new setting is added
to that file first, in a reviewed change. Names that change how a process starts (`LD_*`, `PYTHON*`, `PATH`,
`DJANGO_SETTINGS_MODULE`, `DEBUG`, `AWS_*`, `COMPOSE_*`, `DOCKER_*`) are refused outright. Use **SecureString** for anything secret and
**String** for plain settings such as `LLM_MODEL` or `LLM_BATCH_SIZE`.

**Seed-only settings.** The three permanent keys (`KMS_LOCAL_MASTER_KEY`, `BLIND_INDEX_KEY`, `DJANGO_SECRET_KEY`) and
the web role's `DATABASE_URL` are different: changing one loses stored data or signs everyone out. A parameter may
*fill one in when the server has none* (a new server, or recovery after a lost file) but never replaces a value the
server already has. If the two differ, the deploy log says so by name and keeps the server's. Storing them here is
therefore a safe backup of them, which the database dump deliberately is not.

The database **owner** and bootstrap credentials (`DATABASE_OWNER_URL`, `POSTGRES_*`, `AUTOCA_*_PASSWORD`, anything with OWNER or POSTGRES in the name) are
never taken from Parameter Store: they stay in `.env.owner` and `.env.db`, apart from the web process on purpose.
`PARAMETER_PREFIX` and `PARAMETER_REGION` cannot be set from a parameter. Empty values and values with a line break are
ignored.

## One-time setup (you, in the AWS console)

**1. Let the server read its own parameters.** IAM -> Roles -> the role attached to the server -> Add permissions ->
Create inline policy -> JSON, name it `autoca-read-parameters`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"],
      "Resource": [
        "arn:aws:ssm:ap-south-1:000246635189:parameter/autoca/prod",
        "arn:aws:ssm:ap-south-1:000246635189:parameter/autoca/prod/*"
      ]
    }
  ]
}
```

It can read this one path and nothing else, and cannot write or delete. (The web container shares this role, so keep
the path narrow and keep the three permanent keys out of it, as above.) Parameters encrypted with the default
`aws/ssm` key need no extra key permission. If you choose your own KMS key instead, also allow `kms:Decrypt` on it.

**2. Create each parameter.** Systems Manager -> Parameter Store -> Create parameter:

- Name: `/autoca/prod/LLM_API_KEY`
- Type: **SecureString**, key: the default `alias/aws/ssm`
- Value: the key. Paste it only into that box, never into chat or a file in the repository.

Repeat for `/autoca/prod/LLM_MODEL` (value `gpt-6-luna`, type String is fine) and for any other setting you want managed here.

Whoever may *write* parameters is whoever may set the app's settings, so give `ssm:PutParameter` on `/autoca/prod/*` to
the administrators only.

## Importing a whole .env file at once

Instead of creating parameters one by one, `deploy/import_env.py` reads an `.env` file and creates them all. Run it in
**AWS CloudShell** (the `>_` icon in the console toolbar; already signed in, Python and boto3 included), region Mumbai:

1. Actions -> Upload file: `deploy/import_env.py`, and your env file (call it `env.txt`).
2. `python3 import_env.py env.txt` shows what it would do and writes nothing.
3. `python3 import_env.py env.txt --apply` creates `/autoca/prod/NAME` for each setting, as a SecureString.
4. `rm env.txt` when done.

It prints only names, never values. A parameter that already exists is left alone unless you add `--overwrite`. Comments,
blank and empty lines, and the names the server refuses (above) are skipped and listed. Settings the server does not
know are created but ignored at deploy with a line in the log until they are added to `deploy/prod.env.example`.

## Using it

Deploy as usual. `deploy/deploy.sh` runs `deploy/pull-secrets.sh` first, which prints for example:

    pull-secrets: updated from Parameter Store: LLM_API_KEY LLM_MODEL

and never prints a value. A setting that is not in Parameter Store keeps whatever `.env.prod` already has, so you can
move settings over one at a time. If Parameter Store cannot be reached, for instance the policy above is missing, it
says so and the deploy goes on with the settings already on the server; it never fails a deploy.

To rotate a key: edit the parameter (Edit -> new value -> Save), then deploy. To check what is set without showing
values: Parameter Store lists the names, and `ac logs` shows the one-line summary above after each deploy.

`deploy/set-env.sh KEY` still works for a setting you have not moved. If both exist, Parameter Store wins at the next
deploy, because it is the source of truth for the names it holds.

## Not yet in effect until

- the inline policy above is attached, and the parameters are created; and
- a deploy has run **twice** after this change reached `prod` (the first deploy runs the previous `deploy.sh`, which does
  not yet know about the pull).
