# ADR-019: Switch agent harness as a product — capability-in-CLI, REST+CLI portability seam, capability-ladder isolation

**Status:** EXPLORATORY 2026-06-15
**Parent:** [ADR-011 D1 — personal-agent layer additive](ADR-011-personal-agent-layer-additive.md)
**Scope:** `agent-harness` — how the agent-extended layer (ADR-011) is *packaged, shipped, and made portable* as a product for Switch's users (and later other agent harnesses + standalone). ADR-011 decides *which features* live in agent-extended scope; this ADR decides *how that scope is distributed*. Adjacent to ADR-016 D3 (co-equal REST clients), ADR-018 D4 (capability-ladder), ADR-008 D2 (no speculative abstraction), ADR-003 (cheap foresight).

**Flag-for-consolidation:** the ADR-008 D7 overlap check (2026-06-15) scored ADR-011 adjacency high. Kept as a separate file because distribution/packaging/portability is genuinely new decision space versus ADR-011's feature-placement question, and because this is a churning EXPLORATORY direction that shouldn't bloat a stable FLEXIBLE ADR. If dogfooding shows the two collapse into one concern, fold this into ADR-011 in place (ADRs evolve in place; no supersession).

## Context

The 2026-06-15 strategic pivot (see bd memory `challenge-driven-dogfood-as-design-main-thread`) reframed Switch's work around challenge/journey walks where, for the dogfood, **Claude Code literally acts as the user's distribution agent** — driving existing endpoints + `switch-cli`, drafting and toning copy, handing the user a studio link, placing drafts, reporting. Walking the journey this way surfaced a second-order realization: **the agent harness we build to drive Switch is itself a product** we will want to ship to our users — and later to other agent runtimes (pi, Codex) and as standalone installable pieces.

ADR-011 D1 already places skills/CLIs/MCP/glue in agent-extended scope and names "Pi-agent in Rust, Codex-flavored agents in Go" as future consumers. What it does *not* decide is the packaging discipline: which lever carries load-bearing capability, what the portability seam is, how a user installs *only what they need*, and how we keep our own operator substrate distinct from the product harness. Without that discipline, two failure modes loom: (a) capability accretes inside Claude-Code-only skills, silently excluding every other harness and humans/CI; (b) we prematurely build a cross-harness publishing/adapter layer with no real second consumer (an ADR-008 D2 violation) and an ADR-003 violation (shaping a portability layer around an API that may never exist).

The orienting good news (recall, 2026-06-15): most of the portability is *already designed*. ADR-016 D3 deliberately chose raw REST + a dogfooded skill doc over per-harness SDKs precisely so pi/Codex work as co-equal clients; `switch-cli` is already the CLI-over-bash surface; ADR-018 D4 already models capability unlocked by what the user installs locally. This ADR canonicalizes the discipline that keeps those properties cheap, and consciously builds **no** new machinery now.

## Decisions

### D1: Capability in the CLI, convenience in the skill

**Firmness: EXPLORATORY** — a direction grounded by the first dogfood walks; iteration is the contract.

Every load-bearing *capability* (an atomic operation against the API / a platform / the filesystem / a browser) lives in a **CLI verb** (`switch-cli` is the seed). Claude-Code-only **skills, hooks, and commands** are thin *convenience* wrappers that teach Claude how to think about and trigger those verbs — they hold judgment and orchestration, not the doing. When a walk makes us reach for a skill/hook that *does* something rather than thinks, that is the signal to push the doing down into a CLI verb and let the skill wrap it.

**Rationale:**
- `external:` `/design-claude-extension` (skills-design + cli-design references) — the CLI-over-bash surface is the *only* path for an agent with no MCP client (pi), and it simultaneously serves humans, CI, and Codex. A capability that lives only in a Claude-Code skill is structurally unreachable by every other harness.
- `reasoned:` "design around Claude Code first" stays compatible with "publish to pi/Codex/standalone later" at ~zero cost only if the capability never lived in a Claude-only place to begin with. The split makes future portability a no-op rather than a rewrite.
- `external:` token economics (`/design-claude-extension`) — a CLI amortizes into one short discovery-doc read on demand; an equivalent MCP surface loads every tool schema always. Capability-in-CLI is also the cheaper runtime surface.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Capability in skills; CLI only where forced | `reasoned:` silently excludes pi/humans/CI/Codex — the exact harness-as-product audience. Defeats the portability goal at the root. |
| Capability in MCP tools by default | `external:` `/design-claude-extension` — MCP earns its keep only for OAuth/long-lived-shared-state/streaming/pre-existing-server; auth alone is not a reason. Heavier (always-loaded schemas), and excludes bash-only agents unless a CLI also ships. |
| No rule — per-primitive judgment | `reasoned:` invites capability to accrete in whichever lever is convenient at the moment (usually the skill being written), reproducing failure mode (a). The rule is the discipline that prevents the drift. |

**What would invalidate this:** a load-bearing capability proves genuinely unexpressible as a CLI verb at acceptable quality (e.g. it intrinsically needs long-lived streaming/shared state) — that capability earns MCP per `/design-claude-extension`, and the rule narrows to "CLI by default, MCP on the named exceptions." Or: the harness-as-product ambition is abandoned and Switch stays Claude-Code-only forever, collapsing the rule to moot.

### D2: Portability seam = the existing REST contract + the CLI — not a per-harness SDK/adapter layer

**Firmness: EXPLORATORY** (leans on ADR-016 D3, FLEXIBLE).

Cross-harness reach is carried by two already-chosen surfaces: the **co-equal REST API** (ADR-016 D3/D6) and the **CLI** (D1). We do **not** build a per-harness SDK, adapter layer, or `Publishable`-style portability abstraction. Other harnesses consume Switch the same way Claude Code does — over REST, optionally via the CLI — and a dogfooded skill/usage doc (ADR-016 D3 Tier-2, deferred) is the portable knowledge artifact, not generated client libraries.

**Rationale:**
- `external:` ADR-016 D3 already rejected SDK-per-language in favor of raw REST + dogfooded skill doc *specifically so* non-anticipated harnesses (Pi/Rust, Codex/Go) work. This ADR adopts that as the outbound seam too rather than re-litigating it.
- `external:` ADR-008 D2 — building a publishing/adapter layer before a real second consumer is speculative behavioral abstraction; extract from the third diverging caller, not the first.
- `external:` ADR-003 — cheap foresight is data shape + naming, never a speculative API/portability layer; the "What this does NOT include" list explicitly refuses to shape a layer around an API that may not exist.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Generate an SDK per harness (Python/Rust/Go) | `external:` ADR-016 D3 — maintenance burden, lags the contract, and the contract itself is the portable artifact; rejected there, not re-opened here. |
| Build a cross-harness publishing/adapter framework now | `external:` ADR-008 D2 + ADR-003 — no real second consumer yet; speculative machinery. Defer until a concrete second harness consumes a concrete primitive. |

**What would invalidate this:** a second real harness consumer hits genuine friction the raw REST + CLI + skill-doc seam cannot absorb (repeated, observed — not anticipated). That is the ADR-008 D2 "third caller" signal to design a thin shared artifact, and the moment to author the deferred publishing decision (see Open questions).

### D3: Dependency isolation via capability-ladder + a primitive ledger

**Firmness: EXPLORATORY.**

A published primitive's capability is unlocked by **what the user installs locally** — the platform never custodies it (the generalized shape of ADR-018 D4's capability ladder: no agent → bot+public reach; +agent → private-draft reach). A user installs **only what they need**, not our whole substrate. The cheap-foresight mechanism (ADR-003-legal: data/naming + tracking only, *no* machinery) is a **primitive ledger** — a plain doc tracking, per primitive we build or reuse during a walk: `name · lever-type (CLI/skill/hook/subagent/MCP/plugin) · dependencies · portability status (Claude-only / CLI-portable / published)`. The ledger lives at [`docs/harness-primitive-ledger.md`](../harness-primitive-ledger.md).

**Rationale:**
- `external:` ADR-018 D4 — the capability-ladder (local install unlocks the tier; metadata-only syncs upward; server-held session deferred) is already the validated isolation seed; this generalizes its shape to all published primitives.
- `reasoned:` "users install only what they need" requires knowing each primitive's dependency closure; the ledger captures that at authoring time, when the context is in hand, at ~zero cost — versus reverse-engineering it at publish time.
- `external:` ADR-003 — tracking + naming is cheap foresight; building a packaging/vendoring system now would not be.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Ship the whole substrate as one bundle | `reasoned:` forces users to install our entire harness for one capability; the opposite of dependency isolation. |
| Build a package/dependency-resolution system now | `external:` ADR-008 D2 / ADR-003 — speculative machinery with no consumer; the ledger is the zero-cost stand-in until publishing is real. |
| Track dependencies later, at publish time | `reasoned:` the authoring context (what a primitive actually depends on) is freshest at build time; deferring loses it and makes isolation expensive retroactively. |

**What would invalidate this:** the capability-ladder shape fails for a primitive whose capability cannot be cleanly unlocked by local install alone (e.g. it structurally needs a server-custodied secret) — revisit per the ADR-018 D4 server-held-session deferral. Or: the ledger goes stale/unused across several walks, signaling it isn't the right cheap-foresight surface (replace, don't prop up).

### D4: Two distinct harnesses — do not conflate the operator's substrate with the product harness

**Firmness: EXPLORATORY.**

There are **two** harnesses, with different audiences, repos, dependencies, and packaging:
- **(a) Personal substrate harness** — the operator's own skills/agents/prompts, projected across Claude Code / pi / Codex via the personal substrate tooling (`sync-substrate`) and published to the operator's public `harness/` repo via the existing `publish-harness` skill. **Audience: the operator.**
- **(b) Switch *product* harness** — the skills/CLIs/hooks we ship to **Switch's users** so their agents can drive Switch. **Audience: our users.** Different repo, different dependency closure, different packaging, different scrub rules.

`publish-harness` is **inspiration for the pattern** (scrub private content, plumbing-vs-methodology split, produce a standalone scrubbed artifact) but is **not reusable as-is** — it is specific to publishing the operator's personal harness assets. A Switch-product-harness publishing path is its own greenfield artifact, **deferred** (build nothing now per ADR-008 D2).

**Rationale:**
- `direct:` user-explicit, 2026-06-15 — "publish-harness can inspire us but will need to be completely changed cause it's very specific to publishing some skills and agent harness assets in the harness/ repo which is not the same thing as our Switch agent harness."
- `reasoned:` conflating the two would route Switch product-harness publishing through operator-substrate scrub rules and repo conventions that don't fit (different private-content boundary, different audience-appropriate docs), producing leakage or mis-packaging.
- `external:` ADR-008 D2 — building the product-harness publishing path before it has a real consumer is premature; naming the boundary now is cheap, building the path now is not.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Reuse `publish-harness` directly for the product harness | `direct:` user-explicit — it is specific to the operator's `harness/` repo and asset shapes; wrong scrub boundary and audience for a product harness. |
| One unified harness for operator + users | `reasoned:` collapses two different audiences/repos/scrub-rules into one, leaking operator substrate toward users or constraining the product harness to operator conventions. |

**What would invalidate this:** the two harnesses' packaging/scrub needs turn out genuinely identical in practice (observed across a real product-harness publish), making the distinction overhead rather than protection — then unify. Until a product-harness publish is actually attempted, the boundary stands as the cheaper default.

### D5: Reuse composable primitives where real; do not abstract a shared primitive until the third caller

**Firmness: EXPLORATORY.**

Reuse existing clean primitives where a real need exists — e.g. `browser-automation` as the studio read-back "eyes" (already the canonical reuse instance; see bd memory `studio-composer-browser-readback-recipe`). But per ADR-008 D2, do **not** abstract a *new* shared primitive until the third diverging caller; the D3 ledger tracks each reuse so later isolation/publishing stays cheap.

**Rationale:**
- `external:` ADR-008 D2 — extract from the third diverging caller, not the first; premature shared-primitive abstraction is the named anti-pattern.
- `reasoned:` reuse of an *already-clean* primitive (browser-automation) is free and good; *minting* a shared abstraction speculatively is the thing D2 forbids. The distinction is reuse-of-existing vs abstract-a-new-shared.
- `direct:` user-explicit, 2026-06-15 — "We can reuse existing composable primitives like e.g. browser-automation skill ... but ofc we should keep neatly track of all dependencies so we can isolate and publish those on their own."

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Build a shared primitive library up front | `external:` ADR-008 D2 — speculative; abstract on the third caller, not the first. |
| Never reuse; reimplement per primitive | `reasoned:` wasteful and drift-prone where a clean primitive already exists (browser-automation); reuse-of-existing is not the D2 anti-pattern. |

**What would invalidate this:** a primitive reaches its third diverging caller — the D2 signal to extract a shared abstraction (and ledger it). Or: a reused external primitive (e.g. browser-automation) proves too entangled with the operator substrate to publish standalone, forcing a vendoring/forking decision (ledger surfaces this).

## Consequences

### Direct
- New harness-layer bead `--design` cites this ADR and names, per the primitive it builds: the lever (D1), the dependency closure + portability status (D3 ledger row), and whether it's product-harness or operator-substrate (D4).
- `switch-cli` is the default home for new load-bearing capability; skills/hooks wrap it. A new skill that *does* something is a review flag to push the doing into the CLI.
- The primitive ledger is updated as walks build/reuse primitives — it is the running dependency-isolation surface, not a one-time doc.
- No cross-harness publishing, SDK, adapter, or packaging machinery is built until a real second consumer exists (D2/D5).

### Carried forward
- ADR-011 D1 — feature placement (core web-UI-complete vs agent-extended); this ADR adds the packaging/distribution discipline for the agent-extended layer it defines.
- ADR-016 D3/D6 — co-equal REST contract is the portability seam; the deferred skill-doc extraction (Tier-2) is the portable knowledge artifact.
- ADR-018 D4 — capability-ladder is the dependency-isolation seed this ADR generalizes.

### Risk
- "Capability vs convenience" is judgment-laden — risk of capability creeping into skills under deadline. Mitigation: the review flag ("a skill that *does* something → push to CLI") and the ledger's portability-status column make Claude-only capability visible.
- The ledger can rot if not maintained. Mitigation: D3's invalidation signal — a stale/unused ledger across walks means replace the mechanism, don't prop it up.
- EXPLORATORY churn — these decisions will move as the first walks ground them; downstream readers must treat them as a direction, not a fixture.

## canonical_refs
- [ADR-011 D1](ADR-011-personal-agent-layer-additive.md) — parent; agent-extended scope this ADR packages and ships.
- [ADR-016 D3](ADR-016-outbound-syndication-architecture-event-post-projections.md) — co-equal REST clients + raw-REST-not-SDK portability bet + deferred dogfooded skill doc (Tier-2); D5 actor-attested publish verbs; D6 single shared auth/service layer.
- [ADR-018 D4](ADR-018-channel-push-mechanisms-and-draft-only-mtproto-posture.md) — capability-ladder / local-install isolation seed generalized in D3.
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — no speculative abstraction (the primary brake on D2/D4/D5); D3/D4 fail-loud + retry posture bind any I/O-bearing primitive.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — cheap foresight = data shape + naming only; governs the ledger-not-machinery choice in D3.
- [`docs/harness-primitive-ledger.md`](../harness-primitive-ledger.md) — the D3 primitive ledger.
- bd memory `challenge-driven-dogfood-as-design-main-thread` — the dogfood walks (Challenge 0, `kb-k2ds`) are where this ADR gets grounded.
- bd memory `studio-composer-browser-readback-recipe` — the canonical browser-automation reuse instance (D5).

## Open questions deferred

| Question | Resolution path |
|---|---|
| **Firmness cliff at V1.** ADR-008 D1's "refactor hard, no back-compat" expires at V1 — exactly when published-to-other-harness primitives gain external consumers and need a stability/compat posture. | Not decided here. Author a compatibility-posture decision (or evolve this ADR) when the first product-harness primitive acquires a real external consumer. |
| **Product-harness publishing path** (the D4(b) artifact). | Greenfield, deferred per ADR-008 D2. Author when a concrete primitive is ready to ship to users; `publish-harness` informs the pattern, not the implementation. |
| **When to extract the deferred dogfooded skill doc** (ADR-016 D3 Tier-2). | When a second real harness consumer exists (D2 invalidation signal). |
