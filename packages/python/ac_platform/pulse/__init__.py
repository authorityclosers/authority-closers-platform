"""Pulse, Estate Autopilots' work app, as an identity provider and org directory for Sales X-Ray.

- ``oidc``: OpenID Connect against one Pulse issuer (discovery, PKCE, ID-token checks).
- ``profile``: the name, title, team and photo a person's Pulse account gives them here.
- ``org_link``: an organisation's link to its Pulse org, the member directory and its sync.
- ``http``: the routes (Organisation -> Integrations -> Pulse, the callback, the webhook).

Contract: docs/architecture/pulse-identity-contract.md. Design:
docs/product/roles-owner-profile-pulse.md, section 3.
"""
