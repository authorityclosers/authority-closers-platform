"""Pure paired minute/project-budget ledger; no database, provider calls or credentials.

Load permissions and approvals from AC authority, then lock BOTH the minute account and
shared budget row. Persist both next snapshots and a journal event in one transaction.
Fingerprint possession and data deserialization never confer execution authorization.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, ClassVar, Self

from .checkpoints import SourceBinding, content_hash, require_sha256, require_text

NORMAL_CAP_PAISE = 150_000
OWNER_CEILING_PAISE = 200_000


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid integer {field}")
    return value


def _strings(instance: Any, names: tuple[str, ...]) -> None:
    for name in names:
        require_text(getattr(instance, name), name)


def _source(value: Any) -> SourceBinding:
    if not isinstance(value, dict) or set(value) != {
        "tenant_id",
        "recording_id",
        "source_sha256",
        "source_revision",
    }:
        raise ValueError("invalid source binding snapshot")
    return SourceBinding(**value)


def _tuple(value: Any, decoder: Callable[[Any], Any]) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError("snapshot collection must be a JSON array")
    return tuple(decoder(item) for item in value)


class Snapshot:
    _decoders: ClassVar[dict[str, Callable[[Any], Any]]] = {}

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"schema": f"ac.sales_xray.{type(self).__name__}/1"}
        for field in fields(self):  # type: ignore[arg-type]
            value = getattr(self, field.name)
            if isinstance(value, Snapshot):
                result[field.name] = value.as_dict()
            elif isinstance(value, SourceBinding):
                result[field.name] = asdict(value)
            elif isinstance(value, tuple):
                result[field.name] = [v.as_dict() if isinstance(v, Snapshot) else v for v in value]
            else:
                result[field.name] = value
        return result

    @classmethod
    def from_dict(cls, value: Any) -> Self:
        expected = {field.name for field in fields(cls)}  # type: ignore[arg-type]
        if not isinstance(value, dict) or set(value) != expected | {"schema"}:
            raise ValueError(f"invalid {cls.__name__} snapshot fields")
        if value["schema"] != f"ac.sales_xray.{cls.__name__}/1":
            raise ValueError("unsupported snapshot schema")
        arguments = {key: value[key] for key in expected}
        for key, decode in cls._decoders.items():
            arguments[key] = decode(arguments[key])
        return cls(**arguments)

    @property
    def fingerprint(self) -> str:
        return content_hash(self.as_dict())


@dataclass(frozen=True)
class MinuteGrant(Snapshot):
    tenant_id: str
    account_id: str
    grant_id: str
    seconds: int
    authorization_ref: str
    granted_by: str
    reason: str

    def __post_init__(self) -> None:
        _strings(
            self,
            ("tenant_id", "account_id", "grant_id", "authorization_ref", "granted_by", "reason"),
        )
        _integer(self.seconds, "grant seconds", 1)


@dataclass(frozen=True)
class BudgetCapApproval(Snapshot):
    scope_id: str
    approval_ref: str
    owner_actor_id: str
    approved_cap_paise: int
    previous_budget_fingerprint: str
    reason: str
    explicit_above_ceiling: bool = False

    def __post_init__(self) -> None:
        _strings(self, ("scope_id", "approval_ref", "owner_actor_id", "reason"))
        _integer(self.approved_cap_paise, "approved cap paise")
        require_sha256(self.previous_budget_fingerprint, "previous budget fingerprint")
        if type(self.explicit_above_ceiling) is not bool:
            raise ValueError("explicit ceiling approval must be boolean")
        if self.approved_cap_paise > OWNER_CEILING_PAISE and not self.explicit_above_ceiling:
            raise ValueError("above INR2000 requires explicit new owner ceiling approval")
        if self.approved_cap_paise > NORMAL_CAP_PAISE and (
            self.previous_budget_fingerprint == "0" * 64
        ):
            raise ValueError("higher cap requires a new approval bound to the prior budget")


@dataclass(frozen=True)
class Quote(Snapshot):
    quote_id: str
    source: SourceBinding
    account_id: str
    budget_scope_id: str
    provider_id: str
    provider_model: str
    recipe_revision: str
    operation: str
    input_sha256: str
    privacy_revision: str
    permission_ref: str
    provider_terms_ref: str
    retention_ref: str
    professional_gate_ref: str
    pricing_ref: str
    entitlement_seconds: int
    max_cost_paise: int
    created_at_epoch: int
    expires_at_epoch: int
    provider_configuration_sha256: str | None = None

    _decoders: ClassVar[dict[str, Callable[[Any], Any]]] = {"source": _source}

    def as_dict(self) -> dict[str, Any]:
        value = super().as_dict()
        # The field was added after snapshot /1. Omitting an unset value keeps
        # legacy quote fingerprints and permission bindings byte-for-byte.
        if self.provider_configuration_sha256 is None:
            value.pop("provider_configuration_sha256", None)
        return value

    @classmethod
    def from_dict(cls, value: Any) -> Self:
        # Existing reservations have no configuration identity. Decode them
        # as the immutable legacy route and let authority recover its digest
        # from the approval id before any current activation is considered.
        if isinstance(value, dict) and "provider_configuration_sha256" not in value:
            value = {**value, "provider_configuration_sha256": None}
        return super().from_dict(value)

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceBinding):
            raise ValueError("quote requires immutable source binding")
        _strings(
            self,
            (
                "quote_id",
                "account_id",
                "budget_scope_id",
                "provider_id",
                "provider_model",
                "recipe_revision",
                "operation",
                "privacy_revision",
                "permission_ref",
                "provider_terms_ref",
                "retention_ref",
                "professional_gate_ref",
                "pricing_ref",
            ),
        )
        require_sha256(self.input_sha256, "input sha256")
        if self.provider_configuration_sha256 is not None:
            require_sha256(
                self.provider_configuration_sha256,
                "provider configuration sha256",
            )
        _integer(self.entitlement_seconds, "entitlement seconds")
        _integer(self.max_cost_paise, "max cost paise")
        _integer(self.created_at_epoch, "quote creation epoch")
        _integer(self.expires_at_epoch, "quote expiry epoch")
        if self.expires_at_epoch <= self.created_at_epoch:
            raise ValueError("quote expiry must follow creation")


@dataclass(frozen=True)
class ExecutionPermission(Snapshot):
    authorization_ref: str
    quote_fingerprint: str
    approved_by: str
    expires_at_epoch: int

    def __post_init__(self) -> None:
        _strings(self, ("authorization_ref", "approved_by"))
        require_sha256(self.quote_fingerprint, "permission quote fingerprint")
        _integer(self.expires_at_epoch, "permission expiry epoch", 1)


@dataclass(frozen=True)
class SettlementReceipt(Snapshot):
    reservation_id: str
    quote_fingerprint: str
    provider_id: str
    attempt_id: str
    actual_seconds: int
    actual_paise: int
    receipt_ref: str

    def __post_init__(self) -> None:
        _strings(self, ("reservation_id", "provider_id", "attempt_id", "receipt_ref"))
        require_sha256(self.quote_fingerprint, "settlement quote fingerprint")
        _integer(self.actual_seconds, "actual seconds")
        _integer(self.actual_paise, "actual paise")


@dataclass(frozen=True)
class NoChargeReceipt(Snapshot):
    reservation_id: str
    quote_fingerprint: str
    provider_id: str
    attempt_id: str
    receipt_ref: str
    outcome: str

    def __post_init__(self) -> None:
        _strings(self, ("reservation_id", "provider_id", "attempt_id", "receipt_ref"))
        require_sha256(self.quote_fingerprint, "no-charge quote fingerprint")
        if self.outcome != "confirmed_not_executed_or_charged":
            raise ValueError("release needs confirmed no execution AND no charge")


def _optional_receipt(value: Any) -> SettlementReceipt | None:
    return None if value is None else SettlementReceipt.from_dict(value)


def _optional_no_charge(value: Any) -> NoChargeReceipt | None:
    return None if value is None else NoChargeReceipt.from_dict(value)


@dataclass(frozen=True)
class Reservation(Snapshot):
    reservation_id: str
    quote: Quote
    permission: ExecutionPermission
    state: str = "reserved"
    attempt_id: str | None = None
    uncertainty_ref: str | None = None
    settlement: SettlementReceipt | None = None
    release_reason_ref: str | None = None
    no_charge_receipt: NoChargeReceipt | None = None

    _decoders: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "quote": Quote.from_dict,
        "permission": ExecutionPermission.from_dict,
        "settlement": _optional_receipt,
        "no_charge_receipt": _optional_no_charge,
    }

    def __post_init__(self) -> None:
        require_text(self.reservation_id, "reservation id")
        if not isinstance(self.quote, Quote) or not isinstance(
            self.permission, ExecutionPermission
        ):
            raise ValueError("reservation requires typed quote and permission")
        if self.permission.quote_fingerprint != self.quote.fingerprint:
            raise ValueError("permission is not bound to exact recording/provider/privacy quote")
        if self.state not in {
            "reserved",
            "in_flight",
            "uncertain",
            "settled",
            "released",
            "reconciliation_required",
        }:
            raise ValueError("unknown reservation state")
        for value, name in (
            (self.attempt_id, "attempt id"),
            (self.uncertainty_ref, "uncertainty ref"),
            (self.release_reason_ref, "release reason ref"),
        ):
            if value is not None:
                require_text(value, name)
        if self.state == "reserved" and self.attempt_id is not None:
            raise ValueError("reserved state cannot hide a provider attempt")
        if self.state in {"reserved", "in_flight"} and self.uncertainty_ref is not None:
            raise ValueError("uncertainty evidence requires a recorded uncertain outcome")
        if self.state in {"in_flight", "uncertain", "settled", "reconciliation_required"}:
            require_text(self.attempt_id, "attempt id required after dispatch")
        if (self.settlement is not None) != (self.state in {"settled", "reconciliation_required"}):
            raise ValueError("settlement receipt/state mismatch")
        if self.settlement is not None:
            _match_receipt(self, self.settlement)
            exceeds = self.settlement.actual_seconds > self.quote.entitlement_seconds or (
                self.settlement.actual_paise > self.quote.max_cost_paise
            )
            if exceeds != (self.state == "reconciliation_required"):
                raise ValueError("overrun must remain in explicit reconciliation hold")
        if self.state == "uncertain" and self.uncertainty_ref is None:
            raise ValueError("uncertain outcome needs evidence reference")
        if (self.release_reason_ref is not None) != (self.state == "released"):
            raise ValueError("release receipt/state mismatch")
        if self.no_charge_receipt is not None:
            if self.state != "released":
                raise ValueError("no-charge receipt is only for confirmed release")
            _match_receipt(self, self.no_charge_receipt)
        if (
            self.state == "released"
            and self.attempt_id is not None
            and self.no_charge_receipt is None
        ):
            raise ValueError("dispatched release requires no-charge reconciliation")

    @property
    def committed_seconds(self) -> int:
        if self.state == "released":
            return 0
        if self.state == "settled" and self.settlement is not None:
            return self.settlement.actual_seconds
        if self.state == "reconciliation_required" and self.settlement is not None:
            return max(self.quote.entitlement_seconds, self.settlement.actual_seconds)
        return self.quote.entitlement_seconds

    @property
    def committed_paise(self) -> int:
        if self.state == "released":
            return 0
        if self.state == "settled" and self.settlement is not None:
            return self.settlement.actual_paise
        if self.state == "reconciliation_required" and self.settlement is not None:
            return max(self.quote.max_cost_paise, self.settlement.actual_paise)
        return self.quote.max_cost_paise


def _match_receipt(reservation: Reservation, receipt: SettlementReceipt | NoChargeReceipt) -> None:
    if not isinstance(receipt, (SettlementReceipt, NoChargeReceipt)):
        raise ValueError("typed provider reconciliation receipt required")
    if (
        receipt.reservation_id,
        receipt.quote_fingerprint,
        receipt.provider_id,
        receipt.attempt_id,
    ) != (
        reservation.reservation_id,
        reservation.quote.fingerprint,
        reservation.quote.provider_id,
        reservation.attempt_id,
    ):
        raise ValueError("provider receipt does not match reservation/quote/attempt")


def _reservations(value: Any) -> tuple[Reservation, ...]:
    return _tuple(value, Reservation.from_dict)


@dataclass(frozen=True)
class MinuteAccount(Snapshot):
    tenant_id: str
    account_id: str
    grants: tuple[MinuteGrant, ...] = ()
    reservations: tuple[Reservation, ...] = ()

    _decoders: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "grants": lambda value: _tuple(value, MinuteGrant.from_dict),
        "reservations": _reservations,
    }

    def __post_init__(self) -> None:
        _strings(self, ("tenant_id", "account_id"))
        if type(self.grants) is not tuple or type(self.reservations) is not tuple:
            raise ValueError("account history must be immutable tuples")
        if any(not isinstance(grant, MinuteGrant) for grant in self.grants):
            raise ValueError("invalid typed minute grant")
        if len({grant.grant_id for grant in self.grants}) != len(self.grants):
            raise ValueError("duplicate minute grant")
        if any(
            (grant.tenant_id, grant.account_id) != (self.tenant_id, self.account_id)
            for grant in self.grants
        ):
            raise ValueError("cross-tenant/account grant")
        _validate_reservations(self.reservations)
        if any(
            (r.quote.source.tenant_id, r.quote.account_id) != (self.tenant_id, self.account_id)
            for r in self.reservations
        ):
            raise ValueError("cross-tenant/account minute reservation")
        observed_excess = sum(
            max(0, r.committed_seconds - r.quote.entitlement_seconds)
            for r in self.reservations
            if r.state == "reconciliation_required"
        )
        if self.available_seconds + observed_excess < 0:
            raise ValueError("minute snapshot overdraws explicit grants")

    @property
    def available_seconds(self) -> int:
        return sum(grant.seconds for grant in self.grants) - sum(
            reservation.committed_seconds for reservation in self.reservations
        )

    @property
    def has_overrun(self) -> bool:
        return any(r.state == "reconciliation_required" for r in self.reservations)


@dataclass(frozen=True)
class BudgetAccount(Snapshot):
    scope_id: str
    cap_paise: int
    cap_approval: BudgetCapApproval
    reservations: tuple[Reservation, ...] = ()

    _decoders: ClassVar[dict[str, Callable[[Any], Any]]] = {
        "cap_approval": BudgetCapApproval.from_dict,
        "reservations": _reservations,
    }

    def __post_init__(self) -> None:
        require_text(self.scope_id, "budget scope id")
        _integer(self.cap_paise, "cap paise")
        if not isinstance(self.cap_approval, BudgetCapApproval):
            raise ValueError("explicit budget cap approval required")
        if (self.cap_approval.scope_id, self.cap_approval.approved_cap_paise) != (
            self.scope_id,
            self.cap_paise,
        ):
            raise ValueError("cap approval does not match budget")
        _validate_reservations(self.reservations)
        if any(r.quote.budget_scope_id != self.scope_id for r in self.reservations):
            raise ValueError("reservation belongs to another budget scope")
        observed_excess = sum(
            max(0, r.committed_paise - r.quote.max_cost_paise)
            for r in self.reservations
            if r.state == "reconciliation_required"
        )
        if self.available_paise + observed_excess < 0:
            raise ValueError("budget snapshot overdraws approved cap")

    @property
    def available_paise(self) -> int:
        return self.cap_paise - sum(r.committed_paise for r in self.reservations)

    @property
    def has_overrun(self) -> bool:
        return any(r.state == "reconciliation_required" for r in self.reservations)


def _validate_reservations(reservations: tuple[Reservation, ...]) -> None:
    if type(reservations) is not tuple or any(not isinstance(r, Reservation) for r in reservations):
        raise ValueError("reservation history must be immutable typed tuples")
    if len({r.reservation_id for r in reservations}) != len(reservations):
        raise ValueError("duplicate reservation id")
    if len({(r.quote.source.tenant_id, r.quote.quote_id) for r in reservations}) != len(
        reservations
    ):
        raise ValueError("quote already reserved; reuse its original reservation id")


@dataclass(frozen=True)
class LedgerTransition:
    minutes: MinuteAccount
    budget: BudgetAccount
    reservation: Reservation
    changed: bool


def metered_seconds(duration_ms: int) -> int:
    """Round a supplied media duration once; caller chooses whether this operation is billable."""
    return (_integer(duration_ms, "duration_ms", 1) + 999) // 1000


def grant_minutes(account: MinuteAccount, grant: MinuteGrant) -> MinuteAccount:
    if (grant.tenant_id, grant.account_id) != (account.tenant_id, account.account_id):
        raise ValueError("cross-tenant/account grant")
    existing = next((g for g in account.grants if g.grant_id == grant.grant_id), None)
    if existing is not None:
        if existing != grant:
            raise ValueError("immutable grant idempotency conflict")
        return account
    return replace(account, grants=(*account.grants, grant))


def revise_budget_cap(
    budget: BudgetAccount, new_cap_paise: int, approval: BudgetCapApproval
) -> BudgetAccount:
    _integer(new_cap_paise, "new cap paise")
    if approval == budget.cap_approval and new_cap_paise == budget.cap_paise:
        return budget
    if approval.approval_ref == budget.cap_approval.approval_ref:
        raise ValueError("cap revision requires a new explicit owner approval")
    if approval.previous_budget_fingerprint != budget.fingerprint:
        raise ValueError("cap approval must bind current budget snapshot")
    if approval.approved_cap_paise != new_cap_paise or approval.scope_id != budget.scope_id:
        raise ValueError("cap approval must bind exact scope and amount")
    if new_cap_paise < budget.cap_paise - budget.available_paise:
        raise ValueError("cannot reduce cap below spent and held commitments")
    return replace(budget, cap_paise=new_cap_paise, cap_approval=approval)


def _pair(minutes: MinuteAccount, budget: BudgetAccount, reservation_id: str) -> Reservation | None:
    require_text(reservation_id, "reservation id")
    # A shared project budget legitimately contains other users' reservations.
    expected = {
        r.reservation_id: r
        for r in budget.reservations
        if (r.quote.source.tenant_id, r.quote.account_id) == (minutes.tenant_id, minutes.account_id)
    }
    actual = {
        r.reservation_id: r
        for r in minutes.reservations
        if r.quote.budget_scope_id == budget.scope_id
    }
    if expected != actual:
        raise ValueError("paired minute/budget snapshots diverged; reload under both locks")
    found = next((r for r in budget.reservations if r.reservation_id == reservation_id), None)
    if found is not None and found.reservation_id not in actual:
        raise ValueError("reservation belongs to another tenant/account")
    return found


def _replace_pair(
    minutes: MinuteAccount, budget: BudgetAccount, reservation: Reservation
) -> LedgerTransition:
    def updated(rows: tuple[Reservation, ...]) -> tuple[Reservation, ...]:
        return tuple(
            reservation if r.reservation_id == reservation.reservation_id else r for r in rows
        )

    return LedgerTransition(
        replace(minutes, reservations=updated(minutes.reservations)),
        replace(budget, reservations=updated(budget.reservations)),
        reservation,
        True,
    )


def _live_permission(quote: Quote, permission: ExecutionPermission, now_epoch: int) -> None:
    _integer(now_epoch, "now epoch")
    if permission.quote_fingerprint != quote.fingerprint:
        raise ValueError("exact quote-specific execution permission required")
    if (
        not quote.created_at_epoch
        <= now_epoch
        < min(quote.expires_at_epoch, permission.expires_at_epoch)
    ):
        raise ValueError("quote or recording/provider/privacy permission expired or not yet valid")


def reserve(
    minutes: MinuteAccount,
    budget: BudgetAccount,
    reservation_id: str,
    quote: Quote,
    permission: ExecutionPermission,
    now_epoch: int,
) -> LedgerTransition:
    existing = _pair(minutes, budget, reservation_id)
    if existing is not None:
        if existing.quote != quote or existing.permission != permission:
            raise ValueError("reservation idempotency conflict")
        return LedgerTransition(minutes, budget, existing, False)
    if any(
        (r.quote.source.tenant_id, r.quote.quote_id) == (quote.source.tenant_id, quote.quote_id)
        for r in budget.reservations
    ):
        raise ValueError("quote already reserved; reuse its original reservation id")
    if (quote.source.tenant_id, quote.account_id, quote.budget_scope_id) != (
        minutes.tenant_id,
        minutes.account_id,
        budget.scope_id,
    ):
        raise ValueError("quote tenant/account/budget mismatch")
    _live_permission(quote, permission, now_epoch)
    if minutes.has_overrun or budget.has_overrun:
        raise ValueError("unresolved overrun holds further execution")
    if quote.entitlement_seconds > minutes.available_seconds:
        raise ValueError("insufficient explicit minute grant")
    if quote.max_cost_paise > budget.available_paise:
        raise ValueError("shared project budget exhausted")
    reservation = Reservation(reservation_id, quote, permission)
    return LedgerTransition(
        replace(minutes, reservations=(*minutes.reservations, reservation)),
        replace(budget, reservations=(*budget.reservations, reservation)),
        reservation,
        True,
    )


def _existing(minutes: MinuteAccount, budget: BudgetAccount, reservation_id: str) -> Reservation:
    reservation = _pair(minutes, budget, reservation_id)
    if reservation is None:
        raise ValueError("unknown reservation")
    return reservation


def mark_dispatched(
    minutes: MinuteAccount,
    budget: BudgetAccount,
    reservation_id: str,
    attempt_id: str,
    now_epoch: int,
) -> LedgerTransition:
    reservation = _existing(minutes, budget, reservation_id)
    require_text(attempt_id, "attempt id")
    if reservation.state != "reserved":
        if reservation.attempt_id == attempt_id and reservation.state in {"in_flight", "uncertain"}:
            return LedgerTransition(minutes, budget, reservation, False)
        raise ValueError("reservation cannot dispatch a second provider attempt")
    _live_permission(reservation.quote, reservation.permission, now_epoch)
    if minutes.has_overrun or budget.has_overrun:
        raise ValueError("unresolved overrun holds further execution")
    return _replace_pair(
        minutes, budget, replace(reservation, state="in_flight", attempt_id=attempt_id)
    )


def mark_uncertain(
    minutes: MinuteAccount, budget: BudgetAccount, reservation_id: str, evidence_ref: str
) -> LedgerTransition:
    reservation = _existing(minutes, budget, reservation_id)
    require_text(evidence_ref, "uncertain outcome evidence ref")
    if reservation.state == "uncertain" and reservation.uncertainty_ref == evidence_ref:
        return LedgerTransition(minutes, budget, reservation, False)
    if reservation.state != "in_flight":
        raise ValueError("only an in-flight attempt can enter uncertain-outcome hold")
    return _replace_pair(
        minutes, budget, replace(reservation, state="uncertain", uncertainty_ref=evidence_ref)
    )


def settle(
    minutes: MinuteAccount, budget: BudgetAccount, reservation_id: str, receipt: SettlementReceipt
) -> LedgerTransition:
    reservation = _existing(minutes, budget, reservation_id)
    _match_receipt(reservation, receipt)
    if reservation.state in {"settled", "reconciliation_required"}:
        if reservation.settlement != receipt:
            raise ValueError("immutable settlement conflict")
        return LedgerTransition(minutes, budget, reservation, False)
    if reservation.state not in {"in_flight", "uncertain"}:
        raise ValueError("settlement requires a dispatched attempt")
    overrun = receipt.actual_seconds > reservation.quote.entitlement_seconds or (
        receipt.actual_paise > reservation.quote.max_cost_paise
    )
    return _replace_pair(
        minutes,
        budget,
        replace(
            reservation,
            state="reconciliation_required" if overrun else "settled",
            settlement=receipt,
        ),
    )


def release(
    minutes: MinuteAccount,
    budget: BudgetAccount,
    reservation_id: str,
    reason_ref: str,
    no_charge_receipt: NoChargeReceipt | None = None,
) -> LedgerTransition:
    reservation = _existing(minutes, budget, reservation_id)
    require_text(reason_ref, "release reason ref")
    if reservation.state == "released":
        if (reservation.release_reason_ref, reservation.no_charge_receipt) != (
            reason_ref,
            no_charge_receipt,
        ):
            raise ValueError("immutable release idempotency conflict")
        return LedgerTransition(minutes, budget, reservation, False)
    if reservation.state in {"settled", "reconciliation_required"}:
        raise ValueError("cannot release settled spend or unresolved overrun")
    if reservation.state in {"in_flight", "uncertain"} and no_charge_receipt is None:
        raise ValueError(
            "unknown provider outcome remains reserved pending no-charge reconciliation"
        )
    if no_charge_receipt is not None:
        _match_receipt(reservation, no_charge_receipt)
    return _replace_pair(
        minutes,
        budget,
        replace(
            reservation,
            state="released",
            release_reason_ref=reason_ref,
            no_charge_receipt=no_charge_receipt,
        ),
    )
