"""Shared limits for the hosted audio processing route: a recording's size and its length."""

MAX_AUDIO_BYTES = 100_000_000

# The longest call Sales X-Ray analyses, everywhere: the upload policy, every plan's and
# the trial's per-call cap, and the message for a call over it. The owner's target is 120
# minutes ("Call length limit: 120 minutes everywhere", 23 Oct 2026); the analysis
# pipeline handles one hour today (signals.MAX_SECONDS, the hosted AudioAtlas profile), so
# this is 60 until that work lands, and then changes here, once. The web's twin is
# apps/sales-xray-web/app/call-limit.ts.
CALL_LIMIT_SECONDS = 60 * 60

# The trial every person gets: three hours of calls (owner, 13 Nov 2026, in the meeting
# with Dipak: "Not unlimited... Give it with basic rules: three hours. It's 60 minutes
# now, I guess; make it x3"). The trial policy's v1 and the shared upload allowance read
# it, so it changes here, once. Never shown with a price.
TRIAL_SECONDS = 3 * 60 * 60
