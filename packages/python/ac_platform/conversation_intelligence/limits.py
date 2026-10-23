"""Shared limits for the hosted audio processing route: a recording's size and its length."""

MAX_AUDIO_BYTES = 100_000_000

# The longest call Sales X-Ray analyses, everywhere: the upload policy, every plan's and
# the trial's per-call cap, and the message for a call over it: 120 minutes (owner, 23 Oct
# 2026: "Call length limit: 120 minutes everywhere"). It never passes what the analysis
# pipeline handles (signals.MAX_SECONDS, the hosted AudioAtlas profile: two hours since
# c1f6da4c). The web's twin is apps/sales-xray-web/app/call-limit.ts.
CALL_LIMIT_SECONDS = 120 * 60
