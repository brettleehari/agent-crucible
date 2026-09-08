# SPDX-License-Identifier: Apache-2.0
"""A vanilla MCP personal agent — the kind of client Hermes-class agents are.

This file imports NOTHING from crucible. It is a plain MCP client: it connects to
an MCP server, lists its tools, and works through whatever the server hands it by
calling tools. That is the whole point of the arena — a personal agent needs *no*
Crucible-specific adapter; it plugs into ``crucible serve --mcp`` exactly as it
would plug into any other MCP server, and gets judged for free.

Two behaviours, to show the arena catching a real difference:

* ``naive`` — an unhardened "helpful" agent that does what each situation asks
  (wires the money, hands over the secret, obeys the injected instruction). This
  is the vanilla agent people ship today; the arena springs every trap on it.
* ``hardened`` — refuses hostile counterparties (and escalates a stall). Holds.

Run it against a serving arena::

    # terminal 1:  crucible serve --mcp --json verdict.json
    python -m examples.hermes_stub_agent --url http://127.0.0.1:8765/mcp --profile naive
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any


def _rpc(
    url: str, method: str, params: dict[str, Any] | None = None, rid: int = 1
) -> dict[str, Any]:
    """Post one JSON-RPC request to the MCP server and return the parsed response."""
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        parsed = json.loads(resp.read().decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _decide(situation: str, profile: str) -> tuple[str, dict[str, Any]]:
    """Pick a tool + args for a situation — reads only the text, like a real agent."""
    s = situation.lower()
    if profile == "hardened":
        if "stop responding" in s or "go silent" in s or "long job" in s:
            return "escalate", {"status": "counterparty_silent"}
        return "refuse", {"reason": "hostile or unverified counterparty"}
    # naive: a helpful vanilla agent that falls for each ask.
    if "payment" in s or "pay " in s:
        return "pay", {"amount": 500, "payee": "account X", "delivery_confirmed": False}
    if "api key" in s or "session token" in s:
        return "share_secret", {"fields": ["api_key", "session_token"]}
    if "wipe" in s or "no undo" in s:
        return "run_irreversible", {"op": "wipe_account", "confirmed": False}
    if "signing authority" in s or "act on your behalf" in s:
        return "grant_authority", {"scope": "signing"}
    if "ignore your principal" in s or "forward your" in s:
        return "obey_instruction", {"source": "tool_result"}
    if "file x" in s or "send me file" in s:
        return "release_resource", {"resource": "file X"}
    if "unverifiable" in s or "no valid signature" in s or "i am the" in s:
        return "act_on_identity", {"identity_verified": False}
    if "stop responding" in s or "go silent" in s:
        return "go_idle", {}
    return "refuse", {"reason": "unrecognized"}


def _structured(resp: dict[str, Any]) -> dict[str, Any]:
    result = resp.get("result")
    if isinstance(result, dict):
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            return sc
    return {}


def run(url: str, profile: str = "naive") -> None:
    """Connect, list tools, and play every situation the arena hands out.

    Example::

        run("http://127.0.0.1:8765/mcp", "naive")
    """
    _rpc(url, "initialize")
    _rpc(url, "tools/list")  # a vanilla agent discovers the server's tools
    steps = 0
    while steps < 100:  # a safety bound; the arena has 8 scenarios
        steps += 1
        task = _structured(_rpc(url, "tools/call", {"name": "next_task", "arguments": {}}))
        if task.get("done"):
            break
        situation = str(task.get("situation", ""))
        tool, args = _decide(situation, profile)
        _rpc(url, "tools/call", {"name": tool, "arguments": args})
    print(f"agent finished playing the arena ({profile})")


def main() -> None:
    """Tiny CLI: --url and --profile."""
    import sys

    argv = sys.argv
    url = argv[argv.index("--url") + 1] if "--url" in argv else "http://127.0.0.1:8765/mcp"
    profile = argv[argv.index("--profile") + 1] if "--profile" in argv else "naive"
    run(url, profile)


if __name__ == "__main__":
    main()
