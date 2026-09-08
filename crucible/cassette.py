# SPDX-License-Identifier: Apache-2.0
"""Record/replay cassettes: give the live A2A/MCP path a deterministic verdict.

A live endpoint is not deterministic and not free, so the gauntlet cannot call
it on every CI run and still promise byte-identical replays. The cassette closes
that gap. On the first run a live response is fetched once and *recorded* into a
seeded, on-disk cassette keyed by the exact request. Every later run *replays*
the stored bytes -- no network, no clock, byte-for-byte identical -- and Crucible
classifies that captured structured response with the very same per-tripwire
predicates the fixture and callable paths use. Commit the cassette and CI has a
real, offline, reproducible verdict for a deployed agent.

The cassette stores raw response text, so replay is exact. The key is derived
from the request body only (never a clock or RNG), so the same probe always maps
to the same recording.

Example::

    cas = Cassette("traces/agent.cassette.json")
    key = cas.key(request_body)
    raw = cas.get(key)            # None on a miss -> caller records
    cas.put(key, live_raw); cas.save()
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast


class Cassette:
    """A seeded record/replay store for live endpoint responses.

    ``mode`` is ``"auto"`` (replay a recorded response, otherwise record a live
    one) or ``"replay"`` (replay only; a miss is an error, for offline CI on a
    committed cassette).

    Example::

        cas = Cassette("agent.cassette.json", mode="auto")
    """

    def __init__(self, path: str, mode: str = "auto") -> None:
        if mode not in ("auto", "replay"):
            msg = f"cassette mode must be 'auto' or 'replay', got {mode!r}"
            raise ValueError(msg)
        self._path = Path(path)
        self._mode = mode
        self._entries: dict[str, str] = {}
        self._dirty = False
        if self._path.is_file():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                entries = cast("dict[str, Any]", raw).get("entries")
                if isinstance(entries, dict):
                    self._entries = {
                        str(k): str(v) for k, v in cast("dict[Any, Any]", entries).items()
                    }

    @property
    def mode(self) -> str:
        """The cassette mode ('auto' or 'replay')."""
        return self._mode

    def key(self, request_body: dict[str, Any]) -> str:
        """Deterministic key for a JSON-RPC request body (no clock, no RNG).

        Example::

            k = cas.key({"method": "message/send", "params": {...}})
        """
        method = str(request_body.get("method", ""))
        params = request_body.get("params", {})
        blob = json.dumps(params, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return f"{method}:{digest}"

    def get(self, key: str) -> str | None:
        """Return the recorded raw response for *key*, or None on a miss.

        Example::

            raw = cas.get(key)
        """
        return self._entries.get(key)

    def put(self, key: str, raw_response: str) -> None:
        """Record a live raw response under *key* (no-op in replay-only mode).

        Example::

            cas.put(key, raw)
        """
        if self._mode == "replay":
            msg = f"cassette in replay-only mode has no recording for {key!r}"
            raise KeyError(msg)
        if self._entries.get(key) != raw_response:
            self._entries[key] = raw_response
            self._dirty = True

    def require(self, key: str) -> str:
        """Return a recording or raise -- used in replay-only mode on a miss."""
        raw = self._entries.get(key)
        if raw is None:
            msg = f"cassette {self._path.name!r} has no recording for {key!r} (replay-only)"
            raise KeyError(msg)
        return raw

    def save(self) -> None:
        """Persist recordings to disk with stable ordering (byte-stable).

        Example::

            cas.save()
        """
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "note": "Crucible record/replay cassette. Commit for offline, deterministic CI.",
            "entries": dict(sorted(self._entries.items())),
        }
        self._path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        self._dirty = False
