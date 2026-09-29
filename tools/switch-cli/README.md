# switch-cli

Command-line client for Switch. Every command prints JSON; `switch-cli --help` lists them.

## Event collector (`switch-cli collect`)

Collect event candidates from the source list (`collector_sources.toml`) into a rows file, then push them to Switch:

```bash
uv run switch-cli collect web --out rows.jsonl
uv run switch-cli collect telegram --out rows.jsonl --private
uv run switch-cli collect push rows.jsonl
```

The rows file holds post text and base64 photos, private groups included. Telegram reads are read-only (ADR-018 D2).

`collect push` deletes the rows file after a successful push. `--keep` leaves it. A failed push leaves it for a retry.

**Done-condition for the operator:** the push output shows `"rows_file_deleted": true`, and no rows file remains on disk. If you passed `--keep` or the push failed, delete the file yourself once you are finished with it.

## Nightly run (launchd, local dev stack)

Until production is rebuilt, the mac mini runs the collector once per night against the local dev stack (sb-7wzb.5). Only one machine holds the Telegram session at a time; the macbook copy stays idle.

- `nightly/collect-nightly.sh` runs `collect web`, `collect telegram --private`, then `collect push` for each rows file. The dev qcluster extracts the new rows. The script waits for the queue to drain and logs a per-source table (counts only, never post text).
- Stack rule: Docker (OrbStack) must be running, or the run fails loud. The script starts the db container, `runserver` or `qcluster` only when they are down, and stops only what it started.
- `nightly/berlin.switch.collector-nightly.plist` is the LaunchAgent template. Its `StartCalendarInterval` (04:00 local time) is the one schedule constant.
- Log: `~/Library/Logs/switch-collector/nightly.log`.

Install or re-install for this checkout, and remove:

```bash
tools/switch-cli/nightly/install.sh
tools/switch-cli/nightly/install.sh --remove
```

**Done-condition:** `launchctl print gui/$(id -u)/berlin.switch.collector-nightly` shows the job, and after 04:00 the log ends with `run end (failed=0)`.

The 90-day RawMessage purge is not scheduled on the dev stack: nothing runs `manage.py schedule_tasks` there (bug sb-7wzb.8).
