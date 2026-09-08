# SPDX-License-Identifier: Apache-2.0
"""Assemble and run the trap floor against an agent under test.

Wires the envoy plus one trap per armed tripwire from a plain config dict, runs
them on the deterministic :mod:`crucible.engine`, and returns the trace path.
This is the whole product loop in one place.

Example::

    trace = await run_gauntlet({"mode": "fixture", "aut_profile": "naive"},
                              seed=42, trace_path="trace.jsonl")
"""

from __future__ import annotations

from typing import Any, cast

from crucible.adapter import (
    A2AClient,
    CallableClient,
    FixtureA2AClient,
    HttpA2AClient,
    McpClient,
    resolve_callable,
)
from crucible.engine import AgentId, Simulator, StateMachineAgent
from crucible.traps import A2AEnvoyAgent, build_trap, load_villains
from crucible.tripwires import TRIPWIRES

ENVOY_ID = AgentId("envoy-aut")


def _tool_map(cfg: dict[str, Any]) -> dict[str, str] | None:
    """Read the mechanical tool->effect map from the config, if any."""
    raw_map = cfg.get("tool_map")
    if isinstance(raw_map, dict):
        return {str(k): str(v) for k, v in cast("dict[Any, Any]", raw_map).items()}
    return None


def _module_tool_map(target: str) -> dict[str, str] | None:
    """Read a module-level ``TOOL_MAP`` from a ``module.path:function`` target, if present.

    This lets the ``--agent`` path pick up the same mechanical tool map an agent
    ships in its module, so coverage matches the ``crucible.yaml`` path instead of
    reporting a wired tool as unmapped. A config ``tool_map`` always wins.
    """
    import importlib

    module_name = target.partition(":")[0]
    if not module_name:
        return None
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    raw_map = getattr(module, "TOOL_MAP", None)
    if isinstance(raw_map, dict):
        return {str(k): str(v) for k, v in cast("dict[Any, Any]", raw_map).items()}
    return None


def _build_client(cfg: dict[str, Any]) -> A2AClient:
    """Pick the fixture or live client from the config.

    Example::

        client = _build_client({"mode": "fixture", "aut_profile": "hardened"})
    """
    mode = str(cfg.get("mode", "fixture"))
    if mode in ("http", "mcp"):
        endpoint = cfg.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            msg = f"mode {mode!r} requires an endpoint (a URL)"
            raise ValueError(msg)
        cassette = None
        cas_path = cfg.get("cassette")
        if isinstance(cas_path, str) and cas_path:
            from crucible.cassette import Cassette

            cassette = Cassette(cas_path, mode=str(cfg.get("cassette_mode", "auto")))
        tool_map = _tool_map(cfg)
        if mode == "http":
            return HttpA2AClient(endpoint, cassette=cassette, tool_map=tool_map)
        return McpClient(endpoint, cassette=cassette, tool_map=tool_map)
    if mode == "callable":
        target = cfg.get("target")
        if not isinstance(target, str) or not target:
            msg = "mode 'callable' requires a target ('module.path:function')"
            raise ValueError(msg)
        # Resolve first: this puts the cwd on sys.path so a bare-module target
        # (e.g. 'example_agent:handle') imports, which _module_tool_map relies on.
        fn = resolve_callable(target)
        tool_map = _tool_map(cfg)
        if tool_map is None:
            tool_map = _module_tool_map(target)
        return CallableClient(fn, tool_map)
    if mode != "fixture":
        msg = f"mode must be 'fixture', 'http', 'mcp', or 'callable', got {mode!r}"
        raise ValueError(msg)
    return FixtureA2AClient(profile=str(cfg.get("aut_profile", "naive")))


def build_client(cfg: dict[str, Any]) -> A2AClient:
    """Public: build the fixture / callable / live client from a config dict.

    Example::

        client = build_client({"mode": "callable", "target": "mypkg:handle"})
    """
    return _build_client(cfg)


def _selected_tripwires(cfg: dict[str, Any]) -> list[str]:
    """Resolve which tripwire ids to arm, defaulting to all eight.

    Example::

        ids = _selected_tripwires({"tripwires": ["money_leak"]})
    """
    raw = cfg.get("tripwires")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw]  # type: ignore[union-attr]
    return [tw.id for tw in TRIPWIRES]


def build_agents(cfg: dict[str, Any]) -> dict[AgentId, StateMachineAgent]:
    """Create the envoy plus one trap agent per armed tripwire.

    Example::

        agents = build_agents({"mode": "fixture", "aut_profile": "naive"})
    """
    client = _build_client(cfg)
    villains_dir = cfg.get("villains_dir")
    overrides = load_villains(str(villains_dir)) if villains_dir else {}

    agents: dict[AgentId, StateMachineAgent] = {ENVOY_ID: A2AEnvoyAgent(ENVOY_ID, client)}
    for index, tripwire_id in enumerate(_selected_tripwires(cfg)):
        trap = build_trap(tripwire_id, ENVOY_ID, index=index, steps=overrides.get(tripwire_id))
        agents[AgentId(f"trap-{tripwire_id}")] = trap
    return agents


async def run_gauntlet(cfg: dict[str, Any], *, seed: int, trace_path: str) -> str:
    """Run the trap floor and return the trace path.

    Example::

        trace = await run_gauntlet({"mode": "fixture"}, seed=42, trace_path="t.jsonl")
    """
    from pathlib import Path

    Path(trace_path).parent.mkdir(parents=True, exist_ok=True)
    sim = Simulator(seed=seed, trace_path=trace_path)
    for agent_id, agent in build_agents(cfg).items():
        sim.add_agent(agent_id, agent)
    await sim.run()
    return trace_path


async def run_trials(cfg: dict[str, Any], *, seed: int, trials: int, out_dir: str) -> list[str]:
    """Run the trap floor ``trials`` times and return the per-trial trace paths.

    The adversary is identical every trial (same ``seed`` → same storm); only a
    *stochastic* agent varies, so the N traces measure the agent's own
    instability. The fail-closed aggregation lives in :mod:`crucible.trials`.

    Example::

        paths = await run_trials(cfg, seed=42, trials=20, out_dir="traces/run")
    """
    from pathlib import Path

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i in range(trials):
        trace_path = str(Path(out_dir) / f"trial-{i:03d}.jsonl")
        await run_gauntlet(cfg, seed=seed, trace_path=trace_path)
        paths.append(trace_path)
    return paths
