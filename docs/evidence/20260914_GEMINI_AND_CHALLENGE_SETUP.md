# Gemini and upload challenge setup — 14 September 2026

The supplied Gemini testing key is stored in the configured Infisical project
`b421c44e-4599-4394-8df6-758ed8aedfed`, environment `dev`. The dedicated worker
reads only `/sales-xray-test/gemini/GEMINI_API_KEY` through its scoped read token.
The API and frontend receive no Gemini key or provider identity mount.

The earlier synthetic provider smoke returned READY/STOP using eleven total
tokens. This setup did not repeat inference or send a real call externally.
The worker token expires on 20 September 2026 and needs renewal for continued use.

Cloudflare now contains two independent managed Turnstile widgets:

| Environment | Exact hostname | Public site key |
| --- | --- | --- |
| Staging | salesxray-staging.authorityclosers.com | 0x4AAAAAAEzFlDviGlPfsaaU |
| Production | salesxray.authorityclosers.com | 0x4AAAAAAEzFpHYsGeFyn5zF |

Both use `no_clearance`; neither bypasses existing security rules. Cloudflare API
readback confirms their names, domains and modes. Secrets are saved under the
Infisical `dev:/sales-xray-test/turnstile` folder and delivered as separate
`/etc/authority-closers/secrets/sales-xray/{environment}/challenge-secret` files.
Each is a regular file owned by `10001:0`, mode `0400`, with private root-owned
source directories. The release mounts only the selected file into the API.

External receipts under `D:/AC-authority-closers-release-audit`:

- `gemini-scoped-identity-20260914.json`
- `turnstile-provisioning-20260914.json`
- `turnstile-cloudflare-readback-20260914.json`

Secret values were not logged or committed. The temporary encrypted transfer
artifacts and their ephemeral private key were removed after verified delivery.

This is credential and challenge provisioning evidence, not live application
acceptance. The new application image, frontend consumer, canonical provider
configuration, processing principal and release activation still require the
coordinated staging and production deployment and end-to-end verification.
