from uuid import uuid4

import pytest

from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import AuthorizationDenied


def test_actor_context_requires_self_tenant_and_permission() -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=person_id,
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"catalog_publish"}),
    )

    actor.require_self(person_id)
    actor.require_tenant(tenant_id)
    actor.require_permission("catalog_publish")

    with pytest.raises(AuthorizationDenied):
        actor.require_self(uuid4())
    with pytest.raises(AuthorizationDenied):
        actor.require_tenant(uuid4())
    with pytest.raises(AuthorizationDenied):
        actor.require_permission("learning_correct")
