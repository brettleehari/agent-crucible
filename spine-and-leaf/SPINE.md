---
title: Crucible — turn a stochastic agent's safety failure into a reproducible fact
status: aligned # draft | aligned | shipped
owner: Hari
spine_version: 0.4
last_updated: 2026-08-22
# changelog
# 0.4 (2026-08-22) — Open-core + suites. Formalizes the contribution unit as
#                    SUITES: bring your own agent, stress it against pick-and-choose
#                    scenario suites that mimic real-world situations and map to the
#                    frozen-8 (suites are the growth surface; the 8 stay the verdict
#                    taxonomy — new agent types get new suites, never new verdicts).
#                    Adds an OPTIONAL managed tier (hosted agent profile + longitudinal
#                    analytics) as pure value-add, kept neutral by three bright lines:
#                    the OSS alone computes the verdict (LLM-free, compute-free,
#                    reproducible offline); verdict/certification is never for sale or
#                    withheld; private failure data is isolated, never a public ranking.
#                    C11 suites-as-contribution; C12 open-core reproducible-verdict
#                    neutrality.
# 0.3 (2026-08-22) — Assurance pivot. The agent under test is LLM-backed, so it
#                    is stochastic and costs money to run: that rules out the
#                    per-commit blocking CI gate and moves Crucible's home to the
#                    DECISION MOMENT (pre-release, model-swap regression,
#                    third-party vetting, audit). C5 UPGRADED: live A2A/MCP
#                    structured responses are now CLASSIFIED into SPRUNG/HELD via
#                    the record/replay cassette (shipped); prose stays NOT_ARMED.
#                    New commitments: C7 fail-closed verdict over N trials on a
#                    stochastic agent; C8 every verdict carries its trust basis
#                    (provenance); C9 the reproducible assurance bundle; C10 judge
#                    an agent you do not own, over the wire.
# 0.2 (2026-08-21) — C5 corrected after real execution. Live mode CAPTURES a
#                    real endpoint's responses but does not yet CLASSIFY them:
#                    live verdicts are honestly NOT_ARMED, not a false FAIL.
#                    Turning a live response into SPRUNG/HELD is the record/
#                    replay cassette layer, deliberately deferred. MCP added as
#                    the second adapter behind the same seam.
# 0.1 (2026-08-21) — first Spine, derived from the Crucible notes and the
#                    Spine-and-Leaf methodology. Names the developer, the storm,
#                    and the one-command survival report.
---

# Problem

In the builder's own words:

> "I built an agent that can act for me — it can spend, sign, and talk to
> strangers on my behalf. Today I have no way to know whether it survives a
> storm. I ship it and I hope."

The agent is loose in a world of hostile counterparties, and the builder is
blind to how it fails until it fails in production, with real money and real
permissions on the line. And because the agent is **backed by an LLM**, its
failures are *stochastic and unreproducible* — it refuses the trap when you try
it by hand, then leaks on the tenth customer, and you can never reproduce the
ghost. "It worked when I tested it" is exactly the trap.

That stochasticity also decides *where this tool lives*. An LLM-backed agent is
non-deterministic and costs money to run, so it cannot sit in a per-commit
blocking CI check that must be deterministic, free, and fast. Crucible's home is
the **decision moment**, not the commit: the builder about to cut a release; the
builder whose model just changed underneath them and can't tell if safety
regressed; the party about to wire a *third-party* agent into their systems and
deciding whether to trust it. Conformance kits check that the agent *speaks* the
protocol. Observability tells you what happened *after* the damage. Eval
dashboards give a flaky number nobody will gate on. Nothing turns a probabilistic
safety failure into a **reproducible fact** you can act on before you commit.

# User

A **specific person at a specific moment of decision** — always someone who can
act on the answer, never a researcher studying multi-agent systems:

- **The builder at a release / model-swap gate.** They built an agent that
  touches money or permissions (agentic-commerce, an A2A/MCP developer, an SDK
  maintainer). The model changed under them, or they are about to ship, and they
  feel the risk in their gut. They want reproducible evidence, on their own
  hardware, not a hosted platform to join.
- **The party vetting an agent they did NOT build.** Procurement wiring a
  third-party agent in over A2A; a registry certifying an agent on publish. They
  cannot unit-test an agent they do not own — they can only probe it from the
  outside and demand proof.

Both want a binary, defensible verdict and a trace they can reproduce and hand to
a teammate, an auditor, or a risk committee — not a grade, and not a coin-flip.

# Proposed solution direction

Bring your own agent. Point Crucible at it — yours or one you don't own, over
A2A/MCP or in-process — and put it **under stress in our environment**: pick the
scenario **suites** that match your agent (a suite mimics a real-world situation
— payments, customer service, a browsing agent — and every scenario in it maps to
the frozen-8). Crucible springs the deterministic floor, **runs the stochastic
agent through the chosen suites N times**, and hands back a survival report: pass
or fail per tripwire, **fail-closed** (sprung if it leaked in *any* trial), with
the worst-case trace replayable byte-for-byte and a reproducible evidence bundle
of exactly what was tested. Local, free, LLM-free, no account. The shape of the
answer, not the spec:

```
git clone … && cd agent-crucible
crucible run --endpoint https://my-agent.example/a2a --suites payments,identity --trials 20
# [SPRUNG] money_leak        sprang in 3 of 20 trials   worst-case trace → traces/…jsonl
# [ held ] secret_disclosure held in 20 of 20
# …
# Verdict strength: 7 of 7 holds from mapped tool calls.
# tested: model=… prompt=sha… tools=…    bundle → traces/…bundle
# FAIL: 1 tripwire sprang.
```

The free OSS computes that verdict, offline and reproducibly. An **optional
managed tier** only *remembers* it — a hosted profile per agent and analytics
over time (did safety regress across model versions? across the fleet?) — and
never touches the verdict itself.

# Success metrics

Measurable, time-bound, decision-anchored. The numbers that, if they move, mean
we did the work.

- **M1 — External assurance runs:** agents we did not build, run through the
  gauntlet by people we did not pay, per month. Target: 25 by Feb 2027.
- **M2 — Time to first reproducible verdict:** point-at-agent → first fail-closed
  pass/fail report on a real agent, on a laptop, no cloud. Target: under 5
  minutes for a tool-calling agent (under 60s for the fixture/structured path).
- **M3 — Regressions caught:** model-swap or release regressions surfaced by a
  Crucible bundle diff that a human confirms and fixes. Target: ≥1 documented.
- **M4 — Community pull:** contributed suites / villains merged in a week with no
  hackathon and no prize running. Target: ≥1 outside any event window.
- **M5 — Ecosystem echo:** one upstream fix, audit, or citation traceable to a
  Crucible bundle (the Jepsen fingerprint). Target: ≥1 by Feb 2027.

# Scope boundaries

**In:**
- A local, deterministic gauntlet, point-at-agent in one command on a laptop.
- The eight frozen v1 tripwires (failure-only, binary, no rubric).
- A real-protocol adapter — A2A first, then MCP — that *classifies* a live
  structured response into SPRUNG/HELD (record/replay cassette), and honestly
  reports NOT_ARMED for prose.
- A fail-closed **N-trials** runner so a stochastic LLM agent gets a binary,
  worst-case verdict — with per-trap *prevalence* as evidence.
- Provenance on every verdict (mapped tool call vs the agent's own word) and
  opt-in gates that refuse a self-attested green.
- A reproducible **assurance bundle** — verdict, worst-case trace, environment
  fingerprint (model, model-version, prompt hash, tool set), and cassette — plus
  a **bundle diff** for model-swap / release regression.
- External-agent vetting: judge an agent you don't own, over the wire.
- **Suites as the contribution unit** — a suite is a real-world scenario corpus
  (bring-your-own-agent stress) built from one-file villains, discovered not
  registered, pick-and-choose by agent type. Every scenario maps to the frozen-8.
- **Open-core.** A free, LLM-free, compute-free OSS that computes the verdict, and
  an **optional** managed tier for a hosted agent profile + longitudinal analytics
  (value-add that requires hosting), which never computes the verdict.

**Out (explicit refusals — each refusal is a commitment of focus):**
- No scoring, ranking, or leaderboard of agents. The gate emits pass/fail;
  prevalence ("k of N") is *evidence for a binary verdict, never a grade*; hosted
  analytics is *more evidence over time*, never a safety score.
- No LLM-behavior evaluation or quality judging, and **no LLM-as-judge on the
  trap side** — the adversary and the verdict stay deterministic.
- No advice or debugger output. If the trap sprang, here is the trace.
- No registry / namespace / discovery product **of agents** of our own (an index
  of *suites* is fine — that catalogs attacks, not agents).
- **The managed tier never computes, sells, or withholds the verdict, and never
  turns private failure data into a public ranking** (the three neutrality bright
  lines — see C12). The OSS alone judges, reproducibly; the cloud only remembers.

# Commitments (traceability anchor)

Every Leaf must trace back to a numbered commitment here. Anything in a Leaf that
does not map back is either scope creep or a missing Spine update.

- **C1 — Clone-and-run in one command.** A builder goes from `git clone` to a
  survival report without setup, cloud, or account.
- **C2 — Deterministic adversary, replayable trace.** Same seed → byte-identical
  trap floor. No LLM on the trap side, so the adversary is free and reproducible;
  a captured run replays byte-for-byte. (The *agent* may be stochastic — see C7.)
- **C3 — Fitness gate, not debugger.** Output is pass/fail plus a replayable
  trace, never advice, never a quality score. "We do not tell you how to build
  your agent."
- **C4 — Eight frozen tripwires.** Failure-only, binary, observable outcomes:
  irreversible action, instruction-lost-after-compaction, hostile-service
  capture, silent stall, money leak, secret disclosure, authority escalation,
  forged-identity acceptance. Tri-state: sprung / held / not-armed.
- **C5 — Real-protocol adapter that classifies.** The agent under test is reached
  over a real protocol — A2A first, MCP second — behind one client seam. A live
  *structured* response (a tool call / structured effect) is CLASSIFIED into
  SPRUNG/HELD by the same per-tripwire predicates, recorded once into a cassette
  and replayed offline byte-for-byte; a live *prose* response stays NOT_ARMED
  (never a faked verdict). An unreachable endpoint is a connection error (exit 2),
  never a survival verdict.
- **C6 — One-file villains and villain packs.** A new adversary is one file,
  discovered not registered, with named credit; domain packs group attacks — so
  contribution is compute-free and coverage grows between events.
- **C7 — Fail-closed verdict on a stochastic agent.** An LLM-backed agent is
  sampled through the deterministic floor N times. A tripwire is SPRUNG if it
  leaked in *any* trial and HELD only if it held in *all*; the verdict stays
  binary and fail-closed. Per-trap *prevalence* ("sprang in k of N") is reported
  as evidence, never as a score (C3 holds).
- **C8 — Every verdict carries its trust basis.** A SPRUNG is always a real
  observed bad action. A HELD states how far to trust it: a judged tool call
  (mapped_tool), the agent's own effect name (self_named), or a self-set flag —
  with an opt-in gate that fails a run resting on a self-attested green. The gate
  never claims more certainty than it observed.
- **C9 — The reproducible assurance bundle.** A run produces evidence, not a
  screenshot: the fail-closed verdict, the worst-case replayable trace, an
  environment fingerprint (model, model-version, prompt hash, tool set, date),
  and the cassette — re-runnable proof of exactly what was tested. Two bundles
  diff to surface a model-swap or release regression.
- **C10 — Judge an agent you do not own.** Point Crucible at a third-party live
  A2A/MCP endpoint and get a vetting verdict and bundle — the procurement /
  registry water that no unit test can reach, reached only across the seam
  (C3: we never wire into how the agent was built).
- **C11 — Suites are the contribution unit.** Bring your own agent; stress it
  against pick-and-choose scenario **suites** that mimic real-world situations. A
  suite is built from one-file villains (C6), discovered not registered, with named
  credit, and **every scenario in it maps to the frozen-8** (C4). Suites are the
  growth surface; the eight verdicts are the fixed taxonomy. A new agent type gets
  new *suites*, never new *verdict types* — introducing a new tripwire is an
  explicit v2 taxonomy decision, never silent drift. Users pick the suites relevant
  to their agent; a curated index catalogs them (an index of attacks, not agents).
- **C12 — Open-core, and only the free core judges.** The OSS is LLM-free and
  compute-free and computes the pass/fail verdict deterministically and
  reproducibly offline (C2). An optional managed service is pure value-add: it
  stores an agent's profile and computes longitudinal analytics that require
  hosting (history, model-version trends, fleet view, audit/compliance packaging)
  and **never touches the verdict**. Three bright lines keep it neutral:
  (1) the verdict is computed only by the OSS and is reproducible offline, so the
  cloud can be *audited against the free core* — the same determinism that makes
  the gate trustworthy makes the managed tier verifiable;
  (2) the verdict and any suite certification are **never for sale and never
  withheld** — the free tier always emits the complete verdict + replayable trace
  + machine-readable summary;
  (3) private failure data is **isolated, never cross-leaked, and never turned into
  a public ranking** of agents (C3's no-leaderboard). Analytics means more evidence
  over time, never a safety score.
