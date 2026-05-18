# Raw scout records — Switch Berlin competitive scan, 2026-05-18

Raw JSON output from each `feature-scout` subagent dispatch. The synthesized brief lives at `../scout-features-switch-berlin-2026-05-18.md` — these files are the evidence layer behind it.

## Round structure

- **R1 (round 1):** initial fan-out across all 5 platforms. Auth state was uncertain — Redlights came back fully authenticated (dashboard URLs returned live UI), but Diversia / FetLife / Upwork / Luma scouts leaned heavily on `/help/` and `support.*` docs because of partial or no auth.
- **R2 (round 2):** user confirmed authenticated Chrome session was active. Re-scouted Diversia, FetLife, Upwork, Luma with explicit "prioritize authenticated UI over docs" framing. Redlights was NOT re-scouted (R1 already had `ui-screenshot` evidence from the live dashboard).

## Files

| Platform   | Round used in synthesis | Raw file                       | Records |
| ---        | ---                     | ---                            | ---     |
| Redlights  | R1                      | `redlights-r1.json`            | 25      |
| Diversia   | R2 (R1 archived)        | `diversia-r2.json` / `diversia-r1.json` | 25 / 25 |
| FetLife    | R2 (R1 archived)        | `fetlife-r2.json` / `fetlife-r1.json`   | 26 / 25 |
| Upwork     | R2 (R1 archived)        | `upwork-r2.json` / `upwork-r1.json`     | 26 / 25 |
| Luma       | R2 (R1 archived)        | `luma-r2.json` / `luma-r1.json`         | 25 / 25 |

The R1 files for the four re-scouted platforms are kept for completeness — they show what the scout could see WITHOUT auth (docs/marketing surface only) and serve as a contrast against the R2 authenticated record. The synthesis brief weighs R2 evidence over R1 wherever they conflict.

## Schema

Each record follows the `feature-scout` agent's schema:

- `platform` — platform name string
- `name` — feature short name
- `description` — one-paragraph description
- `category` — coarse bucket the scout chose (NOT canonical — synthesis re-clusters by job)
- `source_url` — where the evidence was observed
- `source_type` — one of `docs`, `pricing-page`, `marketing-page`, `ui-screenshot`, `changelog`, `third-party`
- `evidence_quote` — verbatim text from the source
- `captured_at` — ISO date
- `pricing_tier` — which subscription/membership tier the feature requires, or `"all-plans"` / `"no-tiers"`
- `maturity` — typically `"GA"`
- `inferred` — boolean; `true` means the scout extrapolated rather than directly observed
- `screenshot_path` — path to screenshot if `--screenshots` was on (off this run)

## Caveats

- Scout records reflect what each subagent observed in its own browser tab on 2026-05-18. Some pricing values, UI affordances, or paywall boundaries shift quickly on social platforms — re-verify before quoting in any external deliverable.
- The Upwork account observed is an inactive Basic-plan freelancer profile (the user's ex-cofounder's). Earnings/JSS/proposal-funnel widgets render with zero values — UI *shape* is high-credibility, distributional *values* are not.
- Luma host-side surfaces (guest list, blast composer, check-in tools, host analytics) were not directly observed because the user's account had 0 hosted events at scout time. R2 Luma records for host-tools come from `help.luma.com` docs, not live UI.
