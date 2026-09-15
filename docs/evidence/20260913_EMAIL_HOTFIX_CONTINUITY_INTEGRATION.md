# Email recovery integration — 13 September 2026

Integrated the urgent email/Google learner hotfix through666dcd0 with accepted course/activity continuity source6e4f59f,02bdb91 and6b130fb. The only semantic merge conflict was the password-email resolver: the hotfix extracted it for the initial-held verification delivery command while continuity added v2 context links inside the worker method.

The merged worker retains one shared resolver, explicitly allows the four v1/v2 password job kinds, validates each canonical route payload, and appends allowlisted course/activity context before the private token fragment. DurableWorker delegates to that resolver; the initial activation command also uses it. No second template path was introduced. Legacy v1 messages retain their existing links.

Validation on the combined tree:

- Worker, outbox, bootstrap and password-email HTTP continuity:162passed.
- HTTP auth routes and transaction behavior:95passed.
- Worker Ruff and mypy checks passed.
- Source acceptance for the email chain additionally includes193Python and1711learner tests, independent review and canonical browser proofs recorded in20260913_PASSWORD_EMAIL_CONTEXT_CONTINUITY.md. Those counts overlap these integration checks.

Runtime observation before this combined candidate: a normal staging forgot-password request at05:25IST delivered a real Resend email to admin Gmail; the link opened the staging password-reset form. No password was entered or changed. This is a delivery/link proof, not a claim that this combined source is deployed.

The urgent release is deployed separately first. This combined branch still includes pending Sales release work and requires its own exact-SHA image build and staging/production acceptance.
