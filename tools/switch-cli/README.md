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
