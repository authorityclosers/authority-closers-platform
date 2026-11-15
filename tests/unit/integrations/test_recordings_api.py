"""An API upload's progress in a few words (integrations/recordings_api.py)."""

from __future__ import annotations

from ac_platform.conversation_intelligence import key_upload
from ac_platform.integrations.recordings_api import plain_state


def test_progress_reads_as_a_few_plain_words() -> None:
    assert plain_state({"has_report": True}, None) == ("report_ready", None)
    assert plain_state({"ai_skip": {"reason": "short_call"}}, None) == (
        "held",
        "The call is too short for a report.",
    )
    assert plain_state({"ai_skip": {"reason": "no_conversation"}}, None)[1] == (
        "There's no conversation in this recording."
    )
    assert plain_state({"ai_skip": {"reason": "level"}}, None)[0] == "held"
    assert plain_state({"execution_hold": "account_profile_required"}, None)[0] == "held"
    assert plain_state({"failure_code": "provider_failed"}, None)[0] == "failed"
    assert plain_state({"automatic_progression": True}, None) == ("analysing", None)
    assert plain_state({}, {"reason": "terms"}) == ("held", key_upload.CLOSED)
    assert plain_state({}, None) == ("queued", None)


def test_the_key_upload_actor_is_never_a_sign_in_session() -> None:
    from uuid import uuid4

    from ac_platform.kernel.authz import ActorContext

    seller, tenant, key, maker = uuid4(), uuid4(), uuid4(), uuid4()
    actor = key_upload.key_actor(seller=seller, tenant_id=tenant, key_id=key, maker=maker)
    assert isinstance(actor, ActorContext) and type(actor) is not ActorContext
    assert (actor.person_id, actor.tenant_id, actor.key_id, actor.maker_person_id) == (
        seller,
        tenant,
        key,
        maker,
    )
    assert actor.session_id == key  # the key's id, never written as a session
    assert key_upload.is_open("development") and not key_upload.is_open("staging")
    assert not key_upload.is_open("production")
