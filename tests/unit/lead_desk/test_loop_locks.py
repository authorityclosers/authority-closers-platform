"""Each Lead Desk background loop has its own advisory lock pair (19 Oct 2026: the review
sender and the Google Ads puller shared one, then the WhatsApp runner and the review
sender did, so two loops skipped each other's ticks)."""

from ac_platform.lead_desk import push, review_push
from ac_platform.lead_desk.connectors import google_pull, meta_capi, meta_spend
from ac_platform.lead_desk.social import runner as social_runner
from ac_platform.lead_desk.whatsapp import runner


def test_every_lead_desk_loop_has_its_own_lock() -> None:
    locks = {
        "push sender": push._LOCK,
        "work-hours release": push._HOURS_LOCK,
        "review sender": review_push._LOCK,
        "google ads puller": google_pull._LOCK,
        "meta conversions sender": meta_capi._LOCK,
        "whatsapp and sla runner": runner._LOCK,
        "messenger and instagram runner": social_runner._LOCK,
        "meta ad spend reader": meta_spend._LOCK,
    }
    pairs = list(locks.values())
    assert len(set(pairs)) == len(pairs), locks
    assert all(pair[0] == 1802 for pair in pairs)
