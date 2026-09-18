from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from ac_platform.application.settings import Settings
from ac_platform.http.auth import _learner_oauth_recovery_response
from ac_platform.http.auth_transactions import AuthTransaction, AuthTransactionCodec
from ac_platform.identity.services import ProviderAuthorizationType

SALES_RETURN_PATH = "/onboarding?next=/sales-xray"
TRANSACTION_SECRET = "test-oauth-transaction-secret-long-enough"  # noqa: S105


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret=TRANSACTION_SECRET,
        email_challenge_secret="test-email-challenge-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def test_signed_sales_return_path_is_reduced_to_the_exact_callback_hint() -> None:
    transaction = AuthTransaction.issue(
        ProviderAuthorizationType.AUTHENTICATE,
        surface="learner",
        return_path=SALES_RETURN_PATH,
    )
    decoded = AuthTransactionCodec(TRANSACTION_SECRET).decode(
        AuthTransactionCodec(TRANSACTION_SECRET).encode(transaction)
    )

    response = _learner_oauth_recovery_response(
        _settings(),
        result="registration_required",
        transaction_cookie_names=("ac_oauth_transaction",),
        transaction_return_path=decoded.return_path,
    )

    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "result": ["registration_required"],
        "next": ["/sales-xray"],
    }


@pytest.mark.parametrize(
    "return_path",
    [
        "/onboarding?next=%2Fsales-xray",
        "/onboarding?next=/sales-xray&course=authority-closers-free-course",
        "/onboarding?next=/other",
        "/onboarding?return_url=https://evil.example",
    ],
)
def test_oauth_recovery_does_not_forward_unmatched_return_path(
    return_path: str,
) -> None:
    response = _learner_oauth_recovery_response(
        _settings(),
        result="provider_rejected",
        transaction_cookie_names=("ac_oauth_transaction",),
        transaction_return_path=return_path,
    )

    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "result": ["provider_rejected"]
    }
