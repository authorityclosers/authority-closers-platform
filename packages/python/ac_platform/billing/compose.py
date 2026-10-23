"""Compose the billing application from settings (ADR 0052; provider keys via Infisical).

Nothing is composed unless ``AC_BILLING_ENABLED`` is on. The Razorpay adapter
needs its key pair and webhook secret; the fake provider is forbidden in
production and needs its own signing key. The catalogue is the ``plans``
table: only an ``active`` row with a price sells, so every ``coming_soon``
plan stays "not on sale" until its activation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ac_platform.application.settings import Settings
from ac_platform.billing.application import BillingApplication
from ac_platform.billing.catalogue import Catalogue, PlansTableCatalogue
from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.trial import TrialPolicy
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import PaymentMode, PaymentProvider
from ac_platform.payments.razorpay import RazorpayAdapter
from ac_platform.payments.registry import PaymentProviderRegistry


def compose_billing(
    settings: Settings, *, catalogue: Catalogue | None = None
) -> BillingApplication | None:
    if not settings.billing_enabled:
        return None
    public_tenant, operations_tenant = (
        settings.public_learner_tenant_id,
        settings.operations_tenant_id,
    )
    if public_tenant is None or operations_tenant is None or settings.sales_xray_app_url is None:
        raise ValueError("billing composition needs the tenants and the Sales Xray origin")
    providers: list[PaymentProvider] = []
    if settings.billing_fake_provider_signing_key is not None:
        providers.append(
            FakePaymentProvider(
                signing_key=settings.billing_fake_provider_signing_key.get_secret_value()
            )
        )
    if (
        settings.razorpay_key_id is not None
        and settings.razorpay_key_secret is not None
        and settings.razorpay_webhook_secret is not None
    ):
        mode = PaymentMode.LIVE if settings.billing_allow_live else PaymentMode.TEST
        providers.append(
            RazorpayAdapter(
                key_id=settings.razorpay_key_id,
                key_secret=settings.razorpay_key_secret.get_secret_value(),
                webhook_secret=settings.razorpay_webhook_secret.get_secret_value(),
                mode=mode,
            )
        )
    registry = PaymentProviderRegistry(providers, allow_live=settings.billing_allow_live)
    # The test payment page needs an origin a browser can reach. Dev serves /v1
    # behind the Sales Xray origin, and its own API URL is a plain loopback one.
    fake_checkout_base_url = str(settings.api_url).rstrip("/")
    if not fake_checkout_base_url.startswith("https://"):
        fake_checkout_base_url = str(settings.sales_xray_app_url).rstrip("/")
    service = CheckoutService(
        catalogue=catalogue or PlansTableCatalogue(),
        providers=registry,
        public_learner_tenant_id=public_tenant,
        operations_tenant_id=operations_tenant,
        return_url_base=str(settings.sales_xray_app_url).rstrip("/"),
        fake_checkout_base_url=fake_checkout_base_url,
        trial_policy=TrialPolicy(
            settings.sales_xray_trial_policy, settings.sales_xray_trial_policy_switch_at
        ),
        clock=lambda: datetime.now(UTC),
        invoice_settings=settings,
    )
    return BillingApplication(service)


__all__ = ["compose_billing"]
