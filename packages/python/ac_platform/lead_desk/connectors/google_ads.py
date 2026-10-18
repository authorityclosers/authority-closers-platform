"""Google Ads lead form webhooks, read into the CRM's flexible lead record.

Google posts one JSON object per lead to the address and key pasted into a lead
form (Google Ads: the lead form asset, "Export leads from Google Ads", webhook):

    {"lead_id": "...", "api_version": "1.0", "form_id": 1, "campaign_id": 2,
     "adgroup_id": 3, "creative_id": 4, "gcl_id": "...", "google_key": "...",
     "is_test": true, "lead_submit_time": "...",
     "user_column_data": [{"column_id": "FULL_NAME", "column_name": "Full Name",
                           "string_value": "Asha Rao"}, ...]}

Every answer is kept. Google's standard columns get the names the desk's
extractor already reads (full_name, phone_number, email, city, company_name);
a custom question keeps its own question text. The lead's reference stays at the
top as ``lead_id`` (see ``reference``), so a lead Google sends twice, or that the
connector's pull also reads, is recognised and not added again.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

MAX_COLUMNS: Final[int] = 100
MAX_VALUE: Final[int] = 2000
LABEL: Final[str] = "Google Ads lead form"

# Google's standard lead form columns and the field names the desk reads.
STANDARD: Final[dict[str, str]] = {
    "FULL_NAME": "full_name",
    "FIRST_NAME": "first_name",
    "LAST_NAME": "last_name",
    "EMAIL": "email",
    "WORK_EMAIL": "work_email",
    "PHONE_NUMBER": "phone_number",
    "WORK_PHONE": "work_phone",
    "POSTAL_CODE": "postal_code",
    "STREET_ADDRESS": "street_address",
    "CITY": "city",
    "REGION": "region",
    "COUNTRY": "country",
    "COMPANY_NAME": "company_name",
    "JOB_TITLE": "job_title",
}
_DETAILS: Final[tuple[str, ...]] = (
    "form_id",
    "campaign_id",
    "adgroup_id",
    "creative_id",
    "gcl_id",
    "api_version",
    "is_test",
    "lead_submit_time",
)


class GoogleAdsError(ValueError):
    """The body is not a usable Google Ads lead form webhook."""


def google_key(payload: Mapping[str, Any]) -> str:
    """The key Google sends with every lead: the CRM source's own key."""
    value = payload.get("google_key")
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise GoogleAdsError("Paste the key from Sales Xray into the lead form's Key box.")
    return value.strip()


def reference(payload: Mapping[str, Any]) -> str | None:
    """The lead's reference: Google's click id when there is one, else its lead id.

    The webhook's ``lead_id`` and the API's submission id are not documented to be
    the same, but both carry the click id, so a lead that arrives by webhook and by
    the connector's pull is filed once.
    """
    for name, prefix in (("gcl_id", "gclid:"), ("lead_id", "")):
        value = payload.get(name)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            return f"{prefix}{str(value).strip()}"[:200]
    return None


def to_record(payload: Mapping[str, Any]) -> dict[str, Any]:
    """One lead record: every answer, Google's ids, and nothing else."""
    columns = payload.get("user_column_data")
    if not isinstance(columns, list) or not columns:
        raise GoogleAdsError("Google Ads sent a lead with no answers.")
    record: dict[str, Any] = {}
    for column in columns[:MAX_COLUMNS]:
        if not isinstance(column, Mapping):
            continue
        value = column.get("string_value")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        column_id = str(column.get("column_id") or "").strip()
        question = str(column.get("column_name") or "").strip()
        name = STANDARD.get(column_id.upper()) or question or column_id
        if not name:
            continue
        record.setdefault(name[:120], str(value)[:MAX_VALUE])
    if not record:
        raise GoogleAdsError("Google Ads sent a lead with no answers.")
    ref = reference(payload)
    if ref:
        record["lead_id"] = ref
    details = {
        name: payload[name]
        for name in _DETAILS
        if isinstance(payload.get(name), (str, int, bool)) and str(payload[name]).strip()
    }
    lead_id = payload.get("lead_id")
    if isinstance(lead_id, (str, int)) and str(lead_id).strip():
        details["lead_id"] = str(lead_id).strip()[:200]
    if details:
        record["google_ads"] = details
    record["lead_source"] = LABEL
    return record
