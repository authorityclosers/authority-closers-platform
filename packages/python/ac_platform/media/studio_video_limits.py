"""Source-owned bounds for the authenticated Studio video pipeline.

The source limit is deliberately decimal because it is the value exposed by
the Coach capability and enforced by the byte transport.  Storage capacity
remains binary and includes room for the bounded private object inventory.
"""

STUDIO_VIDEO_MAX_SOURCE_BYTES = 2_000_000_000
STUDIO_VIDEO_MAX_STORE_BYTES = 8 * 1024**3
STUDIO_VIDEO_MAX_SCAN_BYTES = 4_000_000_000
STUDIO_VIDEO_SCAN_TIMEOUT_SECONDS = 1_800.0

__all__ = [
    "STUDIO_VIDEO_MAX_SCAN_BYTES",
    "STUDIO_VIDEO_MAX_SOURCE_BYTES",
    "STUDIO_VIDEO_MAX_STORE_BYTES",
    "STUDIO_VIDEO_SCAN_TIMEOUT_SECONDS",
]
