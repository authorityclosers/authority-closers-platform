# Organisation seats (owner order, 30 Oct 2026: "land this asap")

A founding client could not invite its people: every invite said "All paid seats are
occupied". The owner asked for seats that work like ChatGPT and Claude organisations:
bought, kept, reassigned, and given free to founding clients by the owner, with no code.

## How ChatGPT and Claude do it (help centres, read 30 Oct 2026)

- **Seats:** both sell per-seat Standard and Premium seats, monthly or yearly, minimum 2.
  Only owners buy; an addition is prorated and charged at once.
- **Pending invites:** ChatGPT checks for a free seat only when an invite is accepted;
  Claude holds a seat from the moment of the invite and lets it expire after 21 days.
- **Reassignment:** on both, removing a member frees the seat at once for someone else;
  the bill does not drop. The member's work is kept and comes back if they are re-added.
- **Domains:** both verify email domains and offer discovery or auto-join. SSO on both;
  SCIM and claiming existing accounts are Enterprise only.
- **Roles:** ChatGPT has Owner, Admin, Analytics Viewer, Member; Claude has one Primary
  Owner, Owners, Admins, Users. Billing is an owner power on both, not a separate role.
- **Usage per member:** ChatGPT Business shows a per-member table (messages, credits);
  Enterprise adds last active and CSV. Claude shows active members against seats and a
  spend CSV per person.
- **Billing owner:** ChatGPT has no transfer, only more owners; Claude transfers the
  Primary Owner role by typing the new owner's email.
- **Reductions:** both reduce seats only at the next renewal, never below the seats in use
  (ChatGPT) or billable members (Claude), with no refund.

## What Sales X-Ray does

- **Seats = paid + free.** Paid seats come only from the current paid period (unchanged).
  Free (complimentary) seats come from grants the AC owner records in Admin, each with a
  count, a last day (IST) and a reason. A pending invite holds a seat until it is accepted,
  revoked or expires, as on Claude.
- **The grant ledger is append-only** (`organisation_seat_grants`, migration 0144). A change
  or an early end is a new row that supersedes the old one; seats 0 ends it. Every grant is
  also an audit event in the organisation's own audit trail. No billing row is written.
- **Only the owner** (the AI budget ceiling's allowlist, `CEILING_OWNER_EMAILS`) gives,
  changes or ends free seats, after a confirm step showing seats before and after. Any
  Admin with the platform organisation read permission sees them.
- **Ending or shrinking never removes anyone.** New invites wait until a seat is free.
- **Reassignment:** removing a member or revoking an invite frees the seat at once.
- **Team tab (Sales X-Ray):** owners, admins and Finance see seats taken, members, invites
  and free seats, where the seats come from, and a "Buy seats" link (owner and Finance) to
  the existing checkout. People who see the team also see each member's calls, call minutes
  and last activity, quietest first. No price, no end date: those stay in Admin.
- **Admin → Platform → Organisations:** every organisation's plan, seats taken, free seats,
  members, calls and minutes (30 days); per organisation, its seats, plan period and the
  whole grant history with who and why.

Unchanged: the owner-organisation exemption sealed into the release approval
(`organisations/seats.py`), checkout and plan prices (0143, Admin → Economics), and
operator-added members (the onboarding data change), which still skip the seat check.

## Give a founding client free seats

1. Admin → Platform → Organisations, choose the organisation.
2. Seats → Give free seats: the number, the last day they count, a reason.
3. Review shows seats now and after; confirm. The client's owner can invite at once.

To extend or reduce: Change on the grant. To stop: End (members stay).
