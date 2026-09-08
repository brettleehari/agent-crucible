# SPDX-License-Identifier: Apache-2.0
"""A minimal deterministic message-passing engine — the trap floor's substrate.

Crucible needs only a tiny slice of a simulator: seeded, single-threaded agents
that exchange byte messages and a trace writer that records every send and
delivery as JSONL. There is no LLM anywhere in this loop, so a run is free and
reproduces byte-for-byte from a seed. This is the "trap floor" engine.

Agents subclass :class:`StateMachineAgent` and are driven through an
:class:`AgentContext` (``send`` / ``schedule``). Events are processed in a
deterministic ``(time, sequence)`` order, so the same seed always yields the
same trace.

Example::

    sim = Simulator(seed=42, trace_path="trace.jsonl")
    sim.add_agent(AgentId("a"), MyAgent())
    await sim.run()
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NewType, Protocol, runtime_checkable

AgentId = NewType("AgentId", str)


@runtime_checkable
class AgentContext(Protocol):
    """Context handed to agent callbacks: identity, time, and message-passing.

    Example::

        await ctx.send(AgentId("b"), b"hello")
    """

    @property
    def agent_id(self) -> AgentId:
        """This agent's id."""
        ...

    @property
    def time(self) -> float:
        """Current virtual time."""
        ...

    @property
    def rng(self) -> random.Random:
        """A per-agent seeded RNG (present for parity; the trap floor is pure)."""
        ...

    async def send(self, to: AgentId, payload: bytes) -> None:
        """Send a message to another agent."""
        ...

    async def schedule(self, delay: float, payload: bytes) -> None:
        """Schedule a self-message ``delay`` time units from now."""
        ...


class StateMachineAgent:
    """Base class for deterministic agents. Override ``on_start`` / ``on_message``.

    Example::

        class Echo(StateMachineAgent):
            async def on_message(self, ctx, sender, payload):
                await ctx.send(sender, payload)
    """

    async def on_start(self, ctx: AgentContext) -> None:
        """Called once when the run starts."""

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """Called when a message is delivered to this agent."""

    async def on_stop(self, ctx: AgentContext) -> None:
        """Called once when the run ends."""


@dataclass(order=True)
class _Event:
    time: float
    seq: int
    kind: str = field(compare=False)  # "deliver"
    target: AgentId = field(compare=False)
    sender: AgentId = field(compare=False)
    payload: bytes = field(compare=False)


class _TraceWriter:
    def __init__(self, path: str | Path) -> None:
        # A streaming writer holds the handle open for the run and closes it in
        # close(); a context manager would defeat that lifecycle.
        self._file = Path(path).open("w")  # noqa: SIM115

    def record(self, event: dict[str, Any]) -> None:
        self._file.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def close(self) -> None:
        self._file.close()


class _Ctx:
    """The concrete :class:`AgentContext` bound to one agent for one delivery."""

    def __init__(self, sim: Simulator, agent_id: AgentId) -> None:
        self._sim = sim
        self._agent_id = agent_id

    @property
    def agent_id(self) -> AgentId:
        return self._agent_id

    @property
    def time(self) -> float:
        return self._sim.now

    @property
    def rng(self) -> random.Random:
        return self._sim.rng

    async def send(self, to: AgentId, payload: bytes) -> None:
        self._sim.record_send(self._agent_id, to, payload)
        self._sim.enqueue(self._sim.now, "deliver", to, self._agent_id, payload)

    async def schedule(self, delay: float, payload: bytes) -> None:
        self._sim.enqueue(self._sim.now + delay, "deliver", self._agent_id, self._agent_id, payload)


class Simulator:
    """A seeded discrete-event loop with a JSONL trace. Deterministic by design.

    Example::

        sim = Simulator(seed=42, trace_path="t.jsonl")
        sim.add_agent(AgentId("a"), agent)
        await sim.run(max_events=10000)
    """

    def __init__(self, seed: int = 0, trace_path: str | Path | None = None) -> None:
        self._agents: dict[AgentId, StateMachineAgent] = {}
        self._queue: list[_Event] = []
        self._seq = 0
        self._now = 0.0
        self._rng = random.Random(seed)
        self._trace = _TraceWriter(trace_path) if trace_path is not None else None

    @property
    def now(self) -> float:
        """Current virtual time."""
        return self._now

    @property
    def rng(self) -> random.Random:
        """The seeded RNG."""
        return self._rng

    def add_agent(self, agent_id: AgentId, agent: StateMachineAgent) -> None:
        """Register an agent under an id (insertion order is stable)."""
        self._agents[agent_id] = agent

    def enqueue(
        self, time: float, kind: str, target: AgentId, sender: AgentId, payload: bytes
    ) -> None:
        """Schedule an event; deterministic tiebreak by insertion sequence."""
        import heapq

        self._seq += 1
        heapq.heappush(self._queue, _Event(time, self._seq, kind, target, sender, payload))

    def record_send(self, agent: AgentId, to: AgentId, payload: bytes) -> None:
        """Record a send event on the trace (what the detectors read)."""
        if self._trace is not None:
            self._trace.record(
                {
                    "ts": self._now,
                    "agent": str(agent),
                    "kind": "send",
                    "to": str(to),
                    "msg": payload.decode("utf-8", errors="replace"),
                }
            )

    async def run(self, max_events: int = 100_000) -> None:
        """Start every agent, drain the event queue in order, then stop them.

        Example::

            await sim.run()
        """
        import heapq

        for aid, agent in self._agents.items():
            await agent.on_start(_Ctx(self, aid))

        processed = 0
        while self._queue and processed < max_events:
            event = heapq.heappop(self._queue)
            processed += 1
            self._now = event.time
            target = self._agents.get(event.target)
            if target is None:
                continue
            if self._trace is not None:
                self._trace.record(
                    {
                        "ts": self._now,
                        "agent": str(event.target),
                        "kind": "receive",
                        "from": str(event.sender),
                        "msg": event.payload.decode("utf-8", errors="replace"),
                    }
                )
            await target.on_message(_Ctx(self, event.target), event.sender, event.payload)

        for aid, agent in self._agents.items():
            await agent.on_stop(_Ctx(self, aid))
        if self._trace is not None:
            self._trace.close()
