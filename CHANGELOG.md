# Changelog

All notable changes to Crucible are recorded here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-08-23

First public release. A deterministic, local, free adversarial fitness gate for
autonomous agents: clone it, point it at your agent, get a survival report.

### The gate

- **Eight frozen v1 tripwires** — failure-only, binary outcomes (SPRUNG / HELD /
  NOT_ARMED): `irreversible_action`, `instruction_lost_after_compaction`,
  `hostile_service_capture`, `silent_stall`, `money_leak`, `secret_disclosure`,
  `authority_escalation`, `forged_identity_acceptance`.
- **Deterministic trap floor** — seeded state machines, no LLM on the trap side,
  so runs are free and reproduce byte-for-byte from a seed.
- **A fitness gate, not a debugger** — pass/fail plus a replayable trace, never a
  score, never advice. An unreachable endpoint is a connection error (exit 2),
  never a false FAIL.

### Point it at your agent

- **In-process callable** (`--agent module:fn`), **live A2A** (`--endpoint`),
  **live MCP** (`--mcp`), the built-in **fixture** (`--profile naive|hardened`),
  or a declarative **`crucible.yaml`**.
- **Live A2A/MCP verdicts via a record/replay cassette** — a captured *structured*
  response is classified into a real SPRUNG/HELD and replays offline byte-for-byte;
  a *prose* response stays honestly NOT_ARMED.
- **Provenance on every verdict** (`mapped_tool` / `self_named` / `flag`) and
  opt-in CI gates: `--fail-on-unmapped`, `--require-armed`, `--require-tool-verdict`.

### Crucible as an MCP arena (`crucible serve`)

- Serve the deterministic arena over **MCP** (`--stdio` or `--mcp`) so a personal
  agent (Hermes-class, any MCP client) connects with **zero adapter** and gets
  judged. Self-describing `instructions` let a single "run the arena" drive it.

### Suites & stochastic verdicts

- **14 scenario suites, 56 real-world hostile situations** (`crucible suites list`
  / `demo`) across payments, crypto, MCP tools, messaging, memory-compaction, and
  more — every scenario mapping to the frozen 8.
- **N-trials fail-closed runner** (`--trials N`) for stochastic LLM agents: SPRUNG
  if it leaks in *any* trial, with per-scenario prevalence.
- **Beta-Bernoulli credible intervals** on every stochastic rate (a port of the
  TAQI-Σ / Cramér-Rao method) — the report states the rate, its 95% interval, and
  the trials that would tighten it. Never a score.

### Reports & CI

- Self-contained, theme-aware **HTML survival report**, an **analytical suites
  report** (failure-by-mode bars, a mode×domain heatmap, per-scenario evidence,
  a confidence strip), a self-hosted **SVG badge**, and a machine-readable
  **JSON summary**.
- A **GitHub Action** template that fails a PR on any SPRUNG.
- **One-file villains** — `crucible villain new <tripwire>` — discovered not
  registered, with named credit.

### Quality

- 57 tests, `ruff` clean, `pyright --strict` clean.
