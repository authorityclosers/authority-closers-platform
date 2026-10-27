# WhatsApp on AC's own number (the company number)

**The owner's go, 27 Oct 2026:** "WhatsApp for AC's org now on the same number". Leads see one company number for
calls and chats.

## Why no App Review is needed

AC uses its own Meta app, Sales Xray Messaging, with its own WhatsApp Business Account. That makes it a **direct
developer**. Meta's webhooks page says the business's system user grants the app `whatsapp_business_messaging` and
`whatsapp_business_management` when it makes the token. App Review (advanced access) is only for **other businesses'**
numbers, which is the customers' route, Embedded Signup.

**The one risk:** the app is in Development mode, and Meta says "some webhooks will not be sent if your app is in Dev
mode". Sending works either way. The question is whether replies and ticks reach us. The first-day check below
answers it.

## Steps

1. **Owner** (owner steps, item 4):
   - add the company number in WhatsApp Manager;
   - display name **Sales X-Ray**;
   - verify by voice call, with the ExoPhone routed to the owner's mobile for that minute;
   - add a card to the WhatsApp account.
2. **Token:** a system user of the Authority Closers business, with the WhatsApp account and the Messaging app
   assigned, and the two WhatsApp permissions. The owner copies it, then runs
   `ac-secret.ps1 AC_WHATSAPP_OWN_SYSTEM_TOKEN <env> -SkipServer`. It's read only by the script below, inside
   `infisical run`.
3. **Connect:** `scripts/data-changes/lead-desk-whatsapp-own-number.py`. It's an owner-approved data change:
   - dry run first, then `--apply`;
   - in production, `--snapshot` with the snapshot taken first;
   - it subscribes the account, registers the number with a sealed PIN, keeps the number for AC's organisation, and
     brings in its templates.
4. **Production only:** the production verify token (`AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN`), held back until now, is set,
   and the production webhook is subscribed (`~/.ac/bin/ac-meta-webhooks.ps1 prod`), as part of a release. Customers
   still can't connect: Embedded Signup waits for Meta's review.
5. **First-day check:**
   1. From Sales X-Ray, send an approved template to a team phone.
   2. Reply "Hi" from that phone.
   3. Run `scripts/ops/whatsapp-day-one-check.py --org <AC's tenant id> --since <start time>`. In production, use
      `--sql` and the logged read path (`~/costq/q.sh`).
   4. It prints PASS or FAIL for `messages` (the reply arrived), `statuses` (ticks), and `templates` (reviews).

## If webhooks don't arrive

Try these in order:

1. **A small Meta app of AC's own, published Live.**
   - It holds only AC's own WhatsApp account, with only the WhatsApp use case, and its own webhook.
   - Its own assets need no review. A Live app gets every webhook.
   - Connect the number to that app with the same script; the app id and secret come in as their own settings.
2. **A WhatsApp partner for AC's own number.** For example, Exotel's WhatsApp API, which adds about ₹0.06 a message
   to Meta's price. The inbox would read from the partner's webhook. This is more work, so it's second.

## Meta's prices (India, per delivered message, before 18% GST; never shown in the app)

| Category                   | Price                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------- |
| Marketing                  | ≈ ₹0.86                                                                               |
| Utility and authentication | ≈ ₹0.115                                                                              |
| Service replies            | the first 1,000 a month per number are free, then ≈ ₹0.115 (charged since 1 Oct 2026) |

Utility templates inside the 24-hour window have been charged since 1 Oct 2026.

New portfolios start at 250 people a day. A verified business moves to 2,000 after Meta's quality check, then up
automatically.
