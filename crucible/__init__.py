# SPDX-License-Identifier: Apache-2.0
"""Crucible — an adversarial fitness gate for autonomous agents.

Clone, point it at your agent, and one command tells you whether it survives a
floor of deterministic villains: pass / fail per tripwire with a replayable
trace, on a laptop, for free.

Example::

    from crucible.tripwires import TRIPWIRES, evaluate_tripwires
"""

from crucible.tripwires import (
    TRIPWIRES,
    TripwireResult,
    TripwireStatus,
    evaluate_tripwires,
)

__all__ = ["TRIPWIRES", "TripwireResult", "TripwireStatus", "evaluate_tripwires"]
