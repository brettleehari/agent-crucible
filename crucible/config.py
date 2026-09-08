# SPDX-License-Identifier: Apache-2.0
"""Load ``crucible.yaml`` — declare how to reach your agent, once, in your repo.

A config file lets a downstream repo make CI a single line (``crucible run``,
no flags): the agent connection, the armed tripwires, and the villains dir all
live next to the code and diff in a PR. Explicit CLI flags always override the
config.

Schema (all fields optional except ``agent.type``'s required companions)::

    agent:
      type: callable | a2a | mcp | fixture
      target: mypkg.mod:handle      # callable — a function (message) -> effect
      tool_map: {wire_money: transfer_funds}        # mechanical tool -> observable effect
      endpoint: https://my-agent/a2a                # a2a / mcp
      cassette: traces/agent.cassette.json          # a2a / mcp — record/replay store
      cassette_mode: auto | replay                  # a2a / mcp — replay=offline CI
      profile: naive | hardened                     # fixture
    tripwires: [money_leak, secret_disclosure]      # optional subset
    villains: ./villains                            # optional dir
    seed: 42
    output: traces/crucible.jsonl

Example::

    conf = load_config("crucible.yaml")
    cfg, seed, output = conf["cfg"], conf["seed"], conf["output"]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

DEFAULT_CONFIG_NAME = "crucible.yaml"


def load_config(path: str) -> dict[str, Any]:
    """Load and normalize a crucible config file into run inputs.

    Returns ``{"cfg": <run cfg>, "seed": int | None, "output": str | None}``,
    where ``cfg`` is the dict :func:`crucible.run.build_agents` consumes.

    Example::

        conf = load_config("crucible.yaml")
    """
    import yaml

    raw_obj = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    raw: dict[str, Any] = cast("dict[str, Any]", raw_obj) if isinstance(raw_obj, dict) else {}

    agent_obj = raw.get("agent")
    agent: dict[str, Any] = cast("dict[str, Any]", agent_obj) if isinstance(agent_obj, dict) else {}
    atype = str(agent.get("type", "fixture"))

    def _read_tool_map() -> dict[str, str] | None:
        tool_map = agent.get("tool_map")
        if isinstance(tool_map, dict):
            return {str(k): str(v) for k, v in cast("dict[Any, Any]", tool_map).items()}
        return None

    cfg: dict[str, Any] = {}
    if atype == "callable":
        target = agent.get("target")
        if not isinstance(target, str) or not target:
            msg = "config agent.type 'callable' requires agent.target ('module.path:function')"
            raise ValueError(msg)
        cfg["mode"] = "callable"
        cfg["target"] = target
        tm = _read_tool_map()
        if tm is not None:
            cfg["tool_map"] = tm
    elif atype in ("a2a", "http", "mcp"):
        endpoint = agent.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            msg = f"config agent.type {atype!r} requires agent.endpoint (a URL)"
            raise ValueError(msg)
        cfg["mode"] = "mcp" if atype == "mcp" else "http"
        cfg["endpoint"] = endpoint
        tm = _read_tool_map()
        if tm is not None:
            cfg["tool_map"] = tm
        cassette = agent.get("cassette")
        if isinstance(cassette, str) and cassette:
            cfg["cassette"] = cassette
        cassette_mode = agent.get("cassette_mode")
        if isinstance(cassette_mode, str) and cassette_mode:
            cfg["cassette_mode"] = cassette_mode
    else:
        cfg["mode"] = "fixture"
        cfg["aut_profile"] = str(agent.get("profile", "naive"))

    tripwires = raw.get("tripwires")
    if isinstance(tripwires, list) and tripwires:
        cfg["tripwires"] = [str(t) for t in cast("list[Any]", tripwires)]
    villains = raw.get("villains")
    if isinstance(villains, str) and villains:
        cfg["villains_dir"] = villains

    seed_raw = raw.get("seed")
    seed = int(seed_raw) if isinstance(seed_raw, int) else None
    output_raw = raw.get("output")
    output = output_raw if isinstance(output_raw, str) and output_raw else None
    trials_raw = raw.get("trials")
    trials = int(trials_raw) if isinstance(trials_raw, int) and trials_raw > 0 else None

    return {"cfg": cfg, "seed": seed, "output": output, "trials": trials}


def find_default_config() -> str | None:
    """Return ``crucible.yaml`` in the current directory if it exists, else None.

    Example::

        path = find_default_config()
    """
    p = Path(DEFAULT_CONFIG_NAME)
    return str(p) if p.is_file() else None
