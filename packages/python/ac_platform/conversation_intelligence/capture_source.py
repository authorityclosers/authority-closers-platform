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

# Recordings someone picked and sent themselves (Reports V4, Dipak's spec, 13 Nov 2026:
# "Manually Uploaded: recordings that a user selects and uploads themselves"): a file
# chosen on the web, or shared into the app. A call stored with no capture source was
# chosen on the web too (the phone sends one with every recording it uploads itself).
MANUAL_CAPTURE_SOURCES = frozenset({"web_upload", "android_share", "ios_share"})


def upload_kind(capture_source: str | None) -> str:
    """How the call's recording reached Sales X-Ray: "manual" when someone chose the file,
    else "auto" (the phone or desktop app captured and uploaded it on its own)."""
    if capture_source is None or capture_source in MANUAL_CAPTURE_SOURCES:
        return "manual"
    return "auto"


def capture_source_header(values: list[str]) -> str | None:
    """The upload's X-Capture-Source: none, or exactly one known source."""
    if not values:
        return None
    if len(values) != 1 or values[0] not in CAPTURE_SOURCES:
        raise ConversationError("Send one known capture source.")
    return values[0]
