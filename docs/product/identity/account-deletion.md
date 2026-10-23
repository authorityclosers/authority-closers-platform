# Delete account in the app (Google Play, 23 Oct 2026)

Google Play requires apps that have sign-up to let people start account deletion inside the
app, as well as on a web page. Sales X-Ray now has both:

- In the app: **Settings → Security → Delete account**.
- On the web: `/data-deletion` on the Sales X-Ray site. This is the link in the Play Data
  safety form. It describes the in-app path first, then the email
  path.

## What the person sees

The panel opens under its row, with no sheet on top of Settings. It says what is deleted and
what is kept, using the same lists as /data-deletion. It then asks for one thing at a time:

1. **Staff accounts.** These cannot delete themselves. The panel says the owner closes them.
2. **An organisation they alone own that still has other members.** The panel asks them to
   choose a new owner first, through the link to Organisation → Members. "Check again" reads
   the state again.
3. **A session older than 10 minutes.** The panel asks them to sign out and sign in again. This
   is the same rule as removing a sign-in method.
4. **The confirmation.** They type `DELETE`, and then **Delete my account** is enabled.

When the deletion goes through, the app opens `/account-closed`. That is a plain page that
needs no session.

## What the server does (`POST /v1/me/account-deletion`)

All of the following happens in one transaction, in `http/routes/account_deletion.py` and
`identity/account_deletion.py`:

- **Deletion request.** It opens the person's one deletion request (`deletion_requests`,
  status `requested`).
- **Sign-out everywhere.** It revokes every session of theirs, with the reason
  `account closed for deletion`.
- **Account closed.** Every sign-in path issues sessions through `_issue_session`, which now
  refuses a person with an open deletion request (`AccountClosedError`). Each path shows the
  refusal its own way:
  - Email code and password sign-in answer 403 `account_closed`.
  - Google, Apple and Facebook sign-in come back as `auth_result=account_closed`.
  - The sign-in screen says the account is closed and gives the address to write to.
- **Audit.** It writes `identity.account_closed_for_deletion.v1`, with the request id, the
  number of sessions revoked, the organisations that close with the account and the client
  address.
- **Emails.** Two emails go out:
  - to the person: "Your Sales X-Ray account is closed";
  - to admin@authorityclosers.com: "Account deletion request: <email>".

  The outbox carries only the audit event id. The addresses are read when each email is sent.

Nothing is deleted at this step. There is no migration: the `deletion_requests` table already
exists, from 0001.

## Carrying it out (owner-approved, within 2 days)

The request arrives in the admin@ inbox. Follow AGENTS.md, OWNER-APPROVED DELETIONS:

1. List exactly what will be deleted, with ids and counts and the environment:
   - the person's recordings and reports;
   - their leads;
   - any organisation that closes with the account (`organisations_closing` in the audit
     event).
2. The owner answers "approve delete: …".
3. Take a production snapshot.
4. Delete through the app's own paths. For example, recordings use the conversation deletion
   request and leads use the lead delete.
5. Finish the identity side with `AsyncIdentityApplication.begin_deletion_processing`, then
   `complete_deletion`. This requires the `identity_deletion_process` permission. It:
   - erases the Sales X-Ray profile;
   - sets the person to `deleted`;
   - ends their memberships;
   - leaves audit history in place.

**If the person changes their mind before step 3:** cancel the request, which opens the
account again. Today this needs an owner-approved data change, because the in-app
`cancel_deletion` needs the person's own session, and that session is closed.

## Tests

- `tests/integration/test_sales_xray_account_deletion_postgresql.py`
- `tests/unit/http/test_account_deletion_email.py`
- `apps/sales-xray-web/app/account-delete.test.tsx`
- the account-closed case in `apps/sales-xray-web/app/account-auth-client.test.ts`
- `apps/sales-xray-web/app/policy-content.test.tsx`
