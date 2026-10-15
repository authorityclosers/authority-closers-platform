"""Fictional actors, tenants and resources for the authorization gate.

Everything here is deterministic (uuid5 identities, derived tokens) so the
generated expectation table is byte-stable.  No real person, tenant, secret or
recording is involved; the world lives in a disposable PostgreSQL schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from scripts.ci.authorization_gate import stable_token, stable_uuid

OPERATIONS_TENANT = stable_uuid("tenant:operations")
ACADEMY_TENANT = stable_uuid("tenant:academy")
ORGANISATION_TENANT = stable_uuid("tenant:organisation")
FOREIGN_ORGANISATION_TENANT = stable_uuid("tenant:foreign-organisation")
FOREIGN_ACADEMY_TENANT = stable_uuid("tenant:foreign-academy")
NOW = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

PEOPLE = (
    "owner",
    "admin",
    "member",
    "learner",
    "staff",
    "staff_revoked",
    "operator",
    "foreign_owner",
    "foreign_learner",
)
# (actor, context) -> (session name or None, resource world, foreign?)
CONTEXTS: dict[tuple[str, str], tuple[str | None, str, bool]] = {
    ("guest", "anonymous"): (None, "academy", False),
    ("learner", "academy"): ("learner@academy", "academy", False),
    ("learner", "academy_foreign"): ("learner@academy", "foreign_academy", True),
    ("member", "organisation"): ("member@organisation", "organisation", False),
    ("member", "organisation_foreign"): ("member@organisation", "foreign_organisation", True),
    ("admin", "organisation"): ("admin@organisation", "organisation", False),
    ("admin", "organisation_foreign"): ("admin@organisation", "foreign_organisation", True),
    ("admin", "academy"): ("admin@academy", "academy", False),
    ("admin", "academy_foreign"): ("admin@academy", "foreign_academy", True),
    ("owner", "organisation"): ("owner@organisation", "organisation", False),
    ("owner", "organisation_foreign"): ("owner@organisation", "foreign_organisation", True),
    ("owner", "academy"): ("owner@academy", "academy", False),
    ("owner", "academy_foreign"): ("owner@academy", "foreign_academy", True),
    ("admin", "operations"): ("admin@operations", "operations", False),
    ("owner", "operations"): ("owner@operations", "operations", False),
    ("staff", "platform"): ("staff@platform", "platform", False),
    ("staff", "platform_revoked"): ("staff_revoked@platform", "platform", False),
}
SESSIONS: dict[str, tuple[str, UUID | None]] = {
    "owner@organisation": ("owner", ORGANISATION_TENANT),
    "owner@academy": ("owner", ACADEMY_TENANT),
    "admin@organisation": ("admin", ORGANISATION_TENANT),
    "admin@academy": ("admin", ACADEMY_TENANT),
    "member@organisation": ("member", ORGANISATION_TENANT),
    "learner@academy": ("learner", ACADEMY_TENANT),
    "admin@operations": ("admin", OPERATIONS_TENANT),
    "owner@operations": ("owner", OPERATIONS_TENANT),
    "staff@platform": ("staff", None),
    "staff_revoked@platform": ("staff_revoked", None),
    "operator@operations": ("operator", OPERATIONS_TENANT),
    "foreign_owner@foreign_organisation": ("foreign_owner", FOREIGN_ORGANISATION_TENANT),
}
MEMBERSHIPS = (
    ("owner", ORGANISATION_TENANT, "owner"),
    ("owner", ACADEMY_TENANT, "owner"),
    ("admin", ORGANISATION_TENANT, "admin"),
    ("admin", ACADEMY_TENANT, "admin"),
    ("owner", OPERATIONS_TENANT, "owner"),
    ("admin", OPERATIONS_TENANT, "admin"),
    ("member", ORGANISATION_TENANT, "member"),
    ("learner", ACADEMY_TENANT, "learner"),
    ("operator", OPERATIONS_TENANT, "owner"),
    ("foreign_owner", FOREIGN_ORGANISATION_TENANT, "owner"),
    ("foreign_owner", FOREIGN_ACADEMY_TENANT, "owner"),
    ("foreign_learner", FOREIGN_ACADEMY_TENANT, "learner"),
)
# Which application host serves a route (first matching prefix wins).
SURFACES: tuple[tuple[str, str], ...] = (
    ("/v1/admin/", "admin"),
    ("/v1/platform/", "admin"),
    ("/v1/me/platform-access", "admin"),
    ("/v1/reviewer", "admin"),
    ("/v1/updates", "sales_xray"),
    ("/v1/notifications", "sales_xray"),
    ("/v1/auth/email-code", "sales_xray"),
    ("/v1/organisation", "sales_xray"),
    ("/v1/conversation", "sales_xray"),
    ("/v1/me/sales-xray", "sales_xray"),
    ("/v1/me/coaching", "sales_xray"),
    ("/v1/me/workspaces", "sales_xray"),
    ("/v1/plans", "sales_xray"),
    ("/v1/reviewer", "sales_xray"),
    ("/v1/native", "sales_xray"),
    ("/v1/billing", "sales_xray"),
)


def person_id(name: str) -> UUID:
    return stable_uuid(f"person:{name}")


def session_id(name: str) -> UUID:
    return stable_uuid(f"session:{name}")


def command_uuid(name: str) -> str:
    """A deterministic value shaped like a canonical UUIDv4 for Idempotency-Key."""

    raw = bytearray(stable_uuid(f"command:{name}").bytes)
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(raw)))


@dataclass(slots=True)
class World:
    tokens: dict[str, str]
    resources: dict[str, dict[str, Any]]


@dataclass(slots=True)
class Plan:
    actor: str
    context: str
    base_context: str
    foreign: bool
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    content: bytes | None = None
    client: tuple[str, int] = ("127.0.0.1", 40000)
    skip: str = ""
    etag_from: str = ""
    etag_json: str = ""


def sales_xray_runtime(scratch: Path, settings: Any) -> Any:
    from pydantic import SecretStr

    from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
    from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
    from ac_platform.conversation_intelligence.intake import IntakePolicy
    from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
    from ac_platform.http.conversation_acquisition_runtime import AcquisitionRuntime
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime

    class _Native:
        def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: int) -> dict:
            raise RuntimeError("the authorization gate never inspects media")

        def validate_source(self, source: Path, outdir: Path, *, job_id: UUID, rate: int) -> dict:
            raise RuntimeError("the authorization gate never validates media")

    scratch.mkdir(parents=True, exist_ok=True)
    policy = IntakePolicy(
        budget_scope_id=stable_uuid("budget-scope"),
        tenant_ids=frozenset({ACADEMY_TENANT, ORGANISATION_TENANT, FOREIGN_ORGANISATION_TENANT}),
        authorization_ref="ref:intake:authorization-gate",
        retention_ref="ref:retention:authorization-gate",
    )
    return AcquisitionRuntime(
        intake=ConversationIntakeRuntime(
            policy=policy,
            storage=PrivateLocalRecordingStorage(scratch / "store"),
            scratch=PrivateLocalRecordingStorage(scratch / "scratch"),
        ),
        challenge=UploadChallenge(
            secret=SecretStr(stable_token("upload-challenge")),
            hostname=settings.sales_xray_app_url.host,
        ),
        preflight=NativeUploadPreflight(_Native()),
        site_key=settings.sales_xray_challenge_site_key,
        policy_revision=settings.sales_xray_acquisition_policy_revision,
    )


async def seed_world(sessions: Any, settings: Any) -> World:
    import hashlib
    import hmac

    from ac_platform.authorization.application import CapabilityApplication
    from ac_platform.authorization.models import PLATFORM_CAPABILITIES
    from ac_platform.authorization.policy import CapabilityScope
    from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
    from ac_platform.identity.models import Person
    from ac_platform.identity.models import Session as IdentitySession
    from ac_platform.kernel.authz import ActorContext
    from ac_platform.tenancy.models import Membership, Organisation, Tenant

    pepper = settings.session_token_pepper.get_secret_value().encode()
    tokens = {name: stable_token(f"session-token:{name}") for name in SESSIONS}
    resources: dict[str, dict[str, Any]] = {
        "academy": {"tenant_id": ACADEMY_TENANT},
        "foreign_academy": {"tenant_id": FOREIGN_ACADEMY_TENANT},
        "organisation": {"tenant_id": ORGANISATION_TENANT},
        "foreign_organisation": {"tenant_id": FOREIGN_ORGANISATION_TENANT},
        "operations": {"tenant_id": OPERATIONS_TENANT},
    }
    async with sessions() as db, db.begin():
        db.add_all(
            [
                Tenant(id=OPERATIONS_TENANT, slug="gate-operations", name="Gate operations"),
                Tenant(id=ACADEMY_TENANT, slug="gate-academy", name="Gate academy"),
                Tenant(id=ORGANISATION_TENANT, slug="gate-closers", name="Gate Closers Ltd"),
                Tenant(id=FOREIGN_ORGANISATION_TENANT, slug="gate-other-co", name="Gate Other Co"),
                Tenant(id=FOREIGN_ACADEMY_TENANT, slug="gate-other-academy", name="Other academy"),
            ]
        )
        for name in PEOPLE:
            db.add(
                Person(
                    id=person_id(name),
                    email=f"{name.replace('_', '-')}@example.test",
                    first_name=name.replace("_", " ").title(),
                    display_name=name.replace("_", " ").title(),
                    email_verified_at=NOW,
                    consent_version="2026-01",
                    consented_at=NOW,
                )
            )
        await db.flush()
        for name, tenant, role in MEMBERSHIPS:
            db.add(Membership(tenant_id=tenant, person_id=person_id(name), role=role))
        for tenant, label in (
            (ORGANISATION_TENANT, "organisation"),
            (FOREIGN_ORGANISATION_TENANT, "foreign-organisation"),
        ):
            db.add(
                Organisation(
                    tenant_id=tenant,
                    created_by_person_id=person_id(
                        "owner" if label == "organisation" else "foreign_owner"
                    ),
                    creation_command_id=stable_uuid(f"organisation:{label}"),
                    domain_verification_token=stable_token(f"domain:{label}"),
                )
            )
        await db.flush()
        for name, (person, tenant) in SESSIONS.items():
            db.add(
                IdentitySession(
                    id=session_id(name),
                    person_id=person_id(person),
                    selected_tenant_id=tenant,
                    token_hash=hmac.new(pepper, tokens[name].encode(), hashlib.sha256).digest(),
                    created_at=NOW,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        await db.flush()

        def catalog(sync: Any) -> None:
            service = CatalogService(SqlAlchemyCatalogStore(sync))
            for world, tenant in (
                ("academy", ACADEMY_TENANT),
                ("foreign_academy", FOREIGN_ACADEMY_TENANT),
            ):
                program = service.create_program(
                    tenant_id=tenant,
                    slug=f"{world}-course".replace("_", "-"),
                    title="Gate course",
                    program_id=stable_uuid(f"program:{world}"),
                )
                version = service.create_version(
                    program.id, tenant_id=tenant, version_id=stable_uuid(f"version:{world}")
                )
                module = service.add_module(
                    version.id,
                    tenant_id=tenant,
                    title="Gate module",
                    module_id=stable_uuid(f"module:{world}"),
                )
                activity = service.add_activity(
                    module.id,
                    tenant_id=tenant,
                    kind="VIDEO",
                    title="Gate activity",
                    activity_id=stable_uuid(f"activity:{world}"),
                )
                resources[world].update(
                    program_id=program.id,
                    program_version_id=version.id,
                    version_id=version.id,
                    module_id=module.id,
                    activity_id=activity.id,
                    slug=program.slug,
                )

        await db.run_sync(catalog)

    # Platform capability grants: bootstrap the operations owner as the first
    # manager, then grant staff every platform capability; revoke one twin.
    async with sessions() as db, db.begin():
        capabilities = CapabilityApplication(db, operations_tenant_id=OPERATIONS_TENANT)
        await capabilities.bootstrap_first_manager(
            person_id=person_id("operator"),
            command_id=stable_uuid("grant:bootstrap"),
            reason="Authorization gate fixture bootstrap",
        )
        manager = ActorContext(
            person_id("operator"), session_id("operator@operations"), OPERATIONS_TENANT
        )
        for subject in ("staff", "staff_revoked"):
            for permission in sorted(PLATFORM_CAPABILITIES):
                grant = await capabilities.grant(
                    manager,
                    command_id=stable_uuid(f"grant:{subject}:{permission}"),
                    subject_person_id=person_id(subject),
                    permission=permission,
                    scope=CapabilityScope("platform"),
                    reason="Authorization gate fixture grant",
                )
                if subject == "staff_revoked":
                    await capabilities.revoke(
                        manager,
                        command_id=stable_uuid(f"revoke:{subject}:{permission}"),
                        grant_id=grant.id,
                        reason="Authorization gate fixture revocation",
                    )
    for name in PEOPLE:
        for world in resources.values():
            world.setdefault(f"{name}_person_id", person_id(name))
    resources["academy"]["person_id"] = person_id("learner")
    resources["foreign_academy"]["person_id"] = person_id("foreign_learner")
    resources["organisation"]["person_id"] = person_id("member")
    resources["foreign_organisation"]["person_id"] = person_id("foreign_owner")
    resources["platform"] = {**resources["academy"], **resources["organisation"]}
    return World(tokens=tokens, resources=resources)


def resources_for(world: World, world_name: str, session: str | None) -> dict[str, Any]:
    """The acting context's ids over the defaults of its side (own or foreign).

    Every path parameter resolves somewhere, so a route is always reachable;
    the response then shows what happens when, say, an organisation member
    names an academy program.  Person-owned ids come last and win.
    """

    foreign = world_name.startswith("foreign_")
    sides = ("foreign_academy", "foreign_organisation") if foreign else ("academy", "organisation")
    merged: dict[str, Any] = {}
    for side in sides:
        merged.update(world.resources.get(side, {}))
    merged.update(world.resources.get(world_name, {}))
    if session is not None and not foreign:
        merged.update(world.resources.get(f"person:{session.split('@')[0]}", {}))
    return merged


# --- request synthesis ----------------------------------------------------------------


def surface_host(settings: Any, path: str) -> str:
    surface = next((name for prefix, name in SURFACES if path.startswith(prefix)), "learner")
    if surface == "sales_xray" and settings.sales_xray_app_url is None:
        surface = "learner"
    url = {
        "admin": settings.admin_app_url,
        "sales_xray": settings.sales_xray_app_url,
        "coach": settings.coach_app_url,
        "learner": settings.public_app_url,
    }[surface]
    return str(url.host)


def resolve_path(path: str, resources: dict[str, Any]) -> tuple[str, str]:
    """Fill ``{param}`` placeholders; return (url path, missing parameter or '')."""

    import re

    missing = ""

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1).split(":")[0]
        if name not in resources:
            missing = missing or name
            return match.group(0)
        return str(resources[name])

    return re.sub(r"{([^}]+)}", replace, path), missing


def _body_schema(route: Any) -> dict[str, Any] | None:
    body_field = getattr(route, "body_field", None)
    if body_field is None:
        return None
    annotation = getattr(body_field, "type_", None) or getattr(
        getattr(body_field, "field_info", None), "annotation", None
    )
    model_json_schema = getattr(annotation, "model_json_schema", None)
    if model_json_schema is None:
        return None
    return model_json_schema(mode="validation")


def _query_string(route: Any, resources: dict[str, Any]) -> str:
    """Required query parameters, synthesised from their declared types."""

    from urllib.parse import urlencode

    from pydantic import TypeAdapter

    dependant = getattr(route, "dependant", None)
    values: dict[str, Any] = {}
    for param in getattr(dependant, "query_params", ()):
        if not param.field_info.is_required():
            continue
        annotation = getattr(param.field_info, "annotation", None) or str
        try:
            schema = TypeAdapter(annotation).json_schema(mode="validation")
        except Exception:  # noqa: BLE001 - fall back to a plain string
            schema = {"type": "string"}
        values[param.name] = synthesize(schema, schema.get("$defs", {}), resources, param.name)
    return urlencode({key: value for key, value in values.items() if value is not None})


ALIASES = {
    "organisation": "tenant_id",
    "organisation_id": "tenant_id",
    "workspace_id": "tenant_id",
    "subject_person_id": "person_id",
    "target_person_id": "person_id",
    "member_person_id": "person_id",
}
PATTERN_CANDIDATES = (
    "gate-fixture",
    "gate_fixture",
    "gatefixture",
    "0" * 64,
    "a" * 64,
    "syn-gate-fixture",
    "+15550100000",
    "GATE",
    "1",
)


def _patterned(pattern: str) -> str:
    import re

    for candidate in PATTERN_CANDIDATES:
        try:
            if re.fullmatch(pattern, candidate) or re.match(pattern, candidate):
                return candidate
        except re.error:
            break
    return "gate-fixture"


def synthesize(
    schema: dict[str, Any], defs: dict[str, Any], resources: dict[str, Any], name: str = ""
) -> Any:
    """Build one schema-valid, deterministic value; ids come from the fixture world."""

    if "$ref" in schema:
        return synthesize(defs[schema["$ref"].rsplit("/", 1)[-1]], defs, resources, name)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [option for option in schema[key] if option.get("type") != "null"]
            return synthesize((options or schema[key])[0], defs, resources, name)
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for option in schema["allOf"]:
            merged.update(
                option if "$ref" not in option else defs[option["$ref"].rsplit("/", 1)[-1]]
            )
        return synthesize(merged, defs, resources, name)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), kind[0])
    if kind == "object" or "properties" in schema:
        return {
            key: synthesize(value, defs, resources, key)
            for key, value in schema.get("properties", {}).items()
            if key in set(schema.get("required", ()))
        }
    if kind == "array":
        if schema.get("minItems", 0) > 0:
            return [synthesize(schema.get("items", {}), defs, resources, name)]
        return []
    if kind == "integer" or kind == "number":
        low = schema.get(
            "minimum", schema.get("exclusiveMinimum", 0) + 1 if "exclusiveMinimum" in schema else 1
        )
        high = schema.get(
            "maximum",
            schema.get("exclusiveMaximum", low + 1) - 1 if "exclusiveMaximum" in schema else low,
        )
        return min(max(low, 1), high) if kind == "integer" else float(min(max(low, 1), high))
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    # strings
    name = ALIASES.get(name, name)
    if name in resources and (schema.get("format") == "uuid" or name.endswith("_id")):
        return str(resources[name])
    text_format = schema.get("format")
    if text_format == "uuid" or name.endswith("_id"):
        return str(stable_uuid(f"synthesized:{name}"))
    if text_format == "email" or name.endswith("email"):
        return "fixture@example.test"
    if text_format == "date-time":
        return "2026-01-15T09:00:00Z"
    if text_format == "date":
        return "2026-01-15"
    if text_format == "uri":
        return "https://example.test/fixture"
    value = resources.get(name) if isinstance(resources.get(name), str) else None
    if value is None and "pattern" in schema:
        value = _patterned(schema["pattern"])
    if value is None:
        value = "gate-fixture"
        minimum = schema.get("minLength", 0)
        if len(value) < minimum:
            value = (value + "-x" * minimum)[:minimum]
        maximum = schema.get("maxLength")
        if maximum is not None and len(value) > maximum:
            value = value[:maximum]
    return value


def request_plan(world: World, settings: Any, method: str, path: str, route: Any) -> list[Plan]:
    import json

    from scripts.ci.authorization_route_overrides import override

    plans: list[Plan] = []
    host = surface_host(settings, path)
    schema = _body_schema(route)
    defs = schema.get("$defs", {}) if schema else {}
    index = 0
    for (actor, context), (session, world_name, foreign) in CONTEXTS.items():
        index += 1
        resources = resources_for(world, world_name, session)
        base_context = context.removesuffix("_foreign")
        plan = Plan(actor=actor, context=context, base_context=base_context, foreign=foreign)
        plan.client = (f"10.77.{index // 200}.{index % 200 + 1}", 40000)
        url_path, missing = resolve_path(path, resources)
        if foreign and "{" not in path:
            continue
        custom = override(method, path, actor, context, resources)
        if custom is not None and custom.get("skip"):
            plan.skip = str(custom["skip"])
            plans.append(plan)
            continue
        if missing and not (custom and "path" in custom):
            plan.skip = f"no fixture for path parameter {missing}"
            plans.append(plan)
            continue
        if custom and "path" in custom:
            url_path = str(custom["path"])
        query = (
            custom.get("query") if custom and "query" in custom else _query_string(route, resources)
        )
        plan.url = f"https://{host}{url_path}{'?' + query if query else ''}"
        if custom and "etag_from" in custom:
            etag_path, _ = resolve_path(str(custom["etag_from"]), resources)
            plan.etag_from = f"https://{host}{etag_path}"
            plan.etag_json = str(custom.get("etag_json", ""))
        plan.headers = {"origin": f"https://{host}", "x-request-id": f"gate-{index}"}
        if method in MUTATING:
            plan.headers["idempotency-key"] = command_uuid(f"{method} {path} {actor} {context}")
        if session is not None:
            plan.cookies = {settings.session_cookie_name: world.tokens[session]}
        if custom and "content" in custom:
            plan.content = custom["content"]
            plan.headers["content-type"] = custom.get("content_type", "application/octet-stream")
        elif custom and "json" in custom:
            plan.content = json.dumps(custom["json"]).encode()
            plan.headers["content-type"] = "application/json"
        elif schema is not None:
            plan.content = json.dumps(synthesize(schema, defs, resources)).encode()
            plan.headers["content-type"] = "application/json"
        if custom and "headers" in custom:
            plan.headers.update(custom["headers"])
        plans.append(plan)
    return plans
