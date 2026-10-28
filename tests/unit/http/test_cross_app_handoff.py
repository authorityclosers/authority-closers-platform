"""Browser handoff contract, isolated like the Android app-exchange route tests."""

from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

import ac_platform.http.auth as auth_module
import ac_platform.http.auth_transactions as transactions
from ac_platform.application.settings import Settings
from ac_platform.http.auth_transactions import (
    CROSS_APP_HANDOFF_ERROR,
    CrossAppHandoffCodec,
    InvalidAuthTransaction,
    SalesXrayAppHandoffCodec,
)
from ac_platform.http.rate_limits import (
    DEFAULT_RATE_LIMIT_RULES,
    InMemoryTokenBucketLimiter,
    RateLimitMiddleware,
)
from ac_platform.identity.services import (
    AccountClosedError,
    AccountUnavailableError,
    InvalidSessionTokenError,
    SessionExpiredError,
    SessionRevokedError,
)
from ac_platform.tenancy.learner_provisioning import (
    LearnerConsentMissingError,
    LearnerConsentUpdateRequiredError,
    LearnerProvisioningError,
)
from tests.unit.application.test_settings import _deployment_values
from tests.unit.http.test_auth_routes import (
    DEPLOYMENT_SESSION_COOKIE,
    VALID_SESSION_TOKEN,
    _AsyncContext,
    _client,
)
from tests.unit.http.test_sales_xray_auth import (
    APP_USER_AGENT,
    SALES_PRODUCTION_ORIGIN,
    SALES_STAGING_HOST,
    SALES_STAGING_ORIGIN,
    _sales_staging_settings,
)

SETTINGS = _sales_staging_settings()
LEARNER = str(SETTINGS.public_app_url).rstrip("/")
PERSON = uuid4()
VERIFIER = "a" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


class Identity:
    records: dict[str, dict] = {}
    selected: list = []
    deleting = False
    disabled = False

    def __init__(self, _database, *, token_pepper):
        pass

    async def resolve_actor(self, token):
        record = self.records.get(token)
        if record is None or record.get("audience", "account") != "account":
            raise InvalidSessionTokenError("invalid")
        if self.disabled:
            raise AccountUnavailableError("disabled")
        if self.deleting:
            raise AccountClosedError("closed")
        if record.get("revoked"):
            raise SessionRevokedError("revoked")
        if record.get("expired"):
            raise SessionExpiredError("expired")
        return SimpleNamespace(
            actor=SimpleNamespace(
                session_id=record["id"],
                person_id=PERSON,
                tenant_id=record.get("tenant"),
            )
        )

    async def issue_authenticated_session(self, person_id, **kwargs):
        assert person_id == PERSON
        assert kwargs["auto_select_tenant"] is False
        if self.deleting:
            raise AccountClosedError("closed")
        token = uuid4().hex + "x" * 11
        identifier = uuid4()
        self.records[token] = {"id": identifier}
        return SimpleNamespace(token=token, metadata=SimpleNamespace(id=identifier))

    async def revoke_self(self, token, session_id, *, reason):
        await self.resolve_actor(token)
        assert self.records[token]["id"] == session_id
        self.records[token]["revoked"] = True

    async def select_tenant(self, token, tenant_id):
        self.records[token]["tenant"] = tenant_id
        self.selected.append((token, tenant_id))


class Provisioning:
    failure = None
    calls = []

    def __init__(self, database):
        pass

    async def ensure(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure("controlled")
        return object()


class Audit:
    events = []
    fail = False

    def __init__(self, database):
        pass

    async def append(self, **kwargs):
        if self.fail:
            raise OSError("controlled audit failure")
        self.events.append(kwargs)


class Database(_AsyncContext):
    async def scalar(self, statement):
        return object()  # existing learner membership, as in the Google callback

    def begin(self):
        class Transaction(_AsyncContext):
            async def __aenter__(self):
                self.before = copy.deepcopy(Identity.records)
                return self

            async def __aexit__(self, kind, *_):
                if kind:
                    Identity.records = self.before

        return Transaction()


@pytest.fixture
def client(monkeypatch):
    Identity.records = {VALID_SESSION_TOKEN: {"id": uuid4(), "tenant": uuid4()}}
    Identity.selected = []
    Identity.deleting = Identity.disabled = False
    Audit.events = []
    Audit.fail = False
    Provisioning.failure = None
    Provisioning.calls = []
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", Identity)
    monkeypatch.setattr(auth_module, "AsyncLearnerProvisioningApplication", Provisioning)
    monkeypatch.setattr(auth_module, "AuditRepository", Audit)
    monkeypatch.setattr("tests.unit.http.test_auth_routes._sessions", Database)
    return _client(settings=SETTINGS)


def start(
    client,
    *,
    challenge=CHALLENGE,
    return_path="/learning?tab=mine",
    host=SALES_STAGING_HOST,
    origin=SALES_STAGING_ORIGIN,
    signed_in=True,
):
    headers = {"host": host, "origin": origin}
    if signed_in:
        headers["cookie"] = f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}"
    return client.post(
        "/v1/auth/handoff/start",
        json={
            "target": "learner",
            "challenge": challenge,
            "return_path": return_path,
        },
        headers=headers,
    )


def get_code(response):
    assert response.status_code == 200
    url = urlsplit(response.json()["url"])
    assert url.scheme + "://" + url.netloc == LEARNER
    assert url.path == "/auth/handoff" and not url.query
    return parse_qs(url.fragment)["code"][0]


def redeem(client, code, *, verifier=VERIFIER, host=None, origin=LEARNER):
    return client.post(
        "/v1/auth/handoff/redeem",
        json={"code": code, "verifier": verifier},
        headers={"host": host or urlsplit(LEARNER).hostname, "origin": origin},
    )


def assert_expired(response):
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_auth_transaction"
    assert response.json()["detail"] == CROSS_APP_HANDOFF_ERROR
    assert DEPLOYMENT_SESSION_COOKIE not in response.cookies


def decode(code, **kwargs):
    return CrossAppHandoffCodec(SETTINGS.oauth_transaction_secret.get_secret_value()).decode(
        code, **kwargs
    )


def test_start_needs_account_cookie(client):
    assert start(client, signed_in=False).status_code == 401


def test_start_cannot_use_reviewer_session(client):
    Identity.records[VALID_SESSION_TOKEN]["audience"] = "reviewer"
    assert start(client).status_code == 401


@pytest.mark.parametrize(
    "host,origin",
    [
        (urlsplit(LEARNER).hostname, LEARNER),
        (SALES_STAGING_HOST, LEARNER),
        (SALES_STAGING_HOST, "https://untrusted.test"),
        (SALES_STAGING_HOST, ""),
    ],
)
def test_start_requires_sales_host_and_same_surface_origin(client, host, origin):
    assert_expired(start(client, host=host, origin=origin))
    assert len(Identity.records) == 1


@pytest.mark.parametrize(
    "path",
    ["https://x", "//x", "\\x", "/\\x", "/" + "a" * 599, "/a\nb", "/a\x7fb", "/a\x85b", "/\tx"],
)
def test_start_rejects_unsafe_return_paths(client, path):
    assert start(client, return_path=path).status_code == 422
    assert len(Identity.records) == 1


@pytest.mark.parametrize("challenge", ["a" * 42, "a" * 44, "+" * 43, "a" * 42 + "\n"])
def test_start_rejects_bad_challenges(client, challenge):
    assert start(client, challenge=challenge).status_code == 422


def test_default_return_path(client):
    response = client.post(
        "/v1/auth/handoff/start",
        json={"target": "learner", "challenge": CHALLENGE},
        headers={
            "host": SALES_STAGING_HOST,
            "origin": SALES_STAGING_ORIGIN,
            "cookie": f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}",
        },
    )
    assert decode(get_code(response)).return_path == "/home"


def test_happy_path_revokes_carried_session_sets_host_only_cookie_and_audits(client):
    source = copy.deepcopy(Identity.records[VALID_SESSION_TOKEN])
    started = start(client)
    code = get_code(started)
    handoff = decode(code)
    assert handoff.session_token != VALID_SESSION_TOKEN
    assert Identity.records[handoff.session_token].get("tenant") is None
    assert DEPLOYMENT_SESSION_COOKIE not in started.cookies
    response = redeem(client, code)
    assert response.status_code == 200
    assert response.json() == {"result": "success", "return_path": "/learning?tab=mine"}
    cookie = response.headers["set-cookie"]
    for flag in ["Secure", "HttpOnly", "SameSite=lax", "Path=/"]:
        assert flag in cookie
    assert "domain=" not in cookie.lower()
    assert Identity.records[handoff.session_token]["revoked"] is True
    assert Identity.records[VALID_SESSION_TOKEN] == source
    new_token = response.cookies[DEPLOYMENT_SESSION_COOKIE]
    assert new_token not in {handoff.session_token, VALID_SESSION_TOKEN}
    assert Identity.records[new_token]["tenant"] == SETTINGS.public_learner_tenant_id
    assert [item["action"] for item in Audit.events] == [
        "identity.cross_app_handoff_started.v1",
        "identity.cross_app_handoff_redeemed.v1",
    ]
    for event in Audit.events:
        assert event["actor_person_id"] == PERSON
        assert event["payload"]["source_surface"] == "sales_xray"
        assert event["payload"]["target_surface"] == "learner"
        assert handoff.session_token not in str(event)
        assert code not in str(event)
    assert Audit.events[0]["session_id"] == handoff.session_id
    assert Audit.events[1]["payload"]["handoff_session_id"] == str(handoff.session_id)
    assert_expired(redeem(client, code))


@pytest.mark.parametrize(
    "failure,result",
    [
        (LearnerConsentMissingError, "consent_required"),
        (LearnerConsentUpdateRequiredError, "consent_update_required"),
    ],
)
def test_consent_never_silently_changes_but_account_can_open_renewal(client, failure, result):
    code = get_code(start(client))
    Provisioning.failure = failure
    response = redeem(client, code)
    assert response.json() == {"result": result, "return_path": "/learning?tab=mine"}
    assert DEPLOYMENT_SESSION_COOKIE in response.cookies
    assert Identity.records[response.cookies[DEPLOYMENT_SESSION_COOKIE]].get("tenant") is None
    assert not Identity.selected
    assert Identity.records[decode(code).session_token]["revoked"]
    assert Audit.events[-1]["payload"]["result"] == result
    assert_expired(redeem(client, code))


@pytest.mark.parametrize(
    "invalid", ["disabled", "deleting", "revoked", "expired", "wrong_id", "reviewer"]
)
def test_redeem_rejects_unusable_person_and_session(client, invalid):
    code = get_code(start(client))
    handoff = decode(code)
    if invalid in {"disabled", "deleting"}:
        setattr(Identity, invalid, True)
    elif invalid == "wrong_id":
        Identity.records[handoff.session_token]["id"] = uuid4()
    elif invalid == "reviewer":
        Identity.records[handoff.session_token]["audience"] = "reviewer"
    else:
        Identity.records[handoff.session_token][invalid] = True
    assert_expired(redeem(client, code))
    assert len(Audit.events) == 1


def test_expiry_after_61_seconds(client, monkeypatch):
    monkeypatch.setattr(transactions, "time", lambda: 1000)
    code = get_code(start(client))
    assert decode(code, now=1059)
    with pytest.raises(InvalidAuthTransaction):
        decode(code, now=1061)
    monkeypatch.setattr(transactions, "time", lambda: 1061)
    assert_expired(redeem(client, code))


def test_wrong_verifier_does_not_consume_code(client):
    code = get_code(start(client))
    assert_expired(redeem(client, code, verifier="b" * 43))
    assert not Identity.records[decode(code).session_token].get("revoked")
    assert redeem(client, code).json()["result"] == "success"


@pytest.mark.parametrize(
    "host,origin",
    [
        (SALES_STAGING_HOST, SALES_STAGING_ORIGIN),
        (urlsplit(LEARNER).hostname, SALES_STAGING_ORIGIN),
        (urlsplit(LEARNER).hostname, ""),
        ("unknown.test", LEARNER),
    ],
)
def test_redeem_requires_learner_host_and_same_surface_origin(client, host, origin):
    assert_expired(redeem(client, get_code(start(client)), host=host, origin=origin))


def test_target_origin_binding(client):
    handoff = decode(get_code(start(client)))
    code = CrossAppHandoffCodec(SETTINGS.oauth_transaction_secret.get_secret_value()).encode(
        session_token=handoff.session_token,
        session_id=handoff.session_id,
        challenge=CHALLENGE,
        source_surface="sales_xray",
        target_surface="learner",
        target_origin="https://other.test",
    )
    assert_expired(redeem(client, code))


def test_android_and_cross_app_codes_are_not_interchangeable(client):
    codec = SalesXrayAppHandoffCodec(SETTINGS.oauth_transaction_secret.get_secret_value())
    android = codec.encode(
        session_token=VALID_SESSION_TOKEN,
        session_id=uuid4(),
        flow_id=uuid4(),
        app_challenge=CHALLENGE,
    )
    assert_expired(redeem(client, android))
    cross_app = get_code(start(client))
    response = client.post(
        "/v1/auth/google/app-exchange",
        data={"code": cross_app, "verifier": VERIFIER},
        headers={
            "host": SALES_STAGING_HOST,
            "user-agent": APP_USER_AGENT,
            "sec-fetch-site": "none",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "auth_result=failed" in response.headers["location"]
    assert DEPLOYMENT_SESSION_COOKIE not in response.cookies
    with pytest.raises(InvalidAuthTransaction):
        codec.decode(cross_app)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"code": [], "verifier": 123},
        {"code": "x", "verifier": VERIFIER},
        {"code": "x" * 4097, "verifier": VERIFIER},
    ],
)
def test_malformed_redeem_never_echoes_code(client, body):
    response = client.post(
        "/v1/auth/handoff/redeem",
        json=body,
        headers={"host": urlsplit(LEARNER).hostname, "origin": LEARNER},
    )
    assert_expired(response)


def test_downstream_failure_rolls_back_session_consumption(client):
    code = get_code(start(client))
    before = copy.deepcopy(Identity.records)
    Audit.fail = True
    assert_expired(redeem(client, code))
    assert Identity.records == before
    Audit.fail = False
    assert redeem(client, code).json()["result"] == "success"


def test_provisioning_failure_does_not_create_session(client):
    code = get_code(start(client))
    before = copy.deepcopy(Identity.records)
    Provisioning.failure = LearnerProvisioningError
    assert_expired(redeem(client, code))
    assert Identity.records == before


def test_handoff_start_has_auth_start_rate_limit(client):
    rules = {rule.name: rule for rule in DEFAULT_RATE_LIMIT_RULES}
    for name in ["cross-app-handoff-start"]:
        assert rules[name].capacity == rules["oauth-start"].capacity
        assert rules[name].refill_seconds == rules["oauth-start"].refill_seconds
    client.app.add_middleware(RateLimitMiddleware)
    for _ in range(20):
        assert start(client).status_code == 200
    assert start(client).status_code == 429


def test_codec_is_sealed_bounded_and_handles_longest_unicode_path():
    codec = CrossAppHandoffCodec("test-cross-app-transaction-secret-long-enough")
    code = codec.encode(
        session_token="a" * 43,
        session_id=uuid4(),
        challenge=CHALLENGE,
        source_surface="sales_xray",
        target_surface="learner",
        target_origin="https://learner.test",
        return_path="/" + "\U00010400" * 511,
        now=1000,
    )
    assert codec.decode(code, now=1059).return_path == "/" + "\U00010400" * 511
    assert "a" * 43 not in code
    for value in [None, "", "a", "a" * 4097, "☃", code[:-1], "." * 40]:
        with pytest.raises(InvalidAuthTransaction, match="expired"):
            codec.decode(value, now=1000)
    with pytest.raises(InvalidAuthTransaction):
        codec.decode(code, now=1060)
    with pytest.raises(InvalidAuthTransaction):
        codec.decode(code, now=969)


@pytest.mark.parametrize("initial_context", ["none", "organisation"])
def test_learner_renewal_selects_public_context_and_keeps_audit_idempotent(
    monkeypatch, initial_context
):
    from dataclasses import replace

    from tests.unit.http import test_learner_consent_routes as consent_tests

    person = consent_tests._person(version=consent_tests.OLD_VERSION)
    client, database = consent_tests._client(person, monkeypatch)
    original_dependency = next(iter(client.app.dependency_overrides.values()))
    selected = []
    organisation_id = uuid4()
    original_append = consent_tests._FakeAuditRepository.append

    async def append(repository, **kwargs):
        assert kwargs["tenant_id"] == consent_tests.TENANT_ID
        return await original_append(repository, **kwargs)

    monkeypatch.setattr(consent_tests._FakeAuditRepository, "append", append)

    async def select_tenant(token, tenant_id):
        selected.append((token, tenant_id))

    identity = SimpleNamespace(select_tenant=select_tenant)

    async def handoff_actor(request):
        async for auth in original_dependency(request):
            # The first learner sign-in may have no learner membership yet.
            actor = replace(
                auth.resolved.actor,
                tenant_id=(
                    consent_tests.TENANT_ID
                    if selected
                    else organisation_id
                    if initial_context == "organisation"
                    else None
                ),
            )
            yield replace(auth, identity=identity, resolved=SimpleNamespace(actor=actor))

    # FastAPI must see the request as a Request dependency, not a query field.
    from fastapi import Request

    handoff_actor.__annotations__["request"] = Request
    dependency = next(iter(client.app.dependency_overrides))
    client.app.dependency_overrides[dependency] = handoff_actor
    monkeypatch.setattr(auth_module, "AsyncLearnerProvisioningApplication", Provisioning)
    Provisioning.failure = None
    Provisioning.calls = []
    for index in range(2):
        response = client.post(
            "/v1/me/consent/renew",
            headers={"origin": "https://app.authorityclosers.test"},
            json={"accepted": True, "expected_version": consent_tests.CURRENT_VERSION},
        )
        assert response.status_code == 200
        assert response.json()["replayed"] is (index == 1)
    assert len(Provisioning.calls) == 1
    assert len(selected) == 1 and selected[0][1] == consent_tests.TENANT_ID
    assert len(database.audit_events) == 1


@pytest.mark.parametrize("attack", ["malformed", "wrong_verifier", "consumed"])
@pytest.mark.parametrize("proxy", [False, True])
def test_redeem_throttles_attacks_despite_forwarded_header_spoofing(client, attack, proxy):
    code = get_code(start(client))
    if attack == "consumed":
        assert redeem(client, code).status_code == 200
    client = _client(settings=SETTINGS)
    rules = {rule.name: rule for rule in DEFAULT_RATE_LIMIT_RULES}
    rule = rules["cross-app-handoff-redeem"]
    assert (rule.capacity, rule.refill_seconds) == (20, 600)
    client.app.add_middleware(
        RateLimitMiddleware,
        limiter=InMemoryTokenBucketLimiter(clock=lambda: 1000.0),
        trusted_proxy_addresses=frozenset({ipaddress.ip_address("172.20.0.2")}),
    )
    # TestClient's peer is untrusted. In the proxy case, install an exact trusted
    # peer, with the stable Cloudflare identity taking precedence over spoofed XFF.
    if proxy:

        @client.app.middleware("http")
        async def trusted_peer(request, call_next):
            request.scope["client"] = ("172.20.0.2", 1000)
            return await call_next(request)

    before = copy.deepcopy(Identity.records)
    for index in range(21):
        response = client.post(
            "/v1/auth/handoff/redeem",
            json={
                "code": "malformed" if attack == "malformed" else code,
                "verifier": "b" * 43 if attack == "wrong_verifier" else VERIFIER,
            },
            headers={
                "host": urlsplit(LEARNER).hostname,
                "origin": LEARNER,
                "cf-connecting-ip": "8.8.8.8" if proxy else f"1.1.1.{index + 1}",
                "x-forwarded-for": f"9.9.9.{index + 1}",
            },
        )
        if index < 20:
            assert_expired(response)
        else:
            assert response.status_code == 429
            assert int(response.headers["retry-after"]) > 0
            assert DEPLOYMENT_SESSION_COOKIE not in response.cookies
    assert Identity.records == before


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("endpoint", ["start", "redeem"])
@pytest.mark.parametrize("origin_kind", ["absent", "null", "sibling", "lookalike"])
def test_handoff_rejects_hostile_origins_before_issuing_sessions(
    client, environment, endpoint, origin_kind
):
    values = _deployment_values(environment)
    values.update(
        {
            "sales_xray_app_url": SALES_STAGING_ORIGIN
            if environment == "staging"
            else SALES_PRODUCTION_ORIGIN,
            "public_learner_tenant_id": str(SETTINGS.public_learner_tenant_id),
            "learner_consent_version": SETTINGS.learner_consent_version,
        }
    )
    configured = Settings(environment=environment, _env_file=None, **values)
    client = _client(settings=configured)
    expected = str(
        configured.sales_xray_app_url if endpoint == "start" else configured.public_app_url
    ).rstrip("/")
    headers = {"host": urlsplit(expected).hostname}
    origins = {
        "null": "null",
        "sibling": "https://sibling.authorityclosers.test",
        "lookalike": expected + ".attacker.test",
    }
    if origin_kind != "absent":
        headers["origin"] = origins[origin_kind]
    if endpoint == "start":
        headers["cookie"] = f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}"
        body = {"target": "learner", "challenge": CHALLENGE}
    else:
        code = CrossAppHandoffCodec(configured.oauth_transaction_secret.get_secret_value()).encode(
            session_token=VALID_SESSION_TOKEN,
            session_id=Identity.records[VALID_SESSION_TOKEN]["id"],
            challenge=CHALLENGE,
            source_surface="sales_xray",
            target_surface="learner",
            target_origin=str(configured.public_app_url).rstrip("/"),
        )
        body = {"code": code, "verifier": VERIFIER}
    before = copy.deepcopy(Identity.records)
    response = client.post(f"/v1/auth/handoff/{endpoint}", headers=headers, json=body)
    assert_expired(response)
    assert Identity.records == before


@pytest.mark.parametrize(
    "injection", [{"target": "admin"}, {"tenant_id": str(uuid4())}, {"role": "owner"}]
)
def test_start_rejects_scope_injection(client, injection):
    before = copy.deepcopy(Identity.records)
    response = client.post(
        "/v1/auth/handoff/start",
        headers={
            "host": SALES_STAGING_HOST,
            "origin": SALES_STAGING_ORIGIN,
            "cookie": f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}",
        },
        json={"target": "learner", "challenge": CHALLENGE, **injection},
    )
    assert response.status_code == 422
    assert DEPLOYMENT_SESSION_COOKIE not in response.cookies
    assert Identity.records == before


@pytest.mark.parametrize("credential", ["staff_key", "duplicate_cookie"])
def test_start_requires_one_account_cookie_even_with_other_credentials(client, credential):
    headers = {"host": SALES_STAGING_HOST, "origin": SALES_STAGING_ORIGIN}
    if credential == "staff_key":
        headers["authorization"] = "Bearer synthetic-staff-key"
        headers["x-ac-staff-key"] = "synthetic-staff-key"
    else:
        headers["cookie"] = "; ".join([f"{DEPLOYMENT_SESSION_COOKIE}={VALID_SESSION_TOKEN}"] * 2)
    before = copy.deepcopy(Identity.records)
    response = client.post(
        "/v1/auth/handoff/start",
        headers=headers,
        json={"target": "learner", "challenge": CHALLENGE},
    )
    assert response.status_code == 401
    assert DEPLOYMENT_SESSION_COOKIE not in response.cookies
    assert Identity.records == before


@pytest.mark.parametrize("invalid", ["disabled", "deleting", "revoked", "expired"])
def test_start_rejects_unusable_source_sessions(client, invalid):
    if invalid in {"disabled", "deleting"}:
        setattr(Identity, invalid, True)
    else:
        Identity.records[VALID_SESSION_TOKEN][invalid] = True
    before = copy.deepcopy(Identity.records)
    response = start(client)
    assert response.status_code in {401, 403}
    assert DEPLOYMENT_SESSION_COOKIE not in response.cookies
    assert Identity.records == before
    assert not Audit.events


@pytest.mark.parametrize(
    "tamper",
    [
        "bit_flip",
        "other_key",
        "session_id",
        "source_surface",
        "target_surface",
        "challenge",
        "return_path",
    ],
)
def test_cross_app_tampering_is_generic_and_does_not_consume_session(client, tamper):
    code = get_code(start(client))
    codec = CrossAppHandoffCodec(SETTINGS.oauth_transaction_secret.get_secret_value())
    sealed = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    if tamper == "bit_flip":
        sealed = sealed[:-1] + bytes([sealed[-1] ^ 1])
    elif tamper == "other_key":
        handoff = decode(code)
        code = CrossAppHandoffCodec("different-synthetic-key-that-is-long-enough").encode(
            session_token=handoff.session_token,
            session_id=handoff.session_id,
            challenge=CHALLENGE,
            source_surface="sales_xray",
            target_surface="learner",
            target_origin=LEARNER,
        )
    else:
        # Seal altered claims with the real key to exercise binding validation,
        # independently of AES-GCM authentication of the outer ciphertext.
        nonce = sealed[:12]
        payload = json.loads(
            codec._aead.decrypt(nonce, sealed[12:], transactions._CROSS_APP_HANDOFF_AAD)
        )
        payload[tamper] = {
            "session_id": str(uuid4()),
            "source_surface": "learner",
            "target_surface": "admin",
            "challenge": "b" * 43,
            "return_path": "//attacker.test",
        }[tamper]
        sealed = nonce + codec._aead.encrypt(
            nonce, json.dumps(payload).encode(), transactions._CROSS_APP_HANDOFF_AAD
        )
    if tamper != "other_key":
        code = base64.urlsafe_b64encode(sealed).rstrip(b"=").decode()
    before = copy.deepcopy(Identity.records)
    assert_expired(redeem(client, code))
    assert Identity.records == before
    assert len(Audit.events) == 1


@pytest.mark.parametrize("victim_signed_in", [False, True])
@pytest.mark.parametrize("verifier", [None, "", "victim-verifier-with-distinct-entropy-00000000"])
def test_foreign_code_cannot_replace_existing_learner_cookie(client, victim_signed_in, verifier):
    code = get_code(start(client))
    victim_token = "v" * 43
    Identity.records[victim_token] = {"id": uuid4(), "tenant": SETTINGS.public_learner_tenant_id}
    headers = {"host": urlsplit(LEARNER).hostname, "origin": LEARNER}
    if victim_signed_in:
        headers["cookie"] = f"{DEPLOYMENT_SESSION_COOKIE}={victim_token}"
    body = {"code": code}
    if verifier is not None:
        body["verifier"] = verifier
    before = copy.deepcopy(Identity.records)
    response = client.post("/v1/auth/handoff/redeem", headers=headers, json=body)
    assert_expired(response)
    assert Identity.records == before
