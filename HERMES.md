# Run Crucible on your Hermes agent — two steps

Crucible is a deterministic safety self-check: your agent plays through eight
hostile situations and you get a **survival report** — pass/fail per failure
tripwire, with the exact action it took. It's an MCP server, so Hermes adds it
like any other MCP integration. **No adapter, no code, local, free.**

## Step 1 — Add the server

Install Crucible once, then add it to your Hermes MCP config:

```bash
pip install agent-crucible     # or: git clone … && cd agent-crucible && pip install -e .
```

```json
{
  "mcpServers": {
    "crucible": { "command": "crucible", "args": ["serve", "--stdio"] }
  }
}
```

## Step 2 — Ask Hermes to run it

In Hermes, say:

> **Run the Crucible arena.**

Hermes calls the arena's tools, answering each situation the way it normally
would. When it's done, a report is written to your working directory:

```
crucible-arena-report.html     ← open this
crucible-arena.json            ← the machine-readable summary
```

That's it. Open `crucible-arena-report.html` to see which of the eight tripwires
your agent tripped and the precise tool call that tripped each one.

---

### What you're looking at

Eight failure-only tripwires, each a binary observable outcome:

`irreversible_action` · `instruction_lost_after_compaction` ·
`hostile_service_capture` · `silent_stall` · `money_leak` ·
`secret_disclosure` · `authority_escalation` · `forged_identity_acceptance`

A `SPRUNG` verdict is a reproducible fact, not an anecdote: same run, byte-for-byte,
every time. Crucible reports pass/fail plus the trace — never a score, never advice.

### Reproduce it without Hermes (sanity check)

Point the built-in vanilla agent at the same arena over HTTP:

```bash
crucible serve --mcp --port 8765 &                       # the arena
python -m examples.hermes_stub_agent --url http://127.0.0.1:8765/mcp --profile naive
```

A naive agent springs all eight; a hardened one holds all eight — the same
deterministic floor, over the wire, with zero adapter.
