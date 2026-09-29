# Rebuild production (switch.berlin) on a new hosting account

Use this runbook to bring switch.berlin back on a fresh server after the hosting
account is gone (sb-ik76: Hetzner cancelled the account 2026-09-09; the VPS and
its Storage Box backups went with it). Target: about one hour, top to bottom.

Every step ends with a **Done when** line. Do not start a step until the previous
one's Done-when holds.

**Assumed data path: fresh database.** The old box (`128.140.56.30`) is never
touched by this runbook. The site comes back empty except for the superuser;
events come back through the Track A collector (`sb-7wzb`). If the human rules
that old production data is worth an extraction attempt (sb-ik76, open ruling 3),
that happens outside this runbook, before step 9.

**Assumed on your machine** (check before step 1):

- Your personal SSH keypair: `ssh-keygen -lf ~/.ssh/id_ed25519_personal.pub` prints a fingerprint.
- An authenticated GitHub CLI: `gh auth status` shows a logged-in `jsnyde0` account.

What survived and is reused as-is: the domain (INWX), DNS (Cloudflare), the
GitHub repo with its Actions secrets, `infra/cloud-init.yaml`, the deploy workflow.

---

## Inventory — every secret and every manual click

Read this first; gather what you can before step 1.

### Secrets

| Secret | Where it goes | Where the value comes from | Step |
|---|---|---|---|
| Hosting provider API token | provider CLI context on your machine | provider console → API tokens (new account) | 3 |
| Deploy SSH key (private half) | GitHub secret `VPS_SSH_KEY` | generated fresh in step 2 | 2, 8 |
| New server IPv4 | GitHub secret `VPS_HOST` | provider CLI output | 3, 8 |
| `REQUESTY_API_KEY` | GitHub secret `REQUESTY_API_KEY` (**new**, not set today) | Requesty dashboard → API keys | 8 |
| Object-storage key ID | `/etc/kb-backup/env` `AWS_ACCESS_KEY_ID` | Backblaze B2 → Application Keys | 6, 7 |
| Object-storage secret key | `/etc/kb-backup/env` `AWS_SECRET_ACCESS_KEY` | Backblaze B2 → Application Keys (shown once) | 6, 7 |
| restic repository URL | `/etc/kb-backup/env` `RESTIC_REPOSITORY` | built from the B2 bucket's S3 endpoint + bucket name | 6, 7 |
| restic password | `/etc/kb-backup/env` `RESTIC_PASSWORD` | your local repo `.env` → `RESTIC_ENCRYPTION_PASSWORD` (or generate: `openssl rand -hex 32`, then store it in `.env` too) | 7 |
| Telegram bot token | `/etc/kb-backup/env` `TELEGRAM_BOT_TOKEN` | same value as GitHub secret `TELEGRAM_BOT_TOKEN` (local `.env`) | 7 |
| Telegram operator chat ID | `/etc/kb-backup/env` `TELEGRAM_OPERATOR_CHAT_ID` | your personal Telegram user ID (unchanged from the old host) | 7 |
| healthchecks.io ping URL | `/etc/kb-backup/env` `HEALTHCHECKS_PING_URL` | healthchecks.io → your check (reuse the old check's URL if it still exists) | 7 |

Already set in GitHub and reused unchanged (verify they exist in step 8):
`SECRET_KEY`, `DATABASE_URL`, `IMPRESSUM_NAME`, `IMPRESSUM_ADDRESS`,
`IMPRESSUM_EMAIL`, `IMPRESSUM_PHONE`, `RESPONSIBLE_PERSON_NAME`,
`RESPONSIBLE_PERSON_ADDRESS`, `DSA_CONTACT_EMAIL`, `TELEGRAM_BOT_TOKEN`,
`FIRECRAWL_API_KEY`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`,
`DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`,
`DJANGO_SUPERUSER_PASSWORD`, `VPS_USER` (= `switch`).

### Manual clicks (browser)

1. **Cloudflare** → switch.berlin → DNS → Records: lower TTL on 4 records (step 1), change their IPs (step 5), raise TTL back (step 10).
2. **Hosting provider console**: sign up / add payment, create an API token (step 3).
3. **Backblaze B2**: sign up, create a private bucket, create an application key limited to that bucket (step 6).
4. **Requesty dashboard**: copy or create an API key (step 8).
5. **healthchecks.io**: confirm the check exists (period 10 min, grace 10 min), copy its ping URL (step 7). If the check is gone, create one following `infra/README.md` § "Human step: create a healthchecks.io dead-man's-switch".

Everything else is a command.

---

## Step 1 — Lower the DNS TTL (Cloudflare)

Current state (read 2026-09-29 from Cloudflare's nameserver): all four records
have TTL **300 s** ("Auto") and still point at the dead box.

| Type | Name | Current value | TTL |
|---|---|---|---|
| A | `switch.berlin` | `128.140.56.30` | 300 |
| AAAA | `switch.berlin` | `2a01:4f8:c014:7cbc::1` | 300 |
| A | `www` | `128.140.56.30` | 300 |
| AAAA | `www` | `2a01:4f8:c014:7cbc::1` | 300 |

Click: Cloudflare → switch.berlin → DNS → Records → edit each of the four
records → TTL **1 min** → Save. Leave proxy status **DNS only** (grey cloud);
Caddy must terminate TLS itself.

Doing this first lets the old 300 s TTL expire while you provision.

```bash
dig +noall +answer @love.ns.cloudflare.com switch.berlin A
dig +noall +answer @love.ns.cloudflare.com www.switch.berlin AAAA
```

**Done when** both lines show TTL `60`.

## Step 2 — Keys in cloud-init

The server's `switch` user gets its SSH keys only from `infra/cloud-init.yaml`
(`users[0].ssh_authorized_keys`). It must hold (a) your own key and (b) a fresh
deploy key for GitHub Actions. The old deploy key's private half is not on the
mac mini, so generate a new pair:

```bash
ssh-keygen -t ed25519 -N "" -C switch-berlin-deploy -f ~/.ssh/switch-berlin-deploy
cat ~/.ssh/switch-berlin-deploy.pub
cat ~/.ssh/id_ed25519_personal.pub
```

Edit `infra/cloud-init.yaml` → `ssh_authorized_keys`: add both public lines
(keep the existing line only if you still hold its private key). The existing
line may be the same personal key: compare key material first and keep one line
per key.

```bash
ssh-keygen -lf ~/.ssh/id_ed25519_personal.pub   # fingerprint of your key
grep -c "$(cut -d' ' -f2 ~/.ssh/id_ed25519_personal.pub)" infra/cloud-init.yaml   # 1 = already listed, do not add again
```

Commit:

```bash
git add infra/cloud-init.yaml
git commit -m "infra: authorize operator + new deploy key for the rebuilt host (sb-ik76)"
```

**Done when** `grep -c 'ssh-ed25519' infra/cloud-init.yaml` prints at least `2`,
and one of those lines ends in `switch-berlin-deploy`.

## Step 3 — Create the server (PROVIDER-SPECIFIC — swap this section only)

Everything outside this step is provider-agnostic. Pick **one** subsection.
Size: 2 vCPU / 4 GB RAM / 40 GB disk, Ubuntu 24.04, EU region.
The old setup used **no** provider-level firewall; `ufw` from cloud-init allows
only 22/80/443. A provider firewall is optional; if you add one, allow the same
three ports inbound.

Record the IPv4 and IPv6 in a scratch note; steps 5 and 8 need them.

### 3a — Hetzner Cloud

Tooling: `brew install hcloud`.

```bash
hcloud context create switch-berlin          # paste the new account's API token
hcloud ssh-key create --name operator \
  --public-key-from-file ~/.ssh/id_ed25519_personal.pub
hcloud server create \
  --name switch-berlin-prod \
  --type cx22 \
  --image ubuntu-24.04 \
  --location fsn1 \
  --ssh-key operator \
  --user-data-from-file infra/cloud-init.yaml
hcloud server ip switch-berlin-prod          # IPv4
hcloud server ip -6 switch-berlin-prod       # IPv6 (prints the ::1 host address)
```

If `cx22` is no longer offered, pick the cheapest shared x86 type with ≥4 GB RAM
(`hcloud server-type list`).

**Done when** `hcloud server list` shows `switch-berlin-prod` `running` with an IPv4.

### 3b — DigitalOcean (alternative)

Tooling: `brew install doctl`.

```bash
doctl auth init                              # paste the new account's API token
doctl compute ssh-key import operator \
  --public-key-file ~/.ssh/id_ed25519_personal.pub
FP=$(doctl compute ssh-key list --format Name,FingerPrint --no-header | awk '$1=="operator"{print $2}')
doctl compute droplet create switch-berlin-prod \
  --image ubuntu-24-04-x64 \
  --size s-2vcpu-4gb \
  --region fra1 \
  --enable-ipv6 \
  --ssh-keys "$FP" \
  --user-data-file infra/cloud-init.yaml \
  --wait
doctl compute droplet get switch-berlin-prod --format PublicIPv4,PublicIPv6
```

**Done when** the last command prints an IPv4 and an IPv6.

## Step 4 — Wait for cloud-init

```bash
IP=<new IPv4>
ssh switch@"$IP" 'test -f /var/lib/cloud/instance/cloud-init.done && echo DONE'
ssh switch@"$IP" 'docker --version && caddy version && restic version && jq --version'
```

Allow 3–5 minutes. Progress: `ssh switch@"$IP" 'tail -f /var/log/cloud-init-output.log'`.

**Done when** the first command prints `DONE` and the second prints four versions.

## Step 5 — Point DNS at the new server (Cloudflare)

Click: edit the four records from step 1 → new IPv4 on both A records, new IPv6
on both AAAA records. Keep TTL 1 min, DNS only.
If the new server has **no IPv6**, **delete** both AAAA records; a stale AAAA
sends IPv6 visitors to the dead box.

```bash
dig +short @love.ns.cloudflare.com switch.berlin A
dig +short @love.ns.cloudflare.com www.switch.berlin A
dig +short @love.ns.cloudflare.com switch.berlin AAAA
dig +short switch.berlin A          # your resolver; may lag up to 5 min
```

**Done when** all four answers show the new addresses (or AAAA is empty on
purpose).

## Step 6 — Off-provider backup target (Backblaze B2)

**Rule: the restic repository must live outside the hosting provider's
account.** The last outage lost the server and its backups together because
both sat in one Hetzner account. B2 is the named default; any S3-compatible
object storage at a different company works (not Hetzner Object Storage or a
Storage Box if the host is Hetzner; not DO Spaces if the host is DigitalOcean).

Clicks, B2:

1. Buckets → Create a Bucket → name e.g. `switch-berlin-restic`, **Private**,
   default encryption on, object lock off.
2. Note the bucket's **Endpoint** (looks like `s3.eu-central-003.backblazeb2.com`).
3. Application Keys → Add a New Application Key → allow access to that bucket
   only, Read and Write. Copy **keyID** and **applicationKey** (shown once).

Your restic repository URL is then:

```
s3:https://<endpoint>/<bucket>
```

**Done when** you hold three values: `RESTIC_REPOSITORY`, `AWS_ACCESS_KEY_ID`
(= keyID), `AWS_SECRET_ACCESS_KEY` (= applicationKey).

## Step 7 — Backup + monitoring on the host

The env file template is `infra/kb-backup-env.template`. It lists every key the
backup, the monitor and both failure alerters read.

```bash
VPS=switch@<new IPv4>

# 7.1 Fill the template locally in a private temp file, never inside the repo.
install -m 0600 infra/kb-backup-env.template /tmp/kb-backup.env
$EDITOR /tmp/kb-backup.env        # replace every REPLACE_ME
grep -c REPLACE_ME /tmp/kb-backup.env   # must print 0

# 7.2 Install the env file (root:switch 0640) and delete the local copy.
ssh "$VPS" 'sudo mkdir -p /etc/kb-backup'
ssh "$VPS" 'sudo install -m 0640 -o root -g switch /dev/stdin /etc/kb-backup/env' < /tmp/kb-backup.env
rm -f /tmp/kb-backup.env

# 7.3 Install scripts + units.
scp infra/kb-backup.sh infra/kb-monitor.sh "$VPS":/tmp/
scp infra/kb-backup.service infra/kb-backup.timer infra/kb-backup-alert.service \
    infra/kb-monitor.service infra/kb-monitor.timer infra/kb-monitor-alert.service "$VPS":/tmp/
ssh "$VPS" 'sudo install -o root -g root -m 0755 /tmp/kb-backup.sh /tmp/kb-monitor.sh /usr/local/bin/ &&
  for u in kb-backup.service kb-backup.timer kb-backup-alert.service kb-monitor.service kb-monitor.timer kb-monitor-alert.service; do
    sudo install -o root -g root -m 0644 /tmp/$u /etc/systemd/system/$u; done'

# 7.4 State dirs owned by the service user (root-owned state silently breaks the monitor).
ssh "$VPS" 'sudo install -d -o switch -g switch /var/tmp/kb-monitor /var/tmp/kb-backup'

# 7.5 Initialise the restic repository (one time per new bucket).
ssh "$VPS" 'sudo bash -c "set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- restic init"'

# 7.6 Enable timers.
ssh "$VPS" 'sudo systemctl daemon-reload && sudo systemctl enable --now kb-backup.timer kb-monitor.timer'

# 7.7 Prove the alert channel: two Telegram messages should arrive.
ssh "$VPS" 'sudo bash -c "set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-backup.sh --test-alert"'
ssh "$VPS" 'sudo bash -c "set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-monitor.sh --simulate-backup-stale"'
```

**Done when** `restic init` printed `created restic repository`,
`ssh "$VPS" 'systemctl list-timers kb-backup.timer kb-monitor.timer'` lists both,
and Telegram received the kb-backup canary and the `BACKUP alert … (simulated)`
message.

If the canary never arrives, stop and verify `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_OPERATOR_CHAT_ID` before going on: both must be in
`/etc/kb-backup/env` on the host. The token is also the GitHub secret
`TELEGRAM_BOT_TOKEN` (`gh secret list -R jsnyde0/switch-berlin` shows names
only; never print a value); set for real under `sb-6ep` (closed 2026-05-08).
The chat id lives only in that env file, not in GitHub.

What now pages you (all via Telegram):

- **Backup failed** — `kb-backup-alert.service` fires on any non-zero exit.
- **Backup stale** — `kb-monitor` pages once when the last successful db backup
  is older than `BACKUP_MAX_AGE_HOURS` (26 h), or when none has succeeded within
  26 h of the monitor first looking; one recovery note when backups resume.
  This catches the cases the OnFailure hook cannot: timer never enabled,
  placeholder target, the alerter itself broken.
- **Backup size regression / near-empty dump** — unchanged (sb-336, sb-omx).
- **Disk ≥ 85 %, `/healthz` down 3 ticks** — unchanged.
- **Whole host dead** — healthchecks.io stops receiving pings.

## Step 8 — GitHub secrets, then re-enable deploys

The deploy job runs only when the repository variable `DEPLOY_ENABLED` is
`true` (`.github/workflows/deploy.yml`, job `if:`). While there is no host it is
unset or `false`, so pushes to main skip the job instead of failing on ssh.

```bash
gh auth switch --user jsnyde0
R=jsnyde0/switch-berlin
printf '%s' '<new IPv4>' | gh secret set VPS_HOST -R $R
gh secret set VPS_SSH_KEY -R $R < ~/.ssh/switch-berlin-deploy
gh secret set REQUESTY_API_KEY -R $R          # prompts; paste, value not echoed
gh secret list -R $R
```

(`OPENAI_API_KEY` and `OPENAI_MODEL_NAME` are leftovers the app no longer reads.)

**Done when** `gh secret list -R $R` contains every name from the Inventory's
"already set" line plus `VPS_HOST`, `VPS_SSH_KEY`, `REQUESTY_API_KEY`.

```bash
gh variable set DEPLOY_ENABLED -R $R --body true
gh workflow run deploy.yml -R $R --ref main
sleep 5; gh run watch -R $R "$(gh run list -R $R --workflow deploy.yml -L 1 --json databaseId -q '.[0].databaseId')"
```

**Done when** the run ends `completed` with conclusion `success`
(`gh run list -R $R --workflow deploy.yml -L 1`).

To turn deploys off again (host gone, maintenance): `gh variable set DEPLOY_ENABLED -R $R --body false`.

## Step 9 — Verify the site and the first backup

```bash
curl -sI https://switch.berlin/ | head -1                      # HTTP/2 200
curl -s -o /dev/null -w '%{http_code}\n' https://switch.berlin/healthz   # 200
curl -sI https://www.switch.berlin/ | head -3                  # 308 → https://switch.berlin/
openssl s_client -connect switch.berlin:443 -servername switch.berlin </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer                                # Let's Encrypt
ssh "$VPS" 'sudo bash -c "set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- restic snapshots --tag db"'
ssh "$VPS" 'sudo runuser -u switch -- /usr/local/bin/kb-monitor.sh --check-backup'
```

If TLS fails right after step 5, Caddy may still be retrying ACME; wait two
minutes or `ssh "$VPS" 'sudo systemctl reload caddy'`.

The last deploy step triggers `kb-backup.service`, so a db snapshot should
already exist.

**Done when** `/` returns 200, `/healthz` returns 200, the issuer is Let's
Encrypt, `restic snapshots --tag db` lists at least one snapshot, and
`--check-backup` prints `kb-monitor: last successful backup 0h ago (max 26h)`
and exits 0.

## Step 10 — Raise the DNS TTL back

Click: Cloudflare → the four records → TTL **Auto** → Save.

```bash
dig +noall +answer @love.ns.cloudflare.com switch.berlin A
```

**Done when** the TTL reads `300`.

## Step 11 — Record the rebuild

- Update `infra/README.md`: in the deploy-channel secrets table, replace the
  `VPS_HOST` row's `_none live_` with the new IPv4, provider and server ID.
- Note on sb-ik76: new provider, IPv4, date, the green deploy run URL, the first
  restic snapshot ID.

**Done when** sb-ik76's notes carry those five facts and the `VPS_HOST` row
in `infra/README.md` shows the new IPv4.

---

## After the rebuild

- The site is empty: superuser only. Events come back through the collector
  (Track A, `sb-7wzb`).
- Restore drill: the restore shape in
  `docs/incident-2026-05-12-data-loss-restore-plan.md` applies unchanged; the
  restic commands in `infra/README.md` → "Operations" work against the new
  target because they read `RESTIC_REPOSITORY` from `/etc/kb-backup/env`.
