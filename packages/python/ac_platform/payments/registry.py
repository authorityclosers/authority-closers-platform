"""Registry of configured payment providers, fail-closed on live mode."""

from __future__ import annotations

from collections.abc import Iterable

from ac_platform.payments.ports import PaymentMode, PaymentProvider, require_provider_name


class UnknownPaymentProviderError(LookupError):
    """No provider is registered under that name."""


class PaymentProviderRegistry:
    """Providers by name. Which one serves an order is a settings decision.

    A live-mode adapter is refused unless the caller passes ``allow_live=True``.
    That flag must come only from the owner's go-live setting.
    """

    def __init__(
        self, providers: Iterable[PaymentProvider] = (), *, allow_live: bool = False
    ) -> None:
        self._allow_live = allow_live
        self._providers: dict[str, PaymentProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: PaymentProvider) -> None:
        name = require_provider_name(provider.name)
        if name in self._providers:
            raise ValueError(f"payment provider {name} is already registered")
        if provider.mode is not PaymentMode.TEST and not self._allow_live:
            raise ValueError(f"payment provider {name} is in live mode, which is not allowed here")
        self._providers[name] = provider

    def get(self, name: str) -> PaymentProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise UnknownPaymentProviderError("payment provider is not registered") from None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


__all__ = ["PaymentProviderRegistry", "UnknownPaymentProviderError"]
