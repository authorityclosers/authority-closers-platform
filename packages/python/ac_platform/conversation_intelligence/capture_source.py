"""How a call's recording was captured (ADR 0056 F2, 19 Oct 2026).

The Android app says so when it uploads the source (X-Capture-Source): it picked
up the dialer's own file, recorded a conversation itself, or recorded a call
with its optional call recorder. The value is written when the call's row is
created; conversation_guest_submissions is append-only, so it never changes
afterwards. The call data engine compares transcript quality by it, never by
file name (ADR 0056 section 4).
"""

from __future__ import annotations

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.guest_models import CAPTURE_SOURCES


def capture_source_header(values: list[str]) -> str | None:
    """The upload's X-Capture-Source: none, or exactly one known source."""
    if not values:
        return None
    if len(values) != 1 or values[0] not in CAPTURE_SOURCES:
        raise ConversationError("Send one known capture source.")
    return values[0]
