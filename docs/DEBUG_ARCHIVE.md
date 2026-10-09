# Debug archive

A short-lived record of what was read from a file and what the model replied, so a bad reading can be debugged by looking at
it instead of guessing. **It holds client data** (the extracted text is not masked), so it is off by default, lives in a bucket
of its own, and expires by itself.

## What is kept

```
dev/2026-10-10/shri-narayan-trading-co-1234abcd/invoice/023145-invoice-3938-pdf/
    meta.json              purpose, document, client id, started, seconds, number of model calls, how it ended
    extracted.txt          the text read out of the file, before the model (unmasked)
    call-1.request.json    what was sent to the model (masked: exactly what left the building) and max_tokens
    call-1.response.txt    the model's reply exactly as it came, before anything parsed it
    call-1.response.json   the same, parsed and indented (absent when the reply is not valid JSON)
    call-1.meta.json       model, tokens, time, whether it parsed, or the error
    outcome.json           what the app made of it (kept fields, arithmetic checks, tier, kind)
```

Purposes: `invoice` (a purchase or sales invoice upload), `statement` (a bank statement upload), `classify` (one batch of
statement rows; the folder also has `shape.json`, which rows the model answered or skipped and which fields it left out, and
`applied.json`, per row what the model said beside what was stored), `other` (a model call made outside any of these).

Page images are never kept, only their count. File names and client names appear in the folder names; GSTINs, PANs and
account numbers never do.

## One-time setup (you, in the AWS console)

1. **Create a bucket** for it (S3, region `ap-south-1`, block all public access, default encryption on). Name it as you like.
   It is separate from the files bucket and from the backups bucket on purpose: the files bucket is readable by the server and
   holds the clients' documents, and nothing here should ever be reachable from there.
2. **Expiry after 10 days.** Bucket, Management, Lifecycle rules, create a rule for the whole bucket, "Expire current versions
   of objects" after **10 days**. Leave versioning off (an old version would outlive the rule).
3. **The server may only write.** On the server's role (the one named in `docs/AWS.md`) add an inline policy:
   ```json
   { "Version": "2012-10-17", "Statement": [ { "Effect": "Allow", "Action": "s3:PutObject", "Resource": "arn:aws:s3:::<DEBUG_BUCKET>/*" } ] }
   ```
   No read, no list, no delete: a compromised web process can add to it and learn nothing from it.
4. **Only you may read.** On your own IAM user add the same bucket with `s3:GetObject` and `s3:ListBucket`
   (`arn:aws:s3:::<DEBUG_BUCKET>` and `/*`), and `s3:PutObject` if you run the app on your PC with the archive on. Nobody else
   gets a policy naming this bucket.
5. **Turn it on** in the server's settings (and in `.env.live` for the PC):
   ```
   DEBUG_ARCHIVE_ENABLED=1
   DEBUG_ARCHIVE_BUCKET=<DEBUG_BUCKET>
   DEBUG_ARCHIVE_REGION=ap-south-1
   DEBUG_ARCHIVE_PREFIX=dev
   ```
   Then restart the web and assistant containers. Turning it on in production is a decision to make on purpose: from then on
   every uploaded file's text and every model reply is filed for 10 days.

## Looking at it

```
aws s3 ls s3://<DEBUG_BUCKET>/dev/2026-10-10/ --recursive
aws s3 cp s3://<DEBUG_BUCKET>/dev/2026-10-10/<client>/invoice/<time>-<doc>/ . --recursive
```

## Safeguards in the code

- Every object is written encrypted (S3's own encryption, or the KMS key in `DEBUG_ARCHIVE_KMS_KEY_ID`; with a KMS key, your user and the
  server role also need `kms:GenerateDataKey` / `kms:Decrypt` on it).
- Off unless both `DEBUG_ARCHIVE_ENABLED` and `DEBUG_ARCHIVE_BUCKET` are set.
- Writes happen in a background thread and any failure is logged without content; an upload or a classification never fails
  because the archive could not be written.
- The only thing a file name or a client name can do is appear in a folder name; the key never carries an identifier.
