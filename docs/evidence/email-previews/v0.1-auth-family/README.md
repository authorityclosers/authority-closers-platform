# v0.1 auth email visual evidence

Generated from the production renderer in
`packages/python/ac_platform/providers/resend_email.py`.

Files:

- `01-email-verification.html`
- `02-password-reset.html`
- `03-course-access-welcome.html`
- `index.html`

Regenerate:

```powershell
uv run python scripts/render_email_previews.py
```

The links contain `PREVIEW_ONLY_NOT_A_CREDENTIAL`. These files prove template
rendering, responsive composition, and safe escaping; they do not prove that an
external provider accepted or delivered a message. Staging remains on the fake
provider with external side effects held until the activation gate in
[`../../../contracts/V0_1_TRANSACTIONAL_EMAIL_CONTRACT.md`](../../../contracts/V0_1_TRANSACTIONAL_EMAIL_CONTRACT.md)
is satisfied.
