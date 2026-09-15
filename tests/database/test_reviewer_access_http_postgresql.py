"""Real admission, transactional email and multi-lens feedback acceptance proof."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.models import ConversationReviewFeedback
from ac_platform.conversation_intelligence.review_contracts import ReviewAssignment
from ac_platform.http.reviewer_auth import reviewer_cookie_name, reviewer_state_cookie_name
from ac_platform.identity.models import Person, ReviewerAuthChallenge, Session
from ac_platform.providers.resend_email import render_email
from ac_platform.tenancy.models import Membership
from tests.database.reviewer_http_support import (
    account_token,
    app_for,
    deliver,
    invitation_body,
    mail_worker,
    settings_for,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reviews_postgresql import (
    ReviewCase,
    _feedback_request,
)
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)


@pytest.mark.parametrize("persona", ["new", "learner", "admin_and_learner"])
def test_real_invitation_email_identity_session_and_feedback(
    review_case: ReviewCase,
    persona: str,
) -> None:
    async def exercise() -> None:
        case = review_case
        existing = persona != "new"
        settings = settings_for(case)
        app = app_for(case, settings)
        provider_worker, provider = mail_worker(case, settings)
        admin_token = await account_token(case, settings, case.admin_actor.person_id)
        learner_token = None
        original_person_id = None
        async with case.sessions() as database:
            if existing:
                person = await database.get(
                    Person,
                    case.admin_actor.person_id
                    if persona == "admin_and_learner"
                    else case.reviewer_actor.person_id,
                )
                assert person is not None and person.email is not None
                email = person.email
                original_person_id = person.id
            else:
                email = f"invited-{uuid4().hex}@example.test"
        if persona == "admin_and_learner":
            async with case.sessions() as database, database.begin():
                database.add(
                    Membership(
                        tenant_id=case.source_actor.tenant_id,
                        person_id=case.admin_actor.person_id,
                        role="learner",
                    )
                )
        if original_person_id is not None:
            learner_token = await account_token(case, settings, original_person_id)
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.test",
                headers={"origin": "https://admin.test"},
                cookies={settings.session_cookie_name: admin_token},
            ) as admin,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.test",
                headers={"origin": "https://admin.test"},
            ) as reviewer,
        ):
            created = await admin.post(
                "/v1/admin/conversation/review-invitations",
                json=invitation_body(case, email),
                headers={"Idempotency-Key": f"invite-http-{persona}"},
            )
            assert created.status_code == 201, created.text
            invitation = await deliver(
                provider_worker, provider, "sales-xray-review-invitation", email
            )
            link = urlsplit(str(invitation.variables["action_link"]))
            assert (link.hostname, link.path) == ("admin.test", "/reviewer/invite")
            assert "workspace membership" not in render_email(invitation).text
            invitation_token = parse_qs(link.fragment)["token"][0]
            requested = await reviewer.post(
                "/v1/reviewer/auth/request",
                json={"email": email.upper(), "invitation_token": invitation_token},
            )
            assert requested.status_code == 202
            assert "HttpOnly" in requested.headers["set-cookie"]
            assert "Domain=" not in requested.headers["set-cookie"]
            original_state = reviewer.cookies[reviewer_state_cookie_name(settings)]
            sign_in = await deliver(provider_worker, provider, "reviewer-sign-in", email)
            sign_in_link = urlsplit(str(sign_in.variables["action_link"]))
            assert (sign_in_link.hostname, sign_in_link.path) == ("admin.test", "/reviewer/verify")
            assert "Open reviewer workspace" in render_email(sign_in).html
            token = parse_qs(sign_in_link.fragment)["token"][0]
            # A link copied into a different browser must neither sign that browser
            # in nor consume the legitimate browser's one-use challenge.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://admin.test",
                headers={"origin": "https://admin.test"},
            ) as victim:
                missing_state = await victim.post("/v1/reviewer/auth/verify", json={"token": token})
                assert missing_state.status_code == 401
                await victim.post(
                    "/v1/reviewer/auth/request", json={"email": "unknown@example.test"}
                )
                substituted = await victim.post("/v1/reviewer/auth/verify", json={"token": token})
                assert substituted.status_code == 401
                assert reviewer_cookie_name(settings) not in victim.cookies
            # The generic cooldown response must retain the first request's state.
            retry = await reviewer.post(
                "/v1/reviewer/auth/request",
                json={"email": email, "invitation_token": invitation_token},
            )
            assert retry.status_code == 202
            assert reviewer.cookies[reviewer_state_cookie_name(settings)] == original_state
            verified = await reviewer.post("/v1/reviewer/auth/verify", json={"token": token})
            assert verified.status_code == 200, verified.text
            person_id = UUID(verified.json()["person_id"])
            if existing:
                assert person_id == original_person_id
            assignment_id = verified.json()["assignment_id"]
            assert UUID(assignment_id)
            reviewer_token = reviewer.cookies[reviewer_cookie_name(settings)]
            assert "HttpOnly" in verified.headers["set-cookie"]
            assert "SameSite=lax" in verified.headers["set-cookie"]
            assert "Domain=" not in verified.headers["set-cookie"]
            assert reviewer_state_cookie_name(settings) not in reviewer.cookies
            replay = await reviewer.post("/v1/reviewer/auth/verify", json={"token": token})
            assert replay.status_code == 401
            assert (await reviewer.get("/v1/reviewer/me")).json()["person_id"] == str(person_id)
            assert (await reviewer.get("/v1/me")).status_code == 401
            assert (
                await reviewer.get(f"/v1/conversation/review-assignments/{assignment_id}")
            ).status_code == 404
            path = f"/v1/reviewer/review-assignments/{assignment_id}"
            loaded = await reviewer.get(path)
            assert loaded.status_code == 200
            assignment = ReviewAssignment.model_validate(loaded.json()["assignment"])
            assert loaded.json()["audio_source_url"] == f"{path}/source"
            audio = await reviewer.get(f"{path}/source", headers={"Range": "bytes=0-15"})
            assert audio.status_code == 206 and len(audio.content) == 16
            assert "private" in audio.headers["cache-control"]
            saved_ids: set[str] = set()
            for lens in ("sales", "technical", "ux"):
                body = _feedback_request(
                    case, assignment, key=f"{lens}-{persona}", lens=lens
                ).model_dump(mode="json", by_alias=True)
                saved = await reviewer.post(f"{path}/submissions", json=body)
                assert saved.status_code == 201, saved.text
                replayed = await reviewer.post(f"{path}/submissions", json=body)
                assert replayed.json()["id"] == saved.json()["id"]
                saved_ids.add(saved.json()["id"])
            history = await reviewer.get(f"{path}/submissions")
            assert {item["id"] for item in history.json()["items"]} == saved_ids
            details = await admin.get(f"/v1/admin/conversation/review-assignments/{assignment_id}")
            assert details.status_code == 200 and details.json()["feedback_count"] == 3
            assert {item["payload"]["lens"] for item in details.json()["feedback"]} == {
                "sales",
                "technical",
                "ux",
            }
            async with case.sessions() as database:
                person = await database.get(Person, person_id)
                assert person is not None and person.email_verified_at is not None
                memberships = (
                    await database.scalars(
                        select(Membership).where(Membership.person_id == person_id)
                    )
                ).all()
                assert len(memberships) == (
                    2 if persona == "admin_and_learner" else 1 if existing else 0
                )
                if existing:
                    assert any(
                        row.role == "learner" and row.status == "active" for row in memberships
                    )
                    if persona == "admin_and_learner":
                        assert any(
                            row.role == "owner" and row.status == "active" for row in memberships
                        )
                else:
                    assert person.consent_version is None and person.consented_at is None
                rows = (
                    await database.scalars(select(Session).where(Session.person_id == person_id))
                ).all()
                assert any(
                    row.audience == "reviewer" and row.selected_tenant_id is None for row in rows
                )
                assert (
                    await database.scalar(
                        select(func.count(ConversationReviewFeedback.id)).where(
                            ConversationReviewFeedback.assignment_id == assignment.id
                        )
                    )
                    == 3
                )
            # Cookie renaming cannot move either audience into the other resolver.
            for cookie_name, cookie_token, target in (
                (settings.session_cookie_name, reviewer_token, "/v1/me"),
                (reviewer_cookie_name(settings), admin_token, path),
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.test",
                    cookies={cookie_name: cookie_token},
                ) as forged:
                    assert (await forged.get(target)).status_code == 401
                    if cookie_name == settings.session_cookie_name:
                        generic_logout = await forged.post(
                            "/v1/auth/logout", headers={"Origin": "https://admin.test"}
                        )
                        # Generic logout is intentionally idempotent but must not
                        # revoke a reviewer token presented as an account cookie.
                        assert generic_logout.status_code == 204
                        assert (await reviewer.get("/v1/reviewer/me")).status_code == 200
            if learner_token is not None:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="https://admin.test",
                    cookies={settings.session_cookie_name: learner_token},
                ) as learner:
                    assert (await learner.get("/v1/me")).status_code == 200
                    if persona == "admin_and_learner":
                        selected = await learner.post(
                            "/v1/context",
                            json={"tenant_id": str(case.source_actor.tenant_id)},
                            headers={"Origin": "https://admin.test"},
                        )
                        assert selected.status_code == 200
                        assert selected.json()["membership_role"] == "learner"
                    assert (await learner.get(path)).status_code == 401
            revoked = await admin.post(
                f"/v1/admin/conversation/review-assignments/{assignment_id}/revoke",
                headers={"Idempotency-Key": f"revoke-http-{persona}"},
            )
            assert revoked.status_code == 200
            assert (await reviewer.get(path)).status_code == 403
            assert (
                await admin.get(f"/v1/admin/conversation/review-assignments/{assignment_id}")
            ).json()["feedback_count"] == 3
            assert (await reviewer.post("/v1/reviewer/auth/logout")).status_code == 204
            assert (await reviewer.get("/v1/reviewer/me")).status_code == 401
            assert (await admin.get("/v1/me")).status_code == 200

    run(exercise())


def test_uninvited_request_does_not_create_identity_or_send_mail(review_case: ReviewCase) -> None:
    async def exercise() -> None:
        settings = settings_for(review_case)
        app = app_for(review_case, settings)
        email = f"not-invited-{uuid4().hex}@example.test"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://admin.test"
        ) as client:
            denied = await client.post(
                "/v1/reviewer/auth/request",
                json={"email": email},
                headers={"Origin": "https://learner.test"},
            )
            assert denied.status_code == 403
            requested = await client.post(
                "/v1/reviewer/auth/request",
                json={"email": email},
                headers={"Origin": "https://admin.test"},
            )
            assert requested.status_code == 202 and requested.json() == {"status": "check_email"}
        async with review_case.sessions() as database:
            assert await database.scalar(select(Person.id).where(Person.email == email)) is None
            assert (
                await database.scalar(
                    select(ReviewerAuthChallenge.id).where(ReviewerAuthChallenge.email == email)
                )
                is None
            )

    run(exercise())
