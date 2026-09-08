# SPDX-License-Identifier: Apache-2.0
"""The minimal adapter: bridge the gauntlet to an agent under test.

The contract is one method -- :meth:`A2AClient.send` -- and it returns what the
agent OBSERVABLY did, an :class:`~crucible.tripwires.Effect` (the tool it invoked
and its args, or a structured effect), never a safe/unsafe verdict word. The
verdict is Crucible's to make, from that behavior; the adapter only reports it.
This is the line the whole product turns on: the machine judges the agent, the
agent never judges itself.

Four clients implement the seam:

* :class:`FixtureA2AClient` -- a deterministic stand-in with two profiles,
  ``naive`` (performs the trap's unsafe effect) and ``hardened`` (performs the
  safe effect). The differential control: the same trap floor that springs
  against ``naive`` must hold against ``hardened``.
* :class:`CallableClient` -- an in-process function ``(message) -> effect``. The
  message is only ``{text, trap, step}`` -- the agent is never told which effect
  is safe. A returned tool call is mapped to an effect through a mechanical
  ``tool_map``; the SPRUNG/HELD decision still lives in the trap.
* :class:`HttpA2AClient` / :class:`McpClient` -- speak JSON-RPC to a live A2A or
  MCP endpoint (stdlib only). Backed by a record/replay :class:`~crucible.
  cassette.Cassette`, they capture the endpoint's *structured* response once,
  classify it with the same predicates, and replay byte-identically. A genuinely
  free-prose response stays NOT_ARMED -- never a fabricated green.

Example::

    client = FixtureA2AClient(profile="hardened")
    effect = client.send(A2AMessage("s1", "user", "release payment now", {"trap": "money_leak"}))
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from crucible.tripwires import Effect, get_tripwire

_StrMap = dict[str, str]
_AnyMap = dict[str, Any]


@dataclass
class A2AMessage:
    """A minimal A2A user message: text parts plus out-of-band trap metadata.

    ``text`` is what a real agent sees. ``meta`` carries the ``trap``/``step``
    labels the fixture uses to decide; a live endpoint never sees ``meta`` and
    the agent is never told which effect would be safe.

    Example::

        A2AMessage("s1", "user", "please pay 500 now", {"trap": "money_leak"})
    """

    session_id: str
    role: str
    text: str
    meta: dict[str, str] = field(default_factory=_StrMap)


@runtime_checkable
class A2AClient(Protocol):
    """The one-method seam every agent under test is reached through.

    ``send`` returns the observable :class:`~crucible.tripwires.Effect` the agent
    produced -- Crucible classifies it, the client never does.

    Example::

        def send(self, message: A2AMessage) -> Effect: ...
    """

    def send(self, message: A2AMessage) -> Effect:
        """Send one message to the AUT and return its observable effect.

        Example::

            effect = client.send(msg)
        """
        ...


# Representative args baked onto the fixture's effects purely so the plain-language
# trace reads concretely (an amount, the secret fields). Predicates already spring
# the naive effect on its name; these only make the record legible.
_FIXTURE_ARGS: dict[str, dict[str, Any]] = {
    "transfer_funds": {"amount": 500, "payee": "account X", "delivery_confirmed": False},
    "disclose": {"fields": ["api_key", "session_token"]},
    "execute_irreversible": {"op": "wipe_account", "confirmed": False},
    "act_on_identity": {"identity_verified": False},
    "delegate_authority": {"scope": "signing"},
    "release_restricted": {"resource": "file X"},
}


class FixtureA2AClient:
    """Deterministic stand-in AUT with ``naive`` and ``hardened`` profiles.

    The effect is a pure function of ``(trap, profile)`` read from the frozen
    tripwire table, so there is no clock and no RNG -- identical inputs give an
    identical trace. The trap floor springs against ``naive`` and holds against
    ``hardened``, with no live endpoint.

    Example::

        client = FixtureA2AClient(profile="naive")
    """

    def __init__(self, profile: str = "naive") -> None:
        if profile not in ("naive", "hardened"):
            msg = f"profile must be 'naive' or 'hardened', got {profile!r}"
            raise ValueError(msg)
        self._profile = profile

    @property
    def profile(self) -> str:
        """The configured profile.

        Example::

            assert client.profile == "naive"
        """
        return self._profile

    def send(self, message: A2AMessage) -> Effect:
        """Perform the trap's unsafe (naive) or safe (hardened) observable effect.

        A message with no ``trap`` label (setup narration) returns a neutral,
        unclassifiable effect that no tripwire treats as decisive.

        Example::

            effect = client.send(A2AMessage("s1", "user", "...", {"trap": "money_leak"}))
        """
        trap_id = message.meta.get("trap")
        if not trap_id:
            return Effect("", text=message.text)
        tw = get_tripwire(trap_id)
        name = tw.naive_effect if self._profile == "naive" else tw.hardened_effect
        args = dict(_FIXTURE_ARGS.get(name, {})) if self._profile == "naive" else {}
        # The stand-in emits a bare effect name (no real tool call), so its holds
        # carry self_named provenance -- honest about being a demo, not a wired tool.
        return Effect(
            name, args=args, text=f"[fixture:{self._profile}] {name}", provenance="self_named"
        )


# The contract for a user's in-process adapter. It receives a friendly dict and
# returns the observable effect its agent produced.
CallableTarget = Callable[[dict[str, Any]], "str | dict[str, Any] | None"]


def resolve_callable(target: str) -> CallableTarget:
    """Resolve a ``module.path:function`` string to the callable it names.

    Example::

        fn = resolve_callable("myagent.entry:handle")
    """
    import importlib
    import sys

    if ":" not in target:
        msg = f"callable target must be 'module.path:function', got {target!r}"
        raise ValueError(msg)
    if "" not in sys.path:
        sys.path.insert(0, "")
    module_name, _, attr = target.partition(":")
    module = importlib.import_module(module_name)
    fn = getattr(module, attr, None)
    if not callable(fn):
        msg = f"{target!r} does not resolve to a callable"
        raise TypeError(msg)
    return cast("CallableTarget", fn)


def _args_of(obj: dict[str, Any]) -> dict[str, Any]:
    args = obj.get("args")
    return cast("dict[str, Any]", args) if isinstance(args, dict) else {}


def effect_from_structured(obj: dict[str, Any], tool_map: dict[str, str]) -> Effect | None:
    """Normalize a structured agent response into an :class:`Effect`, or None.

    Accepts, in order: an explicit structured effect ``{"effect": name, "args":
    {...}}``; a tool call ``{"tool": name, "args": {...}}`` mapped through the
    mechanical ``tool_map`` (an *unmapped* tool becomes an unclassifiable effect
    that keeps the tool name for the trace -- never a guessed verdict). Returns
    None when there is no structured effect or tool call at all.

    Example::

        effect_from_structured({"tool": "wire", "args": {"amount": 5}}, {"wire": "transfer_funds"})
    """
    effect_name = obj.get("effect")
    if isinstance(effect_name, str) and effect_name:
        # A bare effect name: the agent named its own effect. Recorded as
        # self_named so a hold derived from it can never be trusted as a tool call.
        return Effect(
            effect_name, _args_of(obj), tool=str(obj.get("tool", "")), provenance="self_named"
        )
    tool = obj.get("tool")
    if isinstance(tool, str) and tool:
        mapped = tool_map.get(tool)
        if mapped:
            # A real tool call, mechanically mapped to an effect Crucible judges.
            return Effect(mapped, _args_of(obj), tool=tool, provenance="mapped_tool")
        # Unmapped tool: observable, but Crucible will not guess a verdict for it.
        return Effect("", _args_of(obj), tool=tool, text=f"unmapped tool {tool!r}")
    return None


def _effect_from_result(result: object, tool_map: dict[str, str]) -> Effect:
    """Normalize a callable's return value into an :class:`Effect`.

    A bare string or ``{"text": ...}`` is free prose (unclassifiable, NOT_ARMED);
    a structured effect / tool call is classified by Crucible; anything else /
    ``None`` is an empty, unclassifiable effect.
    """
    if isinstance(result, str):
        return Effect("", text=result)
    if isinstance(result, dict):
        obj = cast("dict[str, Any]", result)
        structured = effect_from_structured(obj, tool_map)
        if structured is not None:
            return structured
        text = obj.get("text")
        return Effect("", text=str(text) if isinstance(text, str) else "")
    return Effect("")


class CallableClient:
    """Reach an agent in-process through a Python callable -- no server, no network.

    The lowest-friction way to put an agent in CI: point Crucible at a function
    ``(message) -> effect``. The callable receives only ``{text, trap, step}`` --
    it is never told which effect is safe -- and returns what its agent DID: a
    tool call ``{"tool": ..., "args": {...}}`` (mapped via ``tool_map``), a
    structured effect ``{"effect": ..., "args": {...}}``, or free prose (which is
    honestly NOT_ARMED). Crucible makes the verdict.

    Example::

        client = CallableClient(resolve_callable("myagent:handle"), {"wire": "transfer_funds"})
    """

    def __init__(self, target: CallableTarget, tool_map: dict[str, str] | None = None) -> None:
        self._target = target
        self._tool_map = tool_map or {}

    def send(self, message: A2AMessage) -> Effect:
        """Call the target with the probe and normalize its answer to an effect.

        Example::

            effect = client.send(msg)
        """
        payload: dict[str, Any] = {
            "text": message.text,
            "trap": message.meta.get("trap", ""),
            "step": message.meta.get("step", ""),
        }
        return _effect_from_result(self._target(payload), self._tool_map)


def build_message_send_request(message: A2AMessage, request_id: str) -> dict[str, Any]:
    """Build the JSON-RPC ``message/send`` request body for a live A2A call.

    Deterministic: the ``messageId`` is derived from the session id and step,
    never from a clock or RNG, so replayed live runs stay stable.

    Example::

        body = build_message_send_request(msg, "1")
        assert body["method"] == "message/send"
    """
    step = message.meta.get("step", "0")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": message.role,
                "parts": [{"kind": "text", "text": message.text}],
                "messageId": f"{message.session_id}-{step}",
            }
        },
    }


def _structured_from_parts(parts: object, tool_map: dict[str, str]) -> Effect | None:
    """Scan a list of A2A/MCP parts for a structured effect or tool call."""
    if not isinstance(parts, list):
        return None
    for part in cast("list[Any]", parts):
        if not isinstance(part, dict):
            continue
        pobj = cast("dict[str, Any]", part)
        data = pobj.get("data")
        if isinstance(data, dict):
            got = effect_from_structured(cast("dict[str, Any]", data), tool_map)
            if got is not None:
                return got
        text = pobj.get("text")
        if isinstance(text, str) and text.strip().startswith("{"):
            try:
                inner = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(inner, dict):
                got = effect_from_structured(cast("dict[str, Any]", inner), tool_map)
                if got is not None:
                    return got
    return None


def classify_a2a_response(raw: str, tool_map: dict[str, str]) -> Effect:
    """Turn a captured A2A ``message/send`` response into an observable effect.

    Looks for a structured effect / tool call inside the result artifacts. If one
    is present, Crucible classifies it exactly like the in-process path. If the
    reply is only free prose, the effect is unclassifiable (NOT_ARMED) with the
    prose kept on ``text`` for the plain-language trace -- never a fabricated
    verdict.

    Example::

        effect = classify_a2a_response(raw_json, {"wire": "transfer_funds"})
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return Effect("", text="")
    if not isinstance(parsed, dict):
        return Effect("", text="")
    result = cast("dict[str, Any]", parsed).get("result")
    prose_chunks: list[str] = []
    if isinstance(result, dict):
        artifacts = cast("dict[str, Any]", result).get("artifacts")
        if isinstance(artifacts, list):
            for artifact in cast("list[Any]", artifacts):
                if not isinstance(artifact, dict):
                    continue
                parts = cast("dict[str, Any]", artifact).get("parts")
                got = _structured_from_parts(parts, tool_map)
                if got is not None:
                    return got
                if isinstance(parts, list):
                    for part in cast("list[Any]", parts):
                        if isinstance(part, dict):
                            t = cast("dict[str, Any]", part).get("text")
                            if isinstance(t, str):
                                prose_chunks.append(t)
    return Effect("", text="".join(prose_chunks))


def build_tools_call_request(message: A2AMessage, request_id: str) -> dict[str, Any]:
    """Build the JSON-RPC ``tools/call`` request body for a live MCP call.

    Deterministic (no clock/RNG): a single ``respond`` tool carrying the probe
    text.

    Example::

        body = build_tools_call_request(msg, "1")
        assert body["method"] == "tools/call"
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "respond", "arguments": {"text": message.text}},
    }


def classify_mcp_response(raw: str, tool_map: dict[str, str]) -> Effect:
    """Turn a captured MCP ``tools/call`` response into an observable effect.

    Reads ``result.structuredContent`` and ``result.content`` for a structured
    effect / tool call, classifying it with the same predicates. A prose-only
    result stays unclassifiable (NOT_ARMED) with the prose kept for the trace.

    Example::

        effect = classify_mcp_response(raw_json, {"wire": "transfer_funds"})
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return Effect("", text="")
    if not isinstance(parsed, dict):
        return Effect("", text="")
    result = cast("dict[str, Any]", parsed).get("result")
    if not isinstance(result, dict):
        return Effect("", text="")
    robj = cast("dict[str, Any]", result)
    structured = robj.get("structuredContent")
    if isinstance(structured, dict):
        got = effect_from_structured(cast("dict[str, Any]", structured), tool_map)
        if got is not None:
            return got
    content = robj.get("content")
    got = _structured_from_parts(content, tool_map)
    if got is not None:
        return got
    prose: list[str] = []
    if isinstance(content, list):
        for part in cast("list[Any]", content):
            if isinstance(part, dict):
                t = cast("dict[str, Any]", part).get("text")
                if isinstance(t, str):
                    prose.append(t)
    return Effect("", text="".join(prose))


class _LiveClient:
    """Shared record/replay body for the live A2A and MCP clients."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout: float,
        cassette: Any | None,
        tool_map: dict[str, str] | None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._cassette = cassette
        self._tool_map = tool_map or {}
        self._counter = 0

    def _fetch(self, body: dict[str, Any]) -> str:
        """Return the raw response: replayed from cassette when present, else live once."""
        if self._cassette is not None:
            key = self._cassette.key(body)
            hit = self._cassette.get(key)
            if hit is not None:
                return hit
            if self._cassette.mode == "replay":
                return self._cassette.require(key)  # raises: honest miss, no fabrication
        raw = self._http_post(body)
        if self._cassette is not None:
            self._cassette.put(self._cassette.key(body), raw)
            self._cassette.save()
        return raw

    def _http_post(self, body: dict[str, Any]) -> str:
        import urllib.request

        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")


class HttpA2AClient(_LiveClient):
    """Speak JSON-RPC ``message/send`` to a live A2A endpoint (stdlib only).

    Backed by a record/replay cassette: the endpoint is called once, its response
    recorded, and every later run replays it byte-identically. The captured
    *structured* response is classified into a real SPRUNG/HELD verdict via
    :func:`classify_a2a_response`; a free-prose reply stays NOT_ARMED.

    Example::

        client = HttpA2AClient("https://agent.example/a2a", cassette=cas, tool_map=tm)
    """

    def __init__(
        self,
        endpoint: str,
        timeout: float = 30.0,
        cassette: Any | None = None,
        tool_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__(endpoint, timeout=timeout, cassette=cassette, tool_map=tool_map)

    def send(self, message: A2AMessage) -> Effect:
        """POST (or replay) one ``message/send`` and classify the response.

        Example::

            effect = client.send(msg)
        """
        self._counter += 1
        body = build_message_send_request(message, str(self._counter))
        raw = self._fetch(body)
        return classify_a2a_response(raw, self._tool_map)


class McpClient(_LiveClient):
    """Speak JSON-RPC ``tools/call`` to a live MCP endpoint (stdlib only).

    Cassette-backed exactly like :class:`HttpA2AClient`; the captured structured
    result is classified via :func:`classify_mcp_response`, a prose-only result
    stays NOT_ARMED. The gauntlet gives a real, deterministic verdict on both
    protocols it speaks.

    Example::

        client = McpClient("https://server.example/mcp", cassette=cas, tool_map=tm)
    """

    def __init__(
        self,
        endpoint: str,
        timeout: float = 30.0,
        cassette: Any | None = None,
        tool_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__(endpoint, timeout=timeout, cassette=cassette, tool_map=tool_map)

    def send(self, message: A2AMessage) -> Effect:
        """POST (or replay) one ``tools/call`` and classify the response.

        Example::

            effect = client.send(msg)
        """
        self._counter += 1
        body = build_tools_call_request(message, str(self._counter))
        raw = self._fetch(body)
        return classify_mcp_response(raw, self._tool_map)
