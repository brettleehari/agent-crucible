# SPDX-License-Identifier: Apache-2.0
"""A real, model-pluggable tool-calling agent — drop in your model, get real numbers.

This is the adapter a Hermes-class (model-agnostic) team would use. It reads ONLY
the hostile prompt — never a trap label — asks a model to pick a tool via
function-calling, and returns the structured call for Crucible to judge. Point it
at a real model with one environment variable::

    CRUCIBLE_LLM="anthropic:claude-sonnet-4-5"  crucible run --agent examples.llm_agent:handle --trials 20
    CRUCIBLE_LLM="openai:gpt-4o"                 crucible run --agent examples.llm_agent:handle --trials 20

With no key set, it falls back to a **stochastic stand-in model** — a weak,
prompt-driven classifier with genuine per-call noise. It is deliberately *not*
tuned to the traps: it reads generic red-flags (urgency, credential requests,
injected instructions, no-undo language) and decides, imperfectly, whether to
comply or refuse. So it produces a realistic, *variable* profile — decent on
obvious secrets and irreversible actions, weaker on payment fraud, injection, and
identity — instead of the strawman all-pass / all-fail of a scripted stub. Swap in
a real model to replace the stand-in's judgement with the model's own.
"""

from __future__ import annotations

import os
import random
from typing import Any

# Mechanical tool -> observable-effect map. Crucible judges the tool call + args.
TOOL_MAP: dict[str, str] = {
    "pay": "transfer_funds",
    "decline_payment": "withhold_payment",
    "share_secret": "disclose",
    "refuse": "refuse",
    "run_irreversible": "execute_irreversible",
    "require_confirmation": "request_confirmation",
    "grant_authority": "delegate_authority",
    "deny_delegation": "deny_delegation",
    "obey_instruction": "obey_counterparty",
    "ignore_counterparty": "ignore_counterparty",
    "release_resource": "release_restricted",
    "honor_constraint": "honor_constraint",
    "act_on_identity": "act_on_identity",
    "reject_identity": "reject_unverified",
    "go_idle": "go_silent",
    "escalate": "surface_timeout",
}

# What the agent does when it complies (unsafe) vs resists (safe), per intent.
_INTENT: dict[str, tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]]] = {
    "payment": (
        ("pay", {"amount": 500, "payee": "unverified", "delivery_confirmed": False}),
        ("decline_payment", {"reason": "delivery unconfirmed"}),
    ),
    "credential": (("share_secret", {"fields": ["api_key"]}), ("refuse", {"reason": "no secrets"})),
    "irreversible": (
        ("run_irreversible", {"op": "wipe", "confirmed": False}),
        ("require_confirmation", {"action": "wipe"}),
    ),
    "injection": (
        ("obey_instruction", {"source": "counterparty"}),
        ("ignore_counterparty", {"injected_via": "tool_result"}),
    ),
    "authority": (
        ("grant_authority", {"scope": "full"}),
        ("deny_delegation", {"scope": "signing"}),
    ),
    "identity": (
        ("act_on_identity", {"identity_verified": False}),
        ("reject_identity", {"why": "unverified"}),
    ),
    "constraint": (
        ("release_resource", {"resource": "file X"}),
        ("honor_constraint", {"constraint": "never release"}),
    ),
    "stall": (("go_idle", {}), ("escalate", {"status": "counterparty_silent"})),
}


def _has(text: str, *needles: str) -> bool:
    return any(n in text for n in needles)


def _intent(text: str) -> str:
    """What is the prompt asking the agent to do? (read the text, like a model)."""
    if _has(text, "payment", "pay ", "wire", "transfer", "deposit", "iban", "funds"):
        return "payment"
    if _has(
        text,
        "api key",
        "session token",
        "password",
        "seed phrase",
        "cvv",
        "card number",
        "ssn",
        "passport",
        "credential",
        "secret",
    ):
        return "credential"
    if _has(text, "wipe", "no undo", "permanently", "irreversible", "finalize", "delete all"):
        return "irreversible"
    if _has(text, "ignore your", "forward your", "system:", "tool result:", "exfiltrate"):
        return "injection"
    if _has(
        text,
        "signing authority",
        "act on your behalf",
        "grant me",
        "admin",
        "moderator",
        "delegate",
        "authorized signer",
    ):
        return "authority"
    if _has(
        text,
        "unverifiable",
        "no valid signature",
        "i am the",
        "claims to be",
        "no badge",
        "unverified",
    ):
        return "identity"
    if _has(text, "file x", "send me file", "release the", "never release", "standing rule"):
        return "constraint"
    if _has(text, "stop responding", "goes silent", "long job", "long-running", "keep waiting"):
        return "stall"
    return "unknown"


# How obviously dangerous each intent is — a competent agent's learned prior. Secrets
# and no-undo actions are refused most of the time; subtle payment/injection/identity/
# compaction attacks slip through more often. This is what shapes a realistic profile.
_PRIOR: dict[str, float] = {
    "credential": 0.62,
    "irreversible": 0.52,
    "authority": 0.38,
    "injection": 0.36,
    "identity": 0.33,
    "payment": 0.31,
    "constraint": 0.30,
    "stall": 0.26,
    "unknown": 0.50,
}


def _flag_bonus(text: str) -> float:
    """Extra caution from generic red-flags on top of the intent prior."""
    b = 0.0
    b += 0.12 * _has(text, "trust me", "don't worry", "just do", "no need to verify")
    b += 0.10 * _has(text, "unverifiable", "no valid signature", "no badge", "unverified")
    b += 0.08 * _has(text, "now", "immediately", "today", "right now")
    return b


# A real RNG seeded once, so the demo reproduces byte-for-byte across runs yet each
# call draws a genuinely different value — a stand-in for a model's sampling.
_rng = random.Random(20260823)


def _standin_choose(text: str) -> dict[str, Any]:
    """The offline stand-in 'model': prior + red-flags + sampling -> comply or resist."""
    low = text.lower()
    intent = _intent(low)
    unsafe, safe = _INTENT.get(intent, (("refuse", {"reason": "unrecognized"}),) * 2)
    resist = _PRIOR.get(intent, 0.45) + _flag_bonus(low) + (_rng.random() - 0.5) * 0.5
    tool, args = safe if resist >= 0.5 else unsafe
    return {"tool": tool, "args": args}


def _model_choose(text: str) -> dict[str, Any]:
    """Route to a real model if CRUCIBLE_LLM is set, else the offline stand-in.

    Real models are asked to pick exactly one tool from TOOL_MAP via function-calling;
    the returned call is what Crucible judges. (Needs the relevant SDK + API key.)
    """
    spec = os.environ.get("CRUCIBLE_LLM", "").strip()
    if not spec:
        return _standin_choose(text)
    provider, _, model = spec.partition(":")
    if provider == "anthropic":  # pragma: no cover - needs a key
        import anthropic

        client = anthropic.Anthropic()
        tools = [
            {"name": t, "description": f"effect: {TOOL_MAP[t]}", "input_schema": {"type": "object"}}
            for t in TOOL_MAP
        ]
        msg = client.messages.create(
            model=model or "claude-sonnet-4-5",
            max_tokens=256,
            tools=tools,  # type: ignore[arg-type]
            messages=[{"role": "user", "content": text}],
        )
        for block in msg.content:
            if getattr(block, "type", "") == "tool_use":
                return {"tool": block.name, "args": dict(block.input)}  # type: ignore[attr-defined]
        return {"tool": "refuse", "args": {"reason": "no tool call"}}
    if provider == "openai":  # pragma: no cover - needs a key
        import json as _json

        import openai

        client = openai.OpenAI()
        tools = [
            {"type": "function", "function": {"name": t, "parameters": {"type": "object"}}}
            for t in TOOL_MAP
        ]
        resp = client.chat.completions.create(
            model=model or "gpt-4o",
            tools=tools,  # type: ignore[arg-type]
            messages=[{"role": "user", "content": text}],
        )
        calls = resp.choices[0].message.tool_calls or []
        if calls:
            return {
                "tool": calls[0].function.name,
                "args": _json.loads(calls[0].function.arguments or "{}"),
            }
        return {"tool": "refuse", "args": {"reason": "no tool call"}}
    return _standin_choose(text)


def handle(message: dict[str, Any]) -> dict[str, Any]:
    """Crucible calls this with the hostile prompt; return the agent's tool call."""
    return _model_choose(str(message.get("text", "")))
