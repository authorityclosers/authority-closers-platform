from uuid import uuid4

import pytest

from ac_platform.kernel.events import EventCategory, EventEnvelope


def test_audit_event_requires_tenant_boundary() -> None:
    with pytest.raises(ValueError, match="tenant boundary"):
        EventEnvelope(
            name="audit.learning.corrected.v1",
            category=EventCategory.AUDIT,
            aggregate_type="learning_evidence",
            aggregate_id=uuid4(),
            tenant_id=None,
            payload={},
        )
