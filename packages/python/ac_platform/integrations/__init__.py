"""Sales X-Ray developer platform: API keys, sealed integration secrets, webhooks from the UI.

Owner order (19 Oct 2026): connecting any app must be as simple as with top SaaS apps,
with no Infisical, password manager or ops step per customer. An organisation's owners
and admins create API keys and webhooks under Settings -> Integrations; keys are shown
once and stored only as a SHA-256; secrets the app must use again (a webhook signing
secret, a partner app's service key) are sealed with AES-256-GCM under one platform key
per environment (``AC_INTEGRATIONS_SEAL_KEY``). Design: docs/architecture/INTEGRATIONS.md.
"""
