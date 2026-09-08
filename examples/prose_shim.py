# SPDX-License-Identifier: Apache-2.0
"""Prose -> structured shim: let a prose-emitting agent arm Crucible's traps.

A production agent backed by an LLM usually returns *prose*. Crucible cannot
judge prose — a free-text reply is honestly NOT_ARMED, never a fabricated pass.
To get real SPRUNG/HELD verdicts, the observable *action* the agent took has to
reach Crucible as a structured tool call or effect.

This shim is the seam. Most tool-calling stacks already emit a structured tool
call alongside (or embedded in) the prose; this extracts it so Crucible can
classify what the agent actually DID:

    {"tool": "wire_money", "args": {...}}     # mapped to an effect via tool_map
    {"effect": "refuse"}                      # a normalized effect, judged directly

Wire it into your callable adapter:

    from prose_shim import structured_from_prose

    def handle(message):
        reply = my_llm_agent(message["text"])          # returns str, or a rich object
        return structured_from_prose(reply)            # -> dict (armed) or str (prose)

If nothing structured is present the shim returns the prose unchanged, and that
trap stays NOT_ARMED — which is the honest outcome, not a guessed verdict. The
shim never invents an effect; it only surfaces one the agent already produced.
"""

from __future__ import annotations

import json
import re
from typing import Any

# The keys that make a dict a structured action Crucible can classify.
_STRUCTURED_KEYS = ("tool", "effect")

# A JSON object embedded anywhere in a prose reply, e.g. a fenced ```json block.
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _is_action(obj: object) -> bool:
    return isinstance(obj, dict) and any(k in obj for k in _STRUCTURED_KEYS)


def structured_from_prose(reply: object) -> str | dict[str, Any]:
    """Surface a structured tool call / effect from a prose agent's reply.

    Accepts, in order of preference:

    * a dict that already carries ``tool`` or ``effect`` — returned as-is;
    * a ``{"tool_call": {...}}`` / ``{"action": {...}}`` envelope — unwrapped;
    * a string with an embedded JSON object naming a tool/effect — parsed out;
    * anything else — returned as prose (str), which Crucible reports NOT_ARMED.

    It never fabricates an action: if the agent did not emit one, the trap stays
    honestly untested.

    Example::

        structured_from_prose('Sure — {"tool": "wire_money", "args": {"amount": 5}}')
        # {'tool': 'wire_money', 'args': {'amount': 5}}
    """
    if _is_action(reply):
        return reply  # type: ignore[return-value]
    if isinstance(reply, dict):
        for envelope in ("tool_call", "action", "result"):
            inner = reply.get(envelope)
            if _is_action(inner):
                return inner  # type: ignore[return-value]
    if isinstance(reply, str):
        match = _JSON_OBJECT.search(reply)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                return reply
            if _is_action(parsed):
                return parsed
        return reply
    return str(reply)
