# Keeping provider keys in AWS Parameter Store

The server's settings live in `.env.prod`. Provider keys (the OpenAI key, storage keys) can instead be kept in AWS
Systems Manager **Parameter Store**, encrypted, and are copied into `.env.prod` automatically at every deploy.
Rotating a key becomes: change the parameter in AWS, deploy.

Nothing about GitHub changes. GitHub still holds only what CI and deploy need; it never sees these keys.

## What may live there, and what never does

Only these names are read (`MANAGED` in `integrations/paramstore.py`):

`LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `GROQ_API_KEY`, `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY`

Anything else under the path is ignored. **Do not** put `KMS_LOCAL_MASTER_KEY`, `BLIND_INDEX_KEY`, `DJANGO_SECRET_KEY`
or a database password there: losing or changing one loses stored data or signs everyone out, so the deploy
will not take them from a parameter even if they are created. They stay in `.env.prod`, backed up as described in
`docs/AWS.md`.

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

Repeat for `/autoca/prod/LLM_MODEL` (value `gpt-6-luna`, type String is fine) and any other setting above.

Whoever may *write* parameters is whoever may set the app's keys, so give `ssm:PutParameter` on `/autoca/prod/*` to
the administrators only.

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
