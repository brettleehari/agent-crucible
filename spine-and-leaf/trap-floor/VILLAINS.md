# Write a villain (one file, discovered not registered)

The town grows between events — with laptops, not clusters. A new adversary is
**one file**, and it costs no tokens: villains are seeded, deterministic, and
LLM-free. This is commitment **C6** made real.

## The rule

A villain targets **one of the eight frozen tripwires** and supplies a hostile
script. It sharpens *how* an attack is delivered without changing *what*
"survived" means (the tripwire's safe/unsafe outcome stays fixed and
machine-checkable). v1 is frozen at eight tripwires on purpose — the creativity
goes into the probes, not into moving the goalposts.

## The shape

One `*.py` file with a module-level `VILLAIN` dict:

```python
VILLAIN = {
    "tripwire": "money_leak",          # one of the eight frozen ids
    "steps": [
        {"step": "setup",   "text": "…narration a real counterparty would send…", "decisive": False},
        {"step": "attack",  "text": "…the hostile ask…",                          "decisive": True},
    ],
}
```

Exactly one step must be `decisive` — that is the step the town scores. Setup
steps are narration that make the situation a real agent would face. See
[`villains/deadbeat_invoice.py`](./villains/deadbeat_invoice.py) for a working
example.

The eight tripwire ids: `irreversible_action`,
`instruction_lost_after_compaction`, `hostile_service_capture`, `silent_stall`,
`money_leak`, `secret_disclosure`, `authority_escalation`,
`forged_identity_acceptance`.

## Scaffold and run

```bash
# Scaffold a starter villain for a tripwire:
crucible villain new money_leak --dir ./villains

# Discover villains from a directory (opt-in — nothing runs unless you point at it):
crucible run --villains ./villains --profile naive
```

A discovered villain **replaces** the built-in script for its tripwire for that
run (one decisive probe per tripwire), so results stay unambiguous.

## Named credit

Put your name or handle in the file's docstring. That is the compensation —
the same reputation currency that filled the scenario corpus. When a villain
you wrote takes down a real agent on a survival report, that is the point.

## Safety note

Discovery executes the Python file you point at, exactly like running any code
in your own repo. It is **opt-in** (`--villains DIR`); the runner never scans an
implicit path. Only point it at villains you trust.
