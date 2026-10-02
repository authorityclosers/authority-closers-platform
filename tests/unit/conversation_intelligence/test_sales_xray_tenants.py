"""Enablement is composed policy data, with operations always excluded."""

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.sales_xray_tenants import sales_xray_tenant_ids


def test_composed_policy_plus_public_minus_operations():
    public, organisation, operations = (uuid4() for _ in range(3))
    settings = Settings(
        _env_file=None,
        environment="test",
        public_learner_tenant_id=public,
        operations_tenant_id=operations,
    )
    policy = IntakePolicy(
        budget_scope_id=uuid4(),
        tenant_ids=frozenset({organisation, operations}),
        authorization_ref="ref:fictional/intake",
        retention_ref="ref:fictional/retention",
    )
    intake = cast(Any, SimpleNamespace(policy=policy))
    assert sales_xray_tenant_ids(settings, intake) == frozenset({public, organisation})
    assert policy.tenant_ids == frozenset({organisation, operations})
    assert sales_xray_tenant_ids(settings, None) == frozenset()
    settings = settings.model_copy(update={"public_learner_tenant_id": None})
    assert sales_xray_tenant_ids(settings, intake) == frozenset({organisation})
