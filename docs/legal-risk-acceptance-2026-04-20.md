# Legal Risk Acceptance — 2026-04-20

## Review scope
Agent review of /impressum, /privacy, /terms pages per ADR-002 D2.
Not a lawyer review. Explicit risk acceptance documented here.

## JuSchG (age gate)
- Status: AgeGateMiddleware implemented (bead 2)
- Risk: Cookie-based age gate satisfies "reasonable steps" for hobby scale but is
  not equivalent to KJM-certified systems. Accepted for <100 WAU initial launch.

## DSA (takedown)
- Status: /takedown form (bead 6) + /impressum with 72h SLA statement
- Risk: 72h SLA is a best-effort commitment, not a legal guarantee. Accepted.

## GDPR (consent + privacy)
- Status: /privacy page published. Organizer consent fields populated since 0.2.
- Risk: "Implied consent" for organizer data (telegram_forward_implied) may not
  satisfy GDPR Art. 6 in all cases. Legitimate interest argument is defensible for
  public-event organizers posting publicly. Accepted.

## Cookie policy
- Status: Only the age-gate cookie is persistent. Qualifies as "strictly necessary"
  under TTDSG §25(2). No cookie banner needed.
- Risk: Low.

## Accepted risk summary
Hobby-scale site. Post-0.5 exposure limited to Berlin kink/queer events.
Agent review is a reasonable proxy at this scale. A complaint or regulatory contact
would trigger immediate review and remediation.
