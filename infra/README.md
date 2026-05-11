# Switch Berlin — Production Infrastructure

This directory holds infrastructure-as-code for the production deploy target
(kb-6nq epic).

## Files

| File | Purpose |
|---|---|
| `Caddyfile` | Host-installed Caddy config: TLS termination + `www → apex` redirect (308). Mirrored into `cloud-init.yaml` for first-boot provisioning. |
| `cloud-init.yaml` | First-boot config for the Hetzner VPS. Creates `switch` deploy user, installs Docker + Caddy, sets up `/opt/switch-berlin/`, configures UFW firewall. |
| `../.github/workflows/deploy.yml` | GH Actions deploy workflow. Slot-4 records non-secret env + verifies secret-name presence; slot-5 implements actual deploy steps. |

## VPS provisioning runbook (kb-6nq.1)

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

## Acceptance probes (kb-6nq.1)

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

## GH Actions secrets & env inventory (kb-6nq.4)

### Secrets (set via `gh secret set <NAME>`, value never echoed)

App secrets — consumed by Django via `.env` rendered on the VPS:

| Name | Source | Notes |
|---|---|---|
| `SECRET_KEY` | repo `.env` | Django session signing key |
| `DATABASE_URL` | repo `.env` | `postgres://postgres:postgres@db:5432/postgres` (refine in slot-5 if rotating db pw) |
| `IMPRESSUM_NAME` | repo `.env` | Operator legal name |
| `IMPRESSUM_ADDRESS` | repo `.env` | Operator legal address |
| `IMPRESSUM_EMAIL` | repo `.env` | `kinkybubbles@protonmail.com` per ADR-006 D3 (rotated by kb-9hw) |
| `IMPRESSUM_PHONE` | repo `.env` (empty) | Optional contact channel |
| `RESPONSIBLE_PERSON_NAME` | empty | Falls back to `IMPRESSUM_NAME` (settings.py) |
| `RESPONSIBLE_PERSON_ADDRESS` | empty | Falls back to `IMPRESSUM_ADDRESS` (settings.py) |
| `DSA_CONTACT_EMAIL` | repo `.env` | Falls back to `IMPRESSUM_EMAIL` if empty |
| `TELEGRAM_BOT_TOKEN` | empty placeholder | Real value tracked by `kb-6ep` (blocks `kb-6nq.6`) |
| `FIRECRAWL_API_KEY` | empty placeholder | Not yet referenced in code |

Deploy-channel secrets — consumed by the workflow itself:

| Name | Value | Notes |
|---|---|---|
| `VPS_HOST` | `128.140.56.30` | IPv4 of `switch-berlin-prod` (Hetzner ID 129964122) |
| `VPS_USER` | `switch` | Deploy user created by `cloud-init.yaml` |
| `VPS_SSH_KEY` | `~/.ssh/switch-berlin-deploy` (private) | Pubkey installed on VPS as `switch`'s `authorized_keys` |

### Non-secret workflow env (declared in `.github/workflows/deploy.yml`)

| Name | Value |
|---|---|
| `ALLOWED_HOSTS` | `switch.berlin,www.switch.berlin` |
| `CSRF_TRUSTED_ORIGINS` | `https://switch.berlin,https://www.switch.berlin` |
| `DEBUG` | `False` |
| `DJANGO_SETTINGS_MODULE` | `a_core.settings` |

## Backup subsystem (kb-6nq.3)

Nightly `pg_dump | restic backup` to Hetzner BX11 (provisioned by `kb-eac`).
All artifacts live on the VPS — nothing in the repo runs the backup.

### Files on `switch-berlin-prod`

| Path | Owner / mode | Purpose |
|---|---|---|
| `/usr/local/bin/kb-backup.sh` | `root:root 0755` | Detects compose db container via `com.docker.compose.service=db` label; dumps with `pg_dump -Fc` piped to `restic backup --stdin`. Falls back to a `no-db-marker.txt` snapshot when no db container is running — keeps pipeline exercisable before/between deploys. |
| `/etc/kb-backup/env` | `root:switch 0640` | systemd `EnvironmentFile`. Contains `RESTIC_REPOSITORY=sftp:bx11:restic` and `RESTIC_PASSWORD=<32-byte hex>` (mirrored locally as `RESTIC_ENCRYPTION_PASSWORD` in repo `.env` — DR key). |
| `/etc/systemd/system/kb-backup.service` | `root:root 0644` | `Type=oneshot`, runs as `switch:switch`, requires `docker.service`. |
| `/etc/systemd/system/kb-backup.timer` | `root:root 0644` | `OnCalendar=*-*-* 03:00:00`, `RandomizedDelaySec=900`, `Persistent=true`. Enabled at `timers.target`. |
| `~switch/.ssh/restic-bx11` | `switch:switch 0600` | SSH key authorised on BX11 (port 23). |
| `~switch/.ssh/config` | `switch:switch 0600` | Defines `Host bx11 → u590899.your-storagebox.de:23` so restic URL `sftp:bx11:restic` Just Works. |

### Hetzner Storage Box quirks

- Username is chrooted — repo path must be **relative** (`sftp:bx11:restic`, not `sftp:bx11:/restic`). Absolute paths return `SSH_FX_FAILURE`.
- SSH support on the box is a panel toggle (port 23), separate from password-based SMB/WebDAV. Must be on for restic-over-SFTP — see `kb-eac`.

### Operations

```bash
# Manual trigger (oneshot — re-uses the timer's unit)
sudo systemctl start kb-backup.service

# Tail recent runs
sudo journalctl -u kb-backup.service --since="1 hour ago"

# Show next scheduled trigger
systemctl list-timers kb-backup.timer

# List snapshots (auth via env file)
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- restic snapshots'

# Disaster recovery — restore latest db snapshot into a scratch container
sudo bash -c 'set -a; . /etc/kb-backup/env; set +a; runuser -u switch -- restic restore latest --target /tmp/kb-restore --tag db'
docker exec -i <scratch-pg> pg_restore -U postgres -d postgres --clean --if-exists < /tmp/kb-restore/db-*.dump
```

### Validation (kb-6nq.3 acceptance, 2026-05-08)

- Timer enabled, `systemctl is-enabled kb-backup.timer` → `enabled`; NEXT trigger surfaced via `systemctl list-timers`.
- `restic init` on empty repo → repo ID `6de8e15bd2`; `restic snapshots` on initialised empty repo exited 0 with no rows.
- Manual one-shot run with no db container produced no-db marker snapshot `6790673b`.
- Manual one-shot run with a synthetic 3-row `events_event` table produced db snapshot `a4c9240e` (1.5 KiB pg_dump). Roundtrip via `restic restore` + `pg_restore` into a scratch `pgvector/pgvector:pg17` container yielded row count `3` — matches live.

The first-deploy auto-trigger that populates the timer's `LAST` column is `kb-6nq.5`'s job.
