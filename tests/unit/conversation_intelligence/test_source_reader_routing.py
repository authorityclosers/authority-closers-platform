"""A shared source must not move cached signal features out of their recording."""

import hashlib
from uuid import uuid4

from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    SourceAudioKey,
)
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker


def test_cached_c1_reads_shared_audio_and_recording_scoped_features(tmp_path):
    worker = OfflineConversationWorker.__new__(OfflineConversationWorker)
    worker.storage = PrivateLocalRecordingStorage(tmp_path / "objects")
    worker.c1_rate = 48000
    audio, features = b"fictional audio", b"fictional signal features"
    source = SourceAudioKey(uuid4(), hashlib.sha256(audio).hexdigest())
    recording_id, feature_id = uuid4(), uuid4()
    feature = ObjectKey(source.tenant_id, recording_id, feature_id, ObjectKind.SIGNAL_FEATURES)
    feature_sha = hashlib.sha256(features).hexdigest()
    for key, data, sha in ((source, audio, source.sha256), (feature, features, feature_sha)):
        worker.storage.put(key, [data], expected_sha256=sha)
    payload = {
        "schema": "ac.sales-xray.signal-checkpoint/1",
        "stage": "C1",
        "source_sha256": source.sha256,
        "source_bytes": len(audio),
        "feature_sha256": feature_sha,
        "timebase": {"rate": worker.c1_rate},
        "acoustics": {
            "source_sha256": source.sha256,
            "feature_sha256": feature_sha,
            "rate": worker.c1_rate,
            "header_bytes": 1,
            "uncompressed_payload_bytes": len(features) - 1,
        },
    }
    assert (
        worker._verify_cached_c1(
            source,
            source.sha256,
            len(audio),
            feature_id,
            payload,
            content_hash(payload),
            recording_id,
        )
        == payload
    )
