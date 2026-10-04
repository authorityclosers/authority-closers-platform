"""Runtime gate for candidate coaching revisions awaiting validation."""

from __future__ import annotations

COACHING_V6_RUNTIME_BLOCK_MESSAGE = (
    "Coaching v6 is an unvalidated candidate. Runtime use is blocked until "
    "AC-SVAL-01 Gate 2 (AI feedback) evidence and approval are recorded. "
    "Select coaching-v5 or another available revision."
)
COACHING_V7_RUNTIME_BLOCK_MESSAGE = COACHING_V6_RUNTIME_BLOCK_MESSAGE.replace("v6", "v7")


def coaching_revision_runtime_block(revision: str) -> str | None:
    """Return the fail-closed runtime block for a candidate revision, if any.

    Offline prompt/schema/adapter work deliberately does not call this helper.
    A future runtime approval requires a reviewed code change and evidence;
    there is no environment or database switch that activates candidate rules.
    """

    if revision == "coaching-v6":
        return COACHING_V6_RUNTIME_BLOCK_MESSAGE
    if revision == "coaching-v7":
        return COACHING_V7_RUNTIME_BLOCK_MESSAGE
    return None


__all__ = [
    "COACHING_V6_RUNTIME_BLOCK_MESSAGE",
    "COACHING_V7_RUNTIME_BLOCK_MESSAGE",
    "coaching_revision_runtime_block",
]
