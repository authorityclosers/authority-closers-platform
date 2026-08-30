"""Learning evidence and server-authoritative progress primitives.

The learning module deliberately keeps its domain services independent from
FastAPI and SQLAlchemy.  The ORM models describe the durable boundary while
the services operate on immutable snapshots and explicit ports.
"""

from ac_platform.learning.models import (
    ActivityDraft,
    ActivityProgress,
    ActivityState,
    EvidenceCorrection,
    EvidenceSubmission,
    LearningEvidence,
    LearningProgressProjection,
    PlaybackSession,
    VideoWatchInterval,
)

__all__ = [
    "ActivityDraft",
    "ActivityProgress",
    "ActivityState",
    "EvidenceCorrection",
    "EvidenceSubmission",
    "LearningEvidence",
    "LearningProgressProjection",
    "PlaybackSession",
    "VideoWatchInterval",
]
