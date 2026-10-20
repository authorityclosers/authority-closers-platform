# Production provider changes from Admin: owner approval and the sealer

Status: design approved (option A) by the orchestrator on 20 Oct 2026; option B (approval inside the app alone) is off the table. Built in slices by admin-2; Root installs the host parts once.

## Why

Admin's Providers hub lets a control account add a provider key and pick a model per stage. In development and staging a choice applies at once, behind the AI spend guard and caps. In production, spend must stay approved from outside the app: the app may propose and record the owner's yes, but it must never be able to widen what may be approved.

Today a production provider configuration is active only if its `configuration_sha256` is in the deployment's hosted approval bundle (`activation_contract.HostedApprovalBundle`), an operator-written file whose digest sits in the release metadata. That outside approval stays; what goes away is the manual Root step for each change.

## The flow

1. **Propose (Admin).** On the hub, a control account chooses a model for a stage in production. Admin shows the cost per audio minute before and after and the stage's budget cap. Saving makes a configuration revision (append-only, as today) and a change request: an append-only row with the revision digest, the estimate and who asked.
2. **Approve (owner, in Admin).** Only a control account, within 10 minutes of signing in, types the stage name to confirm. The approval is an audit event and an append-only approval row naming the exact configuration digest, an expiry (24 hours) and its bounds: the most rupees per audio minute, and the provider, which must be on the allowed list.
3. **Seal (host, installed once by Root).** `ac-provider-approval-seal` runs every minute as the release user. It:
   - reads approved, unsealed change requests through a read-only path (a staff key with `admin:read` plus a new `approvals:read` scope, or a read-only database view);
   - re-checks every bound against its own policy file, `/etc/ac-release/provider-policy.json`, owned by root and unwritable by the app: the allowed providers with their terms, privacy and pricing references, a cap per audio minute and the budget scope;
   - writes the new hosted approval bundle and its digest into the release metadata, then restarts the worker.
4. **Activate (Admin).** The revision now matches the bundle, so the existing `ConversationProviderAdmin.activate` path runs unchanged, with its audit.

Raising a bound or adding a provider to the allowed list stays an edit of the policy file by Root or the owner, on purpose.

## Keys

- A key added in Admin is sealed with AES-256-GCM under the environment's platform key `AC_INTEGRATIONS_SEAL_KEY` (`integrations/sealed.py`, purpose `provider_key`, migration 20261020_0114) and never shown again.
- The API already holds that key. The **workers** need it too, so a sealed key can be used at dispatch; until then Admin keys serve the free connection test and the model lists only.
- Each environment keeps its own platform key and its own provider keys; a production value is never copied into development.

## Root steps

1. **Now:** give each environment's workers `AC_INTEGRATIONS_SEAL_KEY` (the same per-environment value as that environment's API, from Infisical). Check without printing it:
   `python -c "from ac_platform.integrations.sealed import load_key; print(load_key() is not None)"` inside the worker prints `True`.
2. **Once the sealer lands** (its card gets the commit): install `ac-provider-approval-seal` with its service and timer, and create `/etc/ac-release/provider-policy.json` (root-owned, 0644) from the example in the repo with the owner's allowed providers and caps.

After that, no Root step per change.
