# Crucible — Spine and Leaf, applied

This directory is Spine and Leaf run on itself: one **Spine** (the
immutable customer narrative), **seven Leaves** (each authored by its own agent,
deriving from the Spine), a **role-agent** per Leaf so the cell can re-author on
the next Spine version, and the **trap-floor town** the product actually ships —
the seeded villains any agent can be tested against.

The product the cell builds, in one sentence:

> **Clone the repo, point it at your agent, and one command tells you whether it
> survives a town full of deterministic villains — pass/fail with a replayable
> trace, on your laptop, for free.**

## The map

```
spine-and-leaf/
├── SPINE.md                 # the one truth — customer narrative + commitments C1–C6
├── leaves/                  # seven Leaves, each authored by an agent, each traces to the Spine
│   ├── architecture.mmd     #  Architect   — Build-vs-Leverage system diagram (the moat, legible)
│   ├── report.html          #  Engineer    — survival-report UI scaffold (every real state)
│   ├── tour.yml             #  GTM         — the value tour, in the builder's language
│   ├── design.md            #  Designer    — interaction states + determinism as the trust signal
│   ├── traceability.csv     #  Compliance  — every feature → a commitment → a real test
│   ├── sequencing.yml       #  Sequencing  — the work graph (built pieces marked done)
│   └── decisions.yml        #  Decisions   — the real architectural calls, resolved with reasoning
└── trap-floor/               # THE PRODUCT — the town any agent walks into
    ├── town.yaml            #  the eight seeded villains, agent-agnostic, deterministic
    └── README.md            #  enter the town in one command
```

The runnable engine behind it all lives in
`../crucible/` (engine, tripwires, adapter, traps, report) with the CLI
`crucible run`. The Leaves render that real code — they are not a separate
fiction.

## The cell (each Leaf is an agent)

Seven role-agents in [`../../.claude/agents/`](../../.claude/agents/) — `leaf-architect`,
`leaf-engineer`, `leaf-gtm`, `leaf-designer`, `leaf-compliance`, `leaf-sequencing`,
`leaf-decisions`. Each reads `SPINE.md` and authors exactly one Leaf. The five
disciplinary agents run in parallel from the Spine; the two meta-agents
(Sequencing, Decisions) author from the Spine **plus** the five disciplinary
leaves, so they route real work and surface real disagreements. When the Spine
changes, bump `spine_version` and re-run the agents — the Leaves regenerate to
match. That is the "single source, agents converge on it" property, made
operational.

## Start here

- **To use the product:** [`trap-floor/README.md`](./trap-floor/README.md) — put
  your agent in the town.
- **To understand the moat:** [`leaves/architecture.mmd`](./leaves/architecture.mmd).
- **To see the truth everything derives from:** [`SPINE.md`](./SPINE.md).
