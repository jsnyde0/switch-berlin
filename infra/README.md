# Switch Berlin — Production Infrastructure

This directory holds infrastructure-as-code for the production deploy target
(sb-6nq epic).

## Files

| File | Purpose |
|---|---|
| `Caddyfile` | Host-installed Caddy config: TLS termination + `www → apex` redirect (308). Mirrored into `cloud-init.yaml` for first-boot provisioning. |
| `cloud-init.yaml` | Provider-agnostic first-boot config for the production VPS (any cloud-init host). Creates `switch` deploy user, installs Docker + Caddy, sets up `/opt/switch-berlin/`, configures UFW firewall. |
| `../.github/workflows/deploy.yml` | GH Actions deploy workflow. Runs only when the repo variable `DEPLOY_ENABLED` is `true`. |
| `kb-backup-env.template` | Every key of the host's `/etc/kb-backup/env` (backup, monitor, alerters), with `REPLACE_ME` placeholders. |
| `test-kb-backup.sh`, `test-kb-monitor.sh` | Local tests for the two scripts: `bash infra/test-kb-backup.sh && bash infra/test-kb-monitor.sh`. |

**Rebuilding production from scratch:** follow
[`docs/runbooks/rebuild-production.md`](../docs/runbooks/rebuild-production.md).
It is the canonical end-to-end order (DNS, server, backups, secrets, deploy);
the sections below are reference detail.

## VPS provisioning runbook (sb-6nq.1)

Original Hetzner provisioning. The provider-swappable version is step 3 of
`docs/runbooks/rebuild-production.md`.

Tooling: `hcloud` CLI (`brew install hcloud`).

```bash
# 1. Auth (one-time per machine)
hcloud context create switch-berlin   # paste API token when prompted

# 2. Upload SSH key (one-time)
hcloud ssh-key create \
  --name jonat-personal \
  --public-key-from-file ~/.ssh/id_ed25519_personal.pub

# 3. Create CX22 in Falkenstein with cloud-init
hcloud server create \
  --name switch-berlin-prod \
  --type cx22 \
  --image ubuntu-24.04 \
  --location fsn1 \
  --ssh-key jonat-personal \
  --user-data-from-file infra/cloud-init.yaml

# 4. Get IPs
hcloud server ip switch-berlin-prod        # IPv4
hcloud server describe switch-berlin-prod  # full details inc. IPv6
```

After step 3, cloud-init runs for ~2-4 min. Watch progress with:

```bash
ssh switch@<IP> 'tail -f /var/log/cloud-init-output.log'
```

When `/var/lib/cloud/instance/cloud-init.done` exists, provisioning is complete.

## DNS (Cloudflare DNS-only)

For `switch.berlin` zone in Cloudflare dashboard:

| Type | Name | Value | Proxy |
|---|---|---|---|
| A | `@` (apex) | VPS IPv4 | DNS only (grey cloud) |
| AAAA | `@` (apex) | VPS IPv6 | DNS only (grey cloud) |
| A | `www` | VPS IPv4 | DNS only (grey cloud) |
| AAAA | `www` | VPS IPv6 | DNS only (grey cloud) |

**Critical:** proxy must be **off** (grey cloud, not orange). Caddy on Hetzner
terminates TLS directly; Cloudflare proxying would short-circuit Caddy's
Let's Encrypt HTTP-01 challenge and contradict ADR-006 D3's no-CF-TLS stance.

## Acceptance probes (sb-6nq.1)

```bash
# DNS resolution → VPS IP
dig +short switch.berlin A
dig +short www.switch.berlin A

# TLS issuer = Let's Encrypt
openssl s_client -connect switch.berlin:443 -servername switch.berlin </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer

# www → apex 308
curl -sI https://www.switch.berlin/ | head -5

# /opt/switch-berlin/ owned by deploy user
ssh switch@switch.berlin 'stat -c "%U:%G %n" /opt/switch-berlin'
```

## GH Actions secrets & env inventory (sb-6nq.4)

### Secrets (set via `gh secret set <NAME>`, value never echoed)

App secrets — consumed by Django via `.env` rendered on the VPS:

| Name | Source | Notes |
|---|---|---|
| `SECRET_KEY` | repo `.env` | Django session signing key |
| `DATABASE_URL` | repo `.env` | `postgres://postgres:postgres@db:5432/postgres` (refine in slot-5 if rotating db pw) |
| `IMPRESSUM_NAME` | repo `.env` | Operator legal name |
| `IMPRESSUM_ADDRESS` | repo `.env` | Operator legal address |
| `IMPRESSUM_EMAIL` | repo `.env` | `kinkybubbles@protonmail.com` per ADR-006 D3 (rotated by sb-9hw) |
| `IMPRESSUM_PHONE` | repo `.env` (empty) | Optional contact channel |
| `RESPONSIBLE_PERSON_NAME` | empty | Falls back to `IMPRESSUM_NAME` (settings.py) |
| `RESPONSIBLE_PERSON_ADDRESS` | empty | Falls back to `IMPRESSUM_ADDRESS` (settings.py) |
| `DSA_CONTACT_EMAIL` | repo `.env` | Falls back to `IMPRESSUM_EMAIL` if empty |
| `TELEGRAM_BOT_TOKEN` | BotFather bot token | Real value set 2026-05-08 (`sb-6ep`, closed). Check presence with `gh secret list` (names only); never print the value. |
| `FIRECRAWL_API_KEY` | empty placeholder | Not yet referenced in code |
| `REQUESTY_API_KEY` | Requesty dashboard | LLM router key for event extraction (`ingestion/extraction.py`); required |
| `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile | Bot check on forms |
| `DJANGO_SUPERUSER_USERNAME`, `_EMAIL`, `_PASSWORD` | repo `.env` | `bin/init.sh` creates this superuser on a fresh db |

Deploy-channel secrets — consumed by the workflow itself:

| Name | Value | Notes |
|---|---|---|
| `VPS_HOST` | _none live_ | IPv4 of `switch-berlin-prod`. The Hetzner host `128.140.56.30` was lost with the account (sb-ik76); set on rebuild. |
| `VPS_USER` | `switch` | Deploy user created by `cloud-init.yaml` |
| `VPS_SSH_KEY` | `~/.ssh/switch-berlin-deploy` (private) | Pubkey installed on VPS as `switch`'s `authorized_keys` |

### Non-secret workflow env (declared in `.github/workflows/deploy.yml`)

| Name | Value |
|---|---|
| `ALLOWED_HOSTS` | `switch.berlin,www.switch.berlin` |
| `CSRF_TRUSTED_ORIGINS` | `https://switch.berlin,https://www.switch.berlin` |
| `DEBUG` | `False` |
| `DJANGO_SETTINGS_MODULE` | `a_core.settings` |
| `SITE_URL` | `https://switch.berlin` |

Repository variable (not a secret): `DEPLOY_ENABLED` — `true` runs the deploy
job; anything else skips it. `gh variable set DEPLOY_ENABLED --body true|false`.

## Monitoring/alerting subsystem provisioning (kb-monitor)

After the backup subsystem is provisioned (see below), install the monitoring subsystem:

```bash
# Run from the repo root on your local machine.
# Substitute the real VPS IP or hostname.
VPS=switch@switch.berlin

# 1. Install the monitor script
scp infra/kb-monitor.sh "$VPS":/tmp/kb-monitor.sh
ssh "$VPS" 'sudo install -o root -g root -m 0755 /tmp/kb-monitor.sh /usr/local/bin/kb-monitor.sh'

# 2. Install the systemd units (monitor service + timer + OnFailure alerter)
scp infra/kb-monitor.service infra/kb-monitor.timer infra/kb-monitor-alert.service "$VPS":/tmp/
ssh "$VPS" 'sudo install -o root -g root -m 0644 /tmp/kb-monitor.service       /etc/systemd/system/kb-monitor.service'
ssh "$VPS" 'sudo install -o root -g root -m 0644 /tmp/kb-monitor.timer         /etc/systemd/system/kb-monitor.timer'
ssh "$VPS" 'sudo install -o root -g root -m 0644 /tmp/kb-monitor-alert.service /etc/systemd/system/kb-monitor-alert.service'

# 3. Create and own the state directory as the service user
#    The timer runs as switch:switch; root-owned state files will cause silent write failures.
ssh "$VPS" 'sudo mkdir -p /var/tmp/kb-monitor'
ssh "$VPS" 'sudo chown switch:switch /var/tmp/kb-monitor'

# 4. Reload and enable
ssh "$VPS" 'sudo systemctl daemon-reload && sudo systemctl enable --now kb-monitor.timer'

# 5. Verify the timer is active
ssh "$VPS" 'systemctl list-timers kb-monitor.timer'
```

### Additional env vars (append to /etc/kb-backup/env)

The monitor reuses the existing `/etc/kb-backup/env` file (already contains `TELEGRAM_BOT_TOKEN` and `TELEGRAM_OPERATOR_CHAT_ID`). Append the monitor-specific vars:

```bash
ssh "$VPS" 'sudo tee -a /etc/kb-backup/env > /dev/null <<EOF
DISK_ALERT_THRESHOLD_PERCENT=85
HEALTHCHECKS_PING_URL=<paste ping URL from healthchecks.io — see below>
EOF'
```

Optional overrides (defaults shown):

| Key | Default | Notes |
|---|---|---|
| `DISK_ALERT_THRESHOLD_PERCENT` | `85` | Alert when / reaches this % |
| `HEALTHZ_URL` | `https://switch.berlin/healthz` | Public healthcheck URL (through Caddy). Direct-to-app on `127.0.0.1:8000` fails `ALLOWED_HOSTS` (400) then SSL-redirects (301) before the view runs; the public URL exercises the real user path. |
| `UPTIME_FAILURE_THRESHOLD` | `3` | Consecutive failing ticks before paging |
| `HEALTHCHECKS_PING_URL` | _(unset)_ | Dead-man's-switch; see step below |
| `BACKUP_MAX_AGE_HOURS` | `26` | Page when kb-backup's last successful db snapshot (`/var/tmp/kb-backup/last-success`) is older than this, or none has landed within this window of the monitor first looking |

### Human step: create a healthchecks.io dead-man's-switch

1. Create a free account at [https://healthchecks.io](https://healthchecks.io).
2. Add a new check; set period = **10 minutes**, grace = **10 minutes**.
3. Copy the **Ping URL** (looks like `https://hc-ping.com/<uuid>`).
4. Paste it as `HEALTHCHECKS_PING_URL` in `/etc/kb-backup/env` on the VPS.

This lets healthchecks.io detect total host death (no pings for >10 min = alert).

### Verify the alert channel

```bash
ssh "$VPS" 'sudo bash -c "set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-monitor.sh --test-alert"'
```

A successful run sends one Telegram message (`[Switch Berlin] kb-monitor canary … — alert channel wired.`) and exits 0.

### Monitoring subsystem files on `switch-berlin-prod`

| Path | Owner / mode | Purpose |
|---|---|---|
| `/usr/local/bin/kb-monitor.sh` | `root:root 0755` | Per-tick disk + healthz + backup-freshness + dead-man's-switch checks. State under `/var/tmp/kb-monitor/`. Flags: `--test-alert`, `--check-disk`, `--check-healthz`, `--check-backup`, `--simulate-full-disk`, `--simulate-down`, `--simulate-backup-stale`, `--service-failed-alert`. |
| `/etc/systemd/system/kb-monitor.service` | `root:root 0644` | `Type=oneshot`, runs as `switch:switch`. `OnFailure=kb-monitor-alert.service`. |
| `/etc/systemd/system/kb-monitor.timer` | `root:root 0644` | `OnCalendar=*:0/5` (every 5 min), `RandomizedDelaySec=30`, `Persistent=true`. |
| `/etc/systemd/system/kb-monitor-alert.service` | `root:root 0644` | Fires `kb-monitor.sh --service-failed-alert` when the monitor service itself crashes. |

> **WARNING — state-dir ownership footgun:** the timer runs as `switch:switch`. If you run
> `--simulate-*` or any non-`--test-alert` invocation as root, `/var/tmp/kb-monitor/` and its
> state files become root-owned, and the next timer tick (running as `switch`) cannot write the
> failure counter — silently breaking the monitor. Always run ad-hoc or diagnostic invocations
> as the `switch` user:
>
> ```bash
> ssh "$VPS" 'sudo runuser -u switch -- /usr/local/bin/kb-monitor.sh --simulate-down'
> ```
>
> Never run `--simulate-*` / `--check-healthz` / `--check-disk` directly as root on the VPS.

---

## Backup subsystem provisioning (sb-vms + sb-omx)

After `hcloud server create ...` completes and cloud-init has finished (see "VPS provisioning runbook" above), install the backup subsystem files from this repo onto the fresh VPS:

```bash
# Run from the repo root on your local machine.
# Substitute the real VPS IP or hostname.
VPS=switch@switch.berlin

# 1. Install the backup script
scp infra/kb-backup.sh "$VPS":/tmp/kb-backup.sh
ssh "$VPS" 'sudo install -o root -g root -m 0755 /tmp/kb-backup.sh /usr/local/bin/kb-backup.sh'

# 2. Install the systemd units (backup service + timer + OnFailure alerter)
scp infra/kb-backup.service infra/kb-backup.timer infra/kb-backup-alert.service "$VPS":/tmp/
ssh "$VPS" 'sudo install -o root -g root -m 0644 /tmp/kb-backup.service       /etc/systemd/system/kb-backup.service'
ssh "$VPS" 'sudo install -o root -g root -m 0644 /tmp/kb-backup.timer         /etc/systemd/system/kb-backup.timer'
ssh "$VPS" 'sudo install -o root -g root -m 0644 /tmp/kb-backup-alert.service /etc/systemd/system/kb-backup-alert.service'

# 3. Reload and enable
ssh "$VPS" 'sudo systemctl daemon-reload && sudo systemctl enable --now kb-backup.timer'

# 4. Verify the timer is active
ssh "$VPS" 'systemctl list-timers kb-backup.timer'
```

### Operator-managed secrets file (NOT repo-tracked)

`/etc/kb-backup/env` holds secrets and is intentionally absent from the
repository. Build it from `infra/kb-backup-env.template` (every key, with
sources) and install it `root:switch 0640` — exact commands in
`docs/runbooks/rebuild-production.md` step 7. The restic repository must live
at a different company than the host (template comment explains why);
`kb-backup.sh` refuses to run while `RESTIC_REPOSITORY` is still the
`REPLACE_ME` placeholder.

After provisioning the env file, verify the alert channel:

```bash
ssh "$VPS" 'sudo bash -c "set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-backup.sh --test-alert"'
```

> **Note:** A successful `--test-alert` run sends one Telegram message and exits 0 without running any backup.

## Backup subsystem (sb-6nq.3)

Nightly `pg_dump | restic backup` to the off-provider `RESTIC_REPOSITORY`
(S3-compatible object storage at a second company; see the env template).
The original target, a Hetzner BX11 Storage Box, was lost with the Hetzner
account in 2026-09 (sb-ik76). All artifacts live on the VPS — nothing in the
repo runs the backup.

### Files on `switch-berlin-prod`

| Path | Owner / mode | Purpose |
|---|---|---|
| `/usr/local/bin/kb-backup.sh` | `root:root 0755` | Detects compose db container via `com.docker.compose.service=db` label; dumps with `pg_dump -Fc` to a tempfile under `/var/tmp/kb-backup/`, checks absolute 50KiB floor (**sb-omx**) before handing to restic. On a successful db snapshot writes epoch seconds to `/var/tmp/kb-backup/last-success` (read by kb-monitor's backup-freshness check). Refuses to run while `RESTIC_REPOSITORY` starts with `REPLACE_ME`. Falls back to a `no-db-marker.txt` snapshot when no db container is running (no size check — healthy state). **sb-336:** compares new tag=db snapshot bytes to the previous one; if `new < prev / DROP_RATIO` (default 5), POSTs a Telegram alert. Flags: `--test-alert` (canary), `--force-alert` (forced regression message), `--service-failed-alert` (generic failure alert, used by `kb-backup-alert.service` via `OnFailure=`), `--simulate-tiny-dump` (test-only: writes 100-byte fake dump and exercises the 50KiB floor path; expects non-zero exit and alert). |
| `/etc/kb-backup/env` | `root:switch 0640` | systemd `EnvironmentFile`. Keys: see `infra/kb-backup-env.template`. `RESTIC_PASSWORD` is mirrored locally as `RESTIC_ENCRYPTION_PASSWORD` in repo `.env` (DR key). |
| `/etc/systemd/system/kb-backup.service` | `root:root 0644` | `Type=oneshot`, runs as `switch:switch`, requires `docker.service`. `OnFailure=kb-backup-alert.service` (**sb-omx**). |
| `/etc/systemd/system/kb-backup.timer` | `root:root 0644` | `OnCalendar=*-*-* 03:00:00`, `RandomizedDelaySec=900`, `Persistent=true`. Enabled at `timers.target`. |
| `/etc/systemd/system/kb-backup-alert.service` | `root:root 0644` | `Type=oneshot`, runs as `switch:switch` (**sb-omx**). Triggered by `OnFailure=` in `kb-backup.service`. Runs `kb-backup.sh --service-failed-alert` to send a Telegram "service failed — check journalctl" message. |

### Operations

```bash
# Manual trigger (oneshot — re-uses the timer's unit)
sudo systemctl start kb-backup.service

# Tail recent runs
sudo journalctl -u kb-backup.service --since="1 hour ago"

# Backup freshness as the monitor sees it (exit 0 fresh, 1 stale/missing)
sudo runuser -u switch -- /usr/local/bin/kb-monitor.sh --check-backup

# Show next scheduled trigger
systemctl list-timers kb-backup.timer

# List snapshots (auth via env file)
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- restic snapshots'

# Verify the alert channel (canary; sends one Telegram message, no backup)
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-backup.sh --test-alert'

# Force the regression message format (no backup, no real size comparison)
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-backup.sh --force-alert'

# Test the 50KiB absolute-floor path (sb-omx): writes 100-byte fake dump,
# exercises size-check + alert, exits 1.
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- /usr/local/bin/kb-backup.sh --simulate-tiny-dump'
# To also exercise the OnFailure= chain (triggers kb-backup-alert.service),
# create a drop-in override, start the service, then clean up:
sudo mkdir -p /etc/systemd/system/kb-backup.service.d
sudo tee /etc/systemd/system/kb-backup.service.d/test-override.conf > /dev/null <<'DROPINEOF'
[Service]
ExecStart=
ExecStart=/usr/local/bin/kb-backup.sh --simulate-tiny-dump
DROPINEOF
sudo systemctl daemon-reload
sudo systemctl start kb-backup.service   # expect: exit 1, OnFailure chain fires
# Clean up:
sudo rm -rf /etc/systemd/system/kb-backup.service.d/
sudo systemctl daemon-reload

# Disaster recovery — restore latest db snapshot into a scratch container
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- restic restore latest --target /tmp/kb-restore --tag db'
docker exec -i <scratch-pg> pg_restore -U postgres -d postgres --clean --if-exists < /tmp/kb-restore/db-*.dump
```

### Validation (sb-6nq.3 acceptance, 2026-05-08)

- Timer enabled, `systemctl is-enabled kb-backup.timer` → `enabled`; NEXT trigger surfaced via `systemctl list-timers`.
- `restic init` on empty repo → repo ID `6de8e15bd2`; `restic snapshots` on initialised empty repo exited 0 with no rows.
- Manual one-shot run with no db container produced no-db marker snapshot `6790673b`.
- Manual one-shot run with a synthetic 3-row `events_event` table produced db snapshot `a4c9240e` (1.5 KiB pg_dump). Roundtrip via `restic restore` + `pg_restore` into a scratch `pgvector/pgvector:pg17` container yielded row count `3` — matches live.

The first-deploy auto-trigger that populates the timer's `LAST` column is `sb-6nq.5`'s job.

### Size-regression alert (sb-336 acceptance, 2026-05-13)

Motivated by the sb-vp8 data-loss incident: the 132 KiB → 3.5 KiB drop went unnoticed for ~12h. The alert closes that window.

- **Channel:** Telegram via `@switch_berlin_bot` (existing app bot, sb-6ep). Token shared with app via mirror in `/etc/kb-backup/env`; operator chat ID is the operator's personal Telegram user ID after they `/start` the bot once.
- **Threshold:** `new < prev / DROP_RATIO` where `DROP_RATIO=5` by default (configurable via env). Comparison is against the previous tag=db latest snapshot captured *before* the new backup runs.
- **No-op fallback:** if either `TELEGRAM_BOT_TOKEN` or `TELEGRAM_OPERATOR_CHAT_ID` is empty, the script logs the alert to stderr and exits cleanly — the backup itself never fails because alert delivery is misconfigured.
- **Validation 2026-05-13:** canary (`--test-alert`) and forced-regression (`--force-alert`) flows both delivered to the operator's Telegram. A real `systemctl start kb-backup.service` run logged `prev=143302B new=143390B (threshold: alert if new < prev/5)` and fired no spurious alert.
