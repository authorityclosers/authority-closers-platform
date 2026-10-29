"""The website line's reading of what a page sends (lead_desk/websites.py): hosts, pages,
where a visit came from, which answers are kept, and when a form fill is a bot's."""

from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.http.rate_limits import DEFAULT_RATE_LIMIT_RULES
from ac_platform.lead_desk import websites
from ac_platform.lead_desk.capture import extract
from ac_platform.lead_desk.journey.providers import click_ids
from ac_platform.lead_desk.store import DeskError

AT = datetime(2026, 10, 30, 10, 42, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "host"),
    [
        (
            "https://www.Fictional-Homes.example.com/contact?utm_source=x",
            "fictional-homes.example.com",
        ),
        ("fictionalclinic.in", "fictionalclinic.in"),
        ("http://shop.fictional.in:8080/", "shop.fictional.in"),
        ("https://localhost:3000/", "localhost"),
        ("", None),
        ("not a site", None),
        ("https://[::1]/", None),
        ("javascript:alert(1)", None),
        ("intranet", None),
        ("mailto:asha@fictional.example.com", None),
    ],
)
def test_a_site_is_its_host_without_www_or_port(raw: str, host: str | None) -> None:
    assert websites.normalise_host(raw) == host


def test_a_computers_own_address_and_test_names_are_test_sites() -> None:
    for host in ("localhost", "site.localhost", "demo.test", "127.0.0.1", "box.local"):
        assert websites.is_test_host(host)
    for host in ("fictionalclinic.in", "fictional.webflow.io", "fictional.framer.website"):
        assert not websites.is_test_host(host)


def test_a_page_is_its_path_without_query_or_trailing_slash() -> None:
    assert websites.page_path("https://x.in/offer/?utm_source=a#form") == "/offer"
    assert websites.page_path("https://x.in") == "/"
    assert websites.page_path("https://x.in//a//b/") == "/a/b"
    assert websites.page_address("https://x.in/offer/?gclid=abc") == "https://x.in/offer/"
    assert websites.page_address("ftp://x.in/") is None


def test_the_page_must_be_the_one_the_browser_sends_from() -> None:
    body = {"k": "sxw_" + "a" * 32, "u": "https://www.fictionalclinic.in/book"}
    visit = websites.read_visit(body, "https://fictionalclinic.in")
    assert (visit.host, visit.path) == ("fictionalclinic.in", "/book")
    with pytest.raises(DeskError) as other:
        websites.read_visit(body, "https://someone-else.example.com")
    assert other.value.status == 403
    with pytest.raises(DeskError) as missing:
        websites.read_visit(body, None)
    assert missing.value.status == 403
    with pytest.raises(DeskError) as no_key:
        websites.read_visit({**body, "k": "not-a-key"}, "https://fictionalclinic.in")
    assert no_key.value.status == 401


def test_where_the_visit_came_from_keeps_only_well_formed_tags_and_ids() -> None:
    raw = {
        "last": {
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "Diwali offer",
            "gclid": "Cj0KCQjw-fictional_click.id",
            "fbclid": "bad value with spaces",
            "fbc": "fb.1.1730280000000.IwAR-fictional",
            "fbp": "fb.1.1730280000000.1234567890",
            "referrer": "https://www.google.com/search?q=fictional",
            "landing_url": "https://fictionalclinic.in/offer?utm_source=google",
            "evil": "<script>",
            "at": 1730280000000,
        },
        "first": {"utm_source": "newsletter", "at": 1729000000000},
    }
    found = websites.clean_attribution(raw, page="https://fictionalclinic.in/book", title="Book")
    assert found["utm_campaign"] == "Diwali offer"
    assert found["gclid"] == "Cj0KCQjw-fictional_click.id"
    assert "evil" not in found
    # A malformed fbclid is dropped; Meta's cookie gives the click id instead.
    assert found["fbclid"] == "IwAR-fictional"
    assert found["referrer"] == "https://www.google.com/search"
    assert found["landing_url"] == "https://fictionalclinic.in/offer"
    assert found["page_url"] == "https://fictionalclinic.in/book"
    assert found["first_touch"]["utm_source"] == "newsletter"
    # The ad platforms' stage senders read the same ids from the lead's record.
    assert click_ids({"attribution": found}) == {
        "gclid": "Cj0KCQjw-fictional_click.id",
        "fbclid": "IwAR-fictional",
    }


@pytest.mark.parametrize(
    ("attribution", "line"),
    [
        ({"gclid": "abcdefgh", "utm_campaign": "Diwali"}, "Google Ads · Diwali"),
        ({"fbclid": "abcdefgh"}, "Facebook / Instagram ad"),
        ({"utm_source": "instagram", "utm_medium": "social"}, "Instagram"),
        ({"utm_source": "newsletter"}, "Newsletter"),
        ({"referrer": "https://www.google.com/search"}, "Google search"),
        ({"referrer": "https://fictionalclinic.in/other"}, "Direct visit"),
        ({}, "Direct visit"),
    ],
)
def test_came_from_is_one_plain_line(attribution: dict[str, str], line: str) -> None:
    assert websites.came_from(attribution, "fictionalclinic.in") == line


def test_secrets_payment_details_and_plumbing_never_stay() -> None:
    fields = websites.clean_fields(
        [
            {"k": "Full name", "v": "Asha Fictional", "r": "name"},
            {"k": "Password", "v": "hunter2"},
            {"k": "Card number", "v": "4111 1111 1111 1111"},
            {"k": "Notes", "v": "4111111111111111"},  # a card number by its shape
            {"k": "OTP", "v": "123456"},
            {"k": "_wpnonce", "v": "abc"},
            {"k": "g-recaptcha-response", "v": "x" * 50},
            {"k": "post_id", "v": "12"},
            {"k": "Mobile", "v": "98765 43210", "r": "phone"},
            {"k": "Mobile", "v": "91234 56780"},
            {"k": "Empty", "v": "   "},
            {"k": "Odd role", "v": "x", "r": "password"},
        ]
    )
    assert [(f.label, f.value, f.role) for f in fields] == [
        ("Full name", "Asha Fictional", "name"),
        ("Mobile", "98765 43210", "phone"),
        ("Mobile (2)", "91234 56780", None),
        ("Odd role", "x", None),
    ]


def test_the_record_keeps_answers_on_top_and_tags_apart() -> None:
    fields = websites.clean_fields(
        [
            {"k": "First name", "v": "Ravi", "r": "first_name"},
            {"k": "Last name", "v": "Example", "r": "last_name"},
            {"k": "Your WhatsApp", "v": "098765 43210", "r": "phone"},
            {"k": "Budget", "v": "5 lakh"},
        ]
    )
    record, mapping = websites.record_of(
        fields,
        attribution={"gclid": "abcdefgh", "page_url": "https://x.in/offer"},
        website={"host": "x.in", "path": "/offer", "form": "Offer"},
        host="x.in",
    )
    assert mapping == {"phone": "Your WhatsApp", "name": "Full name"}
    assert record["Full name"] == "Ravi Example"
    assert record["Page"] == "https://x.in/offer"
    assert record["Came from"] == "Google Ads"
    assert record["attribution"]["gclid"] == "abcdefgh"
    found = extract(record, mapping)
    assert (found.name, found.phone) == ("Ravi Example", "+919876543210")


def test_contact_comes_from_marked_fields_first_then_any_answer_shaped_so() -> None:
    marked = websites.clean_fields(
        [{"k": "Ref", "v": "98765 00000"}, {"k": "Phone", "v": "91234 56780", "r": "phone"}]
    )
    found = websites.contact_of(marked, "91")
    assert (found.phone, found.email, found.phone_label) == ("+919123456780", None, "Phone")
    unmarked = websites.clean_fields([{"k": "Reach me", "v": "Asha@Fictional.example.com"}])
    found = websites.contact_of(unmarked, "91")
    assert (found.phone, found.email, found.email_label) == (
        None,
        "asha@fictional.example.com",
        "Reach me",
    )
    # A marked phone that isn't one: the lead takes the answer that is.
    odd = websites.clean_fields(
        [{"k": "Phone", "v": "call me", "r": "phone"}, {"k": "Mobile", "v": "98765 43210"}]
    )
    assert websites.contact_of(odd, "91").phone_label == "Mobile"


def test_bots_are_told_apart_from_people() -> None:
    person = websites.clean_fields([{"k": "Name", "v": "Asha", "r": "name"}])
    assert websites.bot_reason(person, webdriver=False, interactions=12, elapsed_ms=900) is None
    assert websites.bot_reason(person, webdriver=False, interactions=0, elapsed_ms=8000) is None
    assert websites.bot_reason(person, webdriver=True, interactions=9, elapsed_ms=9000) == (
        "headless"
    )
    assert websites.bot_reason(
        person, webdriver=False, interactions=9, elapsed_ms=9000, trap=True
    ) == ("honeypot")
    assert websites.bot_reason(person, webdriver=False, interactions=0, elapsed_ms=400) == (
        "too_fast"
    )
    linked = websites.clean_fields(
        [{"k": "Name", "v": "cheap pills http://x.example", "r": "name"}]
    )
    assert websites.bot_reason(linked, webdriver=False, interactions=5, elapsed_ms=9000) == (
        "link_in_name"
    )


def test_the_same_person_sending_again_soon_is_the_same_reference() -> None:
    first = websites.resend_ref("x.in", "+919876543210", None, AT)
    assert websites.resend_ref("x.in", "+919876543210", None, AT.replace(minute=50)) == first
    assert websites.resend_ref("y.in", "+919876543210", None, AT) != first
    assert websites.resend_ref("x.in", None, "a@x.in", AT) != first
    assert len(first) <= 200


def test_each_site_may_send_only_so_many_leads_a_window() -> None:
    now = [0.0]
    limiter = websites.SiteLimiter(clock=lambda: now[0])
    allowed = [limiter.allow("t:x.in") for _ in range(websites.SITE_LEADS_PER_WINDOW + 1)]
    assert allowed.count(True) == websites.SITE_LEADS_PER_WINDOW and allowed[-1] is False
    assert limiter.allow("t:y.in")
    now[0] += websites.SITE_WINDOW.total_seconds() + 1
    assert limiter.allow("t:x.in")


def test_the_key_and_line() -> None:
    key = websites.new_key()
    assert websites.KEY_PATTERN.fullmatch(key)
    assert websites.snippet("https://sx.example/sx.js", key) == (
        f'<script src="https://sx.example/sx.js" data-key="{key}" async></script>'
    )


def test_each_address_may_send_only_a_few() -> None:
    rules = {rule.name: rule for rule in DEFAULT_RATE_LIMIT_RULES}
    assert rules["website-lead"].path.fullmatch("/v1/lead-desk/site/lead")
    assert (rules["website-lead"].capacity, rules["website-lead"].refill_seconds) == (8, 600)
    assert rules["website-hello"].path.fullmatch("/v1/lead-desk/site/hello")


def test_numbers_with_a_country_code_are_never_taken_for_cards() -> None:
    # Both pass the card check (Luhn) when read as digits.
    fields = websites.clean_fields(
        [
            {"k": "Phone", "v": "0091 98765 43217", "r": "phone"},
            {"k": "Other number", "v": "0971 50 123 4563"},
            {"k": "Notes", "v": "4111 1111 1111 1111"},
        ]
    )
    assert [field.label for field in fields] == ["Phone", "Other number"]


def test_hostile_answers_never_break_the_record() -> None:
    fields = websites.clean_fields(
        [
            {"k": "Name", "v": "Asha\x00 Fictional", "r": []},
            {"k": "Odd\ud800", "v": "x"},
            {"k": ["not", "text"], "v": "y"},
            {"k": "Count", "v": 3},
            {"k": "Flag", "v": True},
        ]
    )
    assert [(f.label, f.value, f.role) for f in fields] == [
        ("Name", "Asha Fictional", None),
        ("Odd", "x", None),
        ("Count", "3", None),
    ]
    assert websites.page_path("https://x.in/a\x00b") == "/ab"


def test_a_lead_sent_again_counts_from_when_it_was_first_sent() -> None:
    first = int(AT.timestamp() * 1000)
    later = AT + timedelta(hours=6)
    assert websites.sent_at(first, later) == AT
    assert websites.resend_ref("x.in", "+919876543210", None, websites.sent_at(first, later)) == (
        websites.resend_ref("x.in", "+919876543210", None, AT)
    )
    # Older than a day, in the future, or not a time: now.
    assert websites.sent_at(int((AT - timedelta(days=2)).timestamp() * 1000), AT) == AT
    assert websites.sent_at(int((AT + timedelta(hours=1)).timestamp() * 1000), AT) == AT
    assert websites.sent_at("yesterday", AT) == AT
    assert websites.sent_at(10**30, AT) == AT
