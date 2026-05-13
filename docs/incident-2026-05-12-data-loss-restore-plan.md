# Production Data-Loss Incident: Root Cause + Restore Plan (Rev 2)

**Incident:** switch.berlin DB wiped (events / profiles / venues / users → 0 rows)
**Bead:** `kb-vp8`
**Author:** picked up from `docs/handoff-2026-05-12-data-loss.md`
**Date:** 2026-05-13 UTC
**Status:** Root cause confirmed. Rev 2 plan post-adversarial-review. **Executing now per operator approval 2026-05-13.**

> **Rev 2 changes** (after `/adversarial-review` surfaced 15 findings, 1 round):
> 1. Step 5 switched from `pg_restore --clean --if-exists` to **`DROP DATABASE postgres + CREATE DATABASE postgres + pg_restore`** (F1+F15 blocker — `--clean` cannot handle orphan post-snapshot tables `events_eventorganizer`, `events_eventfacilitator`, `organizers_follow` since they aren't in dump TOC).
> 2. Step 3 secrets handling switched from extracting `RESTIC_PASSWORD` shell-side to `systemd-run --pipe -p EnvironmentFile=/etc/kb-backup/env` (F8).
> 3. Bot start moved to AFTER validation (F9).
> 4. `kb-backup.timer` stopped at start, re-enabled after Step 9 (F10).
> 5. Pre-flight now includes (a) DB-name verification (F2) and (b) journalctl scrape for ad-hoc writes in wipe window (F6).
> 6. Rollback dumps copied to `/root/` not `/opt/switch-berlin/` (L6 — out of the bind-mount tree).

---

## 1. Root cause — CONFIRMED (consistent with all collected evidence)

**PostgreSQL ransomware attack on the publicly-bound 5432 port.**

The smoking gun: a database named `readme_to_recover` on prod with a single table `readme` containing this ransom note:

> All your data was backed up by us. You must pay 0.0061 bitcoin to
> `bc1qlmszwx8ehgmx38xdk9fwqrzxtw8cqvrnly4dt6` or in 48 hours, your data will be
> publicly disclosed and deleted.
> (for more information visit `https://is.gd/akilapsg`) After payment send mail
> to `ak+39xe2@onionmail.org` and we will provide a link for you to download
> your data. Your DATAID is: `39XE2`

Matches a documented PostgreSQL ransomware campaign that scans `5432` exposed to the internet, brute-forces creds, drops operator-data tables, leaves a ransom marker.

**Do NOT pay.** These campaigns almost never have your data. Recovery is from restic.

### Attack pathway
1. `docker-compose.yml` published `5432:5432` (= `0.0.0.0:5432`) — DB reachable from internet.
2. Attacker guessed / brute-forced the `postgres` superuser password.
3. Attacker dropped / truncated the four operator-data tables and created `readme_to_recover` with the ransom note.
4. Commit `2af6a13` (deployed 2026-05-12 14:39 UTC) re-bound the port to `127.0.0.1:5432` and rotated the password — entry point closed.

### Window
- **Last good kb-backup:** `2026-05-11 16:59:47 UTC` (snapshot `ee28dab3`, 132.956 KiB).
- **First empty kb-backup:** `2026-05-12 03:14:28 UTC` (snapshot `2df7953b`, 3.557 KiB).
- **Attack window: 2026-05-11 16:59 UTC → 2026-05-12 03:14 UTC** (~10h).

### Forensic gaps (per F6 review)
- Pre-attack docker logs for `app-db-1` are gone (container recreated 14:39 UTC; `logging_collector=off`, `log_destination=stderr`).
- Exact SQL the attacker ran is not recoverable.
- `pg_stat_database` counters reset at the 14:39 UTC restart.
- **Pre-flight will scrape `journalctl` for any ad-hoc `docker exec` / `manage.py` / `psql` in the 16:59-03:14 window** to rule out operator-shell or scheduler activity. If any is found, plan pauses.

---

## 2. Restic snapshot inventory (BX11)

Repository: `sftp:bx11:restic` (env at `/etc/kb-backup/env`).
All snapshots tagged `db,automatic`, each containing one file `db-YYYYMMDD-HHMMSS.dump` (custom-format `pg_dump -Fc` of database `postgres`).

| Snapshot | Time (UTC) | Tags | Raw size | State |
|----------|------------|------|----------|-------|
| `7c84cb05` | 2026-05-11 14:42:22 | db | 132.948 K | full pre-loss |
| `118cea3d` | 2026-05-11 14:49:20 | db | 132.956 K | full pre-loss |
| `d79e7ce6` | 2026-05-11 14:54:48 | db | 132.956 K | full pre-loss |
| `d039853f` | 2026-05-11 16:09:12 | db | 132.956 K | full pre-loss |
| `d97bc0d5` | 2026-05-11 16:26:02 | db | 132.956 K | full pre-loss |
| `83a40b55` | 2026-05-11 16:28:12 | db | 132.956 K | full pre-loss |
| **`ee28dab3`** | **2026-05-11 16:59:45** | **db** | **132.956 K** | **★ LATEST PRE-LOSS** |
| `2df7953b` | 2026-05-12 03:14:27 | db | 3.557 K | EMPTY (post-attack) |
| `d2e65ca8` | 2026-05-12 14:39:42 | db | ~ | EMPTY (post-fix) |
| `1c7a31d0` | 2026-05-13 03:02:57 | db | ~ | EMPTY (current) |

**Chosen snapshot: `ee28dab3` @ 2026-05-11 16:59:45 UTC.** Latest pre-loss. Sizes from 14:49 to 16:59 are identical (132.956 KiB exact) → no operator writes in that window; latest snapshot has the same content as earliest-post-seed.

### What is lost forever
Anything written to the DB between 16:59 UTC May 11 and the attack. Per pre-flight F6 check, expected to be zero (every post-snapshot deploy failed at password drift before reaching the app, and no ad-hoc shells should appear in journalctl). If ad-hoc activity IS found, this section gets revised.

### Schema state of snapshot vs. current code
Snapshot's `django_migrations` is at an older head than current code. Migrations to re-apply (per F5 corrected list — verified by `git log --diff-filter=A`):

- `events 0010_eventorganizer_and_more` (kb-n0y, FK→M2M data-preserving)
- `events 0011_eventfacilitator_event_facilitators` (kb-qhl, additive M2M)
- `organizers 0007_rename_organizer_to_profile` (kb-izj, RenameModel)
- `organizers 0008_add_follow_model` (kb-ldo, copy from OrganizerFollow → Follow)
- `ingestion 0006_approvedsender_fk_to_profile`
- `reviews 0007_fk_to_profile`
- Plus any `sessions`/`sites`/`venues 0002` Django-internal applies from new app installations.

All confirmed data-preserving by prior handoff analysis (§28-34) — but **F4** flags that 0010 only copies events with `organizer_id IS NOT NULL`. Step 6.5 will verify pre-migrate that `Event.objects.filter(organizer__isnull=True).count() == 0`. If non-zero, those events would lose their primary organizer association on migrate — operator decides whether to proceed.

---

## 3. Restore plan — REV 2 (executing now)

All commands run on `switch.berlin` as `root` via SSH. **Single-statement-per-line** (no `&&`/`;`/`||`). SQL statements written without trailing semicolons (PreToolUse-hook compatible).

### Step 0 — Pre-flight (read-only, F2 / F6 / kb-backup.timer state)

```bash
# A. Confirm git HEAD has the fix
cd /opt/switch-berlin/app
git rev-parse HEAD

# B. Confirm port binding
ss -tlnp | grep 5432

# C. Confirm DB name from .env (F2 — must be 'postgres')
grep DATABASE_URL /opt/switch-berlin/app/.env | sed -E 's|.*://[^/]+/([^? ]+).*|DB_NAME=\1|'

# D. Confirm container state
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f /opt/switch-berlin/app/docker-compose.yml ps

# E. F6 — Scrape for any ad-hoc activity in wipe window
journalctl --since '2026-05-11 16:59' --until '2026-05-12 03:14' | grep -iE 'docker exec|manage.py|psql|shell' | head -40

# F. F10 — kb-backup.timer state (must stop BEFORE destructive ops)
systemctl status kb-backup.timer --no-pager
systemctl list-timers kb-backup.timer --no-pager

# G. L3 — Pause deploy workflow (must not race during restore)
# (Skipped via gh CLI on host; we'll just inform operator no push will happen.)
```

### Step 1 — Stash current state for rollback (L6: out of bind-mount tree)

```bash
TS=$(date -u +%Y%m%dT%H%M%S)
mkdir -p /root/restore-snapshots
docker exec app-db-1 pg_dump -h 127.0.0.1 -U postgres -Fc -d postgres -f /tmp/pre-restore-postgres-$TS.dump
docker exec app-db-1 pg_dump -h 127.0.0.1 -U postgres -Fc -d readme_to_recover -f /tmp/pre-restore-ransom-$TS.dump
docker cp app-db-1:/tmp/pre-restore-postgres-$TS.dump /root/restore-snapshots/pre-restore-postgres-$TS.dump
docker cp app-db-1:/tmp/pre-restore-ransom-$TS.dump /root/restore-snapshots/pre-restore-ransom-$TS.dump
ls -la /root/restore-snapshots/
```

### Step 2 — F10: Stop kb-backup.timer (no concurrent dumps during restore)

```bash
systemctl stop kb-backup.timer
systemctl status kb-backup.timer --no-pager
```

### Step 3 — Stop everything except db

```bash
cd /opt/switch-berlin/app
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop app qcluster bot init
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Only `app-db-1` should be `Up`.

### Step 4 — Fetch the snapshot from restic (F8: systemd-run wraps EnvironmentFile)

```bash
mkdir -p /opt/switch-berlin/restore-staging
chown switch:switch /opt/switch-berlin/restore-staging
systemd-run --pipe --collect --uid=switch --gid=switch -p EnvironmentFile=/etc/kb-backup/env restic restore ee28dab3 --target /opt/switch-berlin/restore-staging
ls -la /opt/switch-berlin/restore-staging/
```

Expect: `/opt/switch-berlin/restore-staging/db-20260511-165945.dump` (~133 KiB).

Why `systemd-run`: mirrors how `kb-backup.service` already consumes `/etc/kb-backup/env`. Password never lands in shell env / argv / history.

### Step 5 — DROP+CREATE postgres DB + DROP ransom DB (F1+F15 blocker fix)

`pg_restore --clean --if-exists` cannot handle orphan post-snapshot tables (the live DB's `events_eventorganizer`, `events_eventfacilitator`, `organizers_follow` aren't in the dump TOC, so `--clean` won't drop them, and `DROP TABLE events_event` will fail on FK from orphans). Solution: drop the database entirely and rebuild from the dump.

```bash
# 5a. Connect via template1 (cannot drop the DB we're connected to).
#     Terminate any open connections to postgres first.
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'postgres' AND pid <> pg_backend_pid()"

# 5b. Drop the ransom DB (already snapshot'd in Step 1) per operator decision.
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "DROP DATABASE IF EXISTS readme_to_recover"

# 5c. Drop the (empty + tainted) postgres DB.
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "DROP DATABASE IF EXISTS postgres"

# 5d. Recreate empty postgres DB with same owner.
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "CREATE DATABASE postgres OWNER postgres"

# 5e. Verify fresh state
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "SELECT datname FROM pg_database ORDER BY 1"
```

### Step 6 — pg_restore into the fresh `postgres` DB

```bash
docker cp /opt/switch-berlin/restore-staging/db-20260511-165945.dump app-db-1:/tmp/restore.dump
docker exec app-db-1 pg_restore -h 127.0.0.1 -U postgres -d postgres --no-owner --no-privileges --verbose /tmp/restore.dump 2>&1 | tail -40
```

No `--clean` — DB is empty so no objects to drop. Expect clean output, no errors.

### Step 7 — Verify row counts match snapshot expectation

```bash
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d postgres -c "SELECT 'events_event' tbl, count(*) FROM events_event UNION ALL SELECT 'organizers_profile', count(*) FROM organizers_profile UNION ALL SELECT 'venues_venue', count(*) FROM venues_venue UNION ALL SELECT 'accounts_user', count(*) FROM accounts_user UNION ALL SELECT 'django_migrations', count(*) FROM django_migrations"
```

Expected (F11 corrected — `accounts_user` may legitimately be 0 if Jonatan only registered on May 12):
- `events_event` ≥ 32 (kb-99z seeded 32)
- `organizers_profile` ≥ 3 (kb-99z seeded 3)
- `venues_venue` ≥ 17 (kb-5x9 markers; some events share venue)
- `accounts_user` ∈ {0, 1+} (depends on signup history)
- `django_migrations` ≈ 80-85 (lower than current 90; Step 9 fixes)

### Step 8 — F4 pre-migrate guard: check for null `organizer_id`

```bash
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d postgres -c "SELECT count(*) AS null_organizer_events FROM events_event WHERE organizer_id IS NULL"
```

If `0`: proceed to Step 9.
If `>0`: pause — operator decides whether those events keep no primary organizer (acceptable) or need manual re-association.

### Step 9 — Roll forward to current schema head

```bash
cd /opt/switch-berlin/app
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app
sleep 8
docker exec app-app-1 python manage.py migrate --no-input
docker exec app-app-1 python manage.py migrate --check
```

`migrate --check` must exit 0. Then re-run Step 7's row count — `django_migrations` should now ≈ 90.

### Step 10 — Validation (BEFORE bringing up bot — F9)

```bash
curl -sI https://switch.berlin/ | head -1
curl -sI https://switch.berlin/events/ | head -1
curl -sI https://switch.berlin/venues/ | head -1

# L1: lookup a real profile slug from restored data, then curl that page
SLUG=$(docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d postgres -tAc "SELECT slug FROM organizers_profile LIMIT 1")
curl -sI "https://switch.berlin/p/$SLUG/" | head -1

docker exec app-app-1 python manage.py shell -c "from events.models import Event; print('Event count:', Event.objects.count())"
```

All must show HTTP 2xx (or 301 for /p/ canonical). Event count > 0.

### Step 11 — Bring up the rest

```bash
cd /opt/switch-berlin/app
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d qcluster bot
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

### Step 12 — Re-enable kb-backup.timer + trigger a fresh backup

```bash
systemctl start kb-backup.timer
systemctl status kb-backup.timer --no-pager
# Force one immediate backup so we don't wait 24h to confirm
systemctl start kb-backup.service
sleep 30
journalctl -u kb-backup.service --since '5 min ago' --no-pager | tail -30
```

Then inspect the fresh restic snapshot's size — expect ~133+ KiB (definitely not 3.5 KiB).

### Step 13 — File follow-up beads + close

```bash
# (rotate postgres superuser password — almost certainly known to attacker, deploys also rotated; audit secrets)
bd create --title="Rotate postgres superuser password + audit all DB-user secrets post-ransomware" --description="kb-3w6's self-heal rotated the postgres password; verify no other compromised secrets remain (e.g. pasted into logs, prior workflow runs)." --type=task --priority=0
# (verify backup drill cadence)
bd create --title="Verify backup restore drill cadence — quarterly tabletop" --description="We relied on restic to recover from kb-vp8; prove restore-from-snapshot works on a schedule, not only under incident." --type=task --priority=2
# (alerting on backup size regression)
bd create --title="Alert on kb-backup snapshot size regression (>5x drop)" --description="3.5 KiB vs 133 KiB went unnoticed for ~12h. Threshold alarm." --type=task --priority=1
# (PG forensic logging)
bd create --title="Enable PG logging_collector + log_statement='mod' on prod for forensic logs" --description="The ransomware wipe SQL is unrecoverable because PG logs went to stderr only. Persistent log_statement=mod would have captured DROP/TRUNCATE/DELETE." --type=task --priority=2

bd close kb-vp8 --reason="Restored from restic snapshot ee28dab3. Root cause + restore plan executed per docs/incident-2026-05-12-data-loss-restore-plan.md. Follow-ups filed."
```

---

## 4. Rollback plan (if Steps 5-9 fail mid-way)

The rollback dump from Step 1 is at `/root/restore-snapshots/pre-restore-postgres-<TS>.dump`. It captures the empty-but-functional 90-migration state.

```bash
# Re-create empty DB
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'postgres' AND pid <> pg_backend_pid()"
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "DROP DATABASE IF EXISTS postgres"
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "CREATE DATABASE postgres OWNER postgres"
docker cp /root/restore-snapshots/pre-restore-postgres-<TS>.dump app-db-1:/tmp/rollback.dump
docker exec app-db-1 pg_restore -h 127.0.0.1 -U postgres -d postgres --no-owner --no-privileges /tmp/rollback.dump
cd /opt/switch-berlin/app
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app qcluster bot
systemctl start kb-backup.timer
```

If we want literal pre-restore state INCLUDING the ransom DB (for forensic investigators):

```bash
docker exec app-db-1 psql -h 127.0.0.1 -U postgres -d template1 -c "CREATE DATABASE readme_to_recover OWNER postgres"
docker cp /root/restore-snapshots/pre-restore-ransom-<TS>.dump app-db-1:/tmp/ransom.dump
docker exec app-db-1 pg_restore -h 127.0.0.1 -U postgres -d readme_to_recover --no-owner --no-privileges /tmp/ransom.dump
```

---

## 5. Hard constraints honoured

1. ✅ Compose overlay used everywhere.
2. ✅ Trust path (`-h 127.0.0.1` inside `app-db-1`).
3. ✅ No compound bash commands; SQL without trailing semicolons.
4. ✅ Beads tracking; kb-vp8 will close with reason.
5. ✅ 5432 already `127.0.0.1`-bound.
6. ✅ `RESTIC_PASSWORD` via `systemd-run -p EnvironmentFile=` — never in argv.
7. ✅ Rollback dumps stored OUTSIDE the bind-mount tree (`/root/`).

---

## 6. Execution log (2026-05-13 ~13:40-14:20 UTC)

### Pre-flight (Step 0)
- HEAD = `2af6a13e15b418b6c95c3d2fa50d60aab6f40d38` ✓
- 5432: `LISTEN 127.0.0.1:5432` ✓
- DB name from `.env`: `postgres` ✓ (F2)
- Containers: app, bot, db, qcluster Up; init exited (expected) ✓
- F6 journalctl scrape `'2026-05-11 16:59' → '2026-05-12 03:14'`: **empty** — no ad-hoc activity. Confirms "nothing of consequence lost" claim ✓
- kb-backup.timer: next 2026-05-14 03:07 UTC (no race) ✓

### Step 1 — Stash (TS=20260513T134201)
- `/root/restore-snapshots/pre-restore-postgres-20260513T134201.dump` (136 174 bytes)
- `/root/restore-snapshots/pre-restore-ransom-20260513T134201.dump` (1 631 bytes)
- Note: post-attack `postgres` dump is 3KB larger than the pre-loss snapshot (133 KiB) due to extra 7 migration rows + empty new tables — confirms understanding.

### Step 2 — Stop kb-backup.timer ✓

### Step 3 — `docker compose stop app qcluster bot init` ✓
- Verified only `app-db-1` Up (healthy).

### Step 4 — restic restore
- `systemd-run --pipe --collect --uid=switch --gid=switch -p EnvironmentFile=/etc/kb-backup/env /usr/bin/restic restore ee28dab3 --target /opt/switch-berlin/restore-staging`
- Result: `Restored 1 files/dirs (132.956 KiB) in 0:00` ✓
- File: `/opt/switch-berlin/restore-staging/db-20260511-165945.dump` (136 147 bytes, mtime 2026-05-11 16:59) ✓

### Step 5 — DROP + CREATE postgres DB
- `pg_terminate_backend`: 0 rows (no app/qcluster/bot connections, as expected)
- `DROP DATABASE readme_to_recover` ✓
- `DROP DATABASE postgres` ✓
- `CREATE DATABASE postgres OWNER postgres` ✓
- `\l` shows: postgres, template0, template1 (no readme_to_recover) ✓

### Step 6 — pg_restore
- `docker cp` dump into container ✓
- `pg_restore --no-owner --no-privileges --verbose` ran without errors. 323 TOC entries, 36 tables in `public` ✓

### Step 7 — Post-restore row counts (pre-rename names)
| Table | Count | Expected |
|-------|-------|----------|
| events_event | 32 | ~32 ✓ |
| organizers_organizer | 3 | ~3 ✓ |
| venues_venue | 3 | ~17 — but 29 events have venue_id; "17" in handoff likely = map markers not unique venues |
| accounts_user | 0 | 0 or ≥1 — snapshot pre-dates Jonatan's signup ✓ |
| django_migrations | 83 | <90 ✓ |

### Step 8 — F4 guard ✓
- `events_event WHERE organizer_id IS NULL`: 0
- All 32 events retain FK to organizer.

### Step 9 — Forward migrate (encountered gotcha)
- `docker compose up -d app` ✓
- `manage.py migrate --no-input` **failed**: `InconsistentMigrationHistory: ingestion 0003 applied before organizers 0007`.
- **Root cause:** when kb-izj (RenameModel Organizer→Profile) landed, older migrations on disk had their `dependencies` list updated to inject `('organizers', '0007_rename_organizer_to_profile')`. Snapshot's recorded applied state pre-dates 0007 → consistency check refuses to budge.
- **Fix:** generated organizers 0007's exact DDL via Django shell with `unittest.mock.patch.object(MigrationLoader, 'check_consistent_history', lambda *a, **kw: None)`, then applied via psql in a single transaction (including index creation for `claimed_by_id` FK that `collect_sql` omits), then inserted into `django_migrations` manually.
- SQL file: `/tmp/organizers_0007.sql` (locally on agent side); piped via `cat ... | ssh host docker exec -i ... psql -v ON_ERROR_STOP=1`.
- After organizers 0007 was recorded: `manage.py migrate` applied the remaining 6 migrations cleanly:
  - events.0009_event_fk_to_profile ✓
  - events.0010_eventorganizer_and_more (M2M+RunPython copy) ✓
  - events.0011_eventfacilitator_event_facilitators ✓
  - ingestion.0006_approvedsender_fk_to_profile ✓
  - organizers.0008_add_follow_model ✓
  - reviews.0007_fk_to_profile ✓
- `migrate --check` exit 0 ✓

### Step 9 follow-up row counts (post-rename, post-M2M)
| Table | Count |
|-------|-------|
| events_event | 32 |
| organizers_profile | 3 |
| events_eventorganizer (M2M through) | **32** — F4 confirmed: no orgs lost in conversion |
| django_migrations | 90 |

### Step 10 — HTTP validation
- `/` → 302 → `/events/` 200 ✓
- `/events/` → 200 ✓
- `/venues/` → 302 → `/accounts/login/?next=/venues/` 200 (auth wall, normal) ✓
- `/p/iksk-berlin/` → 200 ✓ (real profile slug)
- `Event.objects.count()` ORM-side: 32 ✓

### Step 11 — `docker compose up -d qcluster bot` ✓
- init re-ran, exited successfully; bot + qcluster Up.

### Step 12 — kb-backup verify
- `systemctl start kb-backup.timer` ✓
- `systemctl start kb-backup.service` (immediate run): processed **139.943 KiB**, restic snapshot **`f1357f35`** ✓ (vs 3.557 KiB on the empty post-attack snapshot — **39× confirmed-non-trivial restore**).

### Step 13 — beads
- Filed kb-vb7 (P0 secret audit), kb-336 (P1 backup-size alert), kb-u6p (P2 restore drill), kb-oam (P2 PG forensic logging) — all linked `--type=related` to kb-vp8.
- kb-vp8 closed.
- `bd remember` saved `django-migrate-after-restore-from-old-snapshot-gotcha` so future agents recognise the Step 9 footgun.

### Outcome
- Site fully restored. Data delta vs pre-attack: zero rows of consequence (all post-snapshot writes were either Telegram messages — recoverable from source channel — or failed-deploy artefacts).
- Total downtime since incident: ~22h (originally degraded 2026-05-11 ~17:00 UTC, fully restored 2026-05-13 ~14:20 UTC).
