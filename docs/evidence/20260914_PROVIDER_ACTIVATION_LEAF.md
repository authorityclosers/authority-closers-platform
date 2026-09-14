# Provider activation leaf

This leaf adds an admin-only, append-only selection for the provider registry.
Saving a registry still creates an immutable configuration revision. Activation
selects one saved revision for plans quoted after the activation; a quote keeps
its configuration digest, provider, model, recipe and approval references.

The browser reads `GET /v1/admin/conversation/providers`. The response exposes
`current.activation_options` only for saved revisions that pass the pinned
approval bundle, the implemented provider catalog, the exact credential and
privacy references, the paid policy, and the aggregate bundle cap. The browser
cannot supply an approval digest or provider secret. `POST
/v1/admin/conversation/providers/activate` accepts only:

```json
{
  "expected_revision": 4,
  "target_revision": 4
}
```

The request requires the existing verified admin session, safe-origin checks,
and an `Idempotency-Key`. The server takes the provider revision lock, checks
the latest revision, resolves every asr/facts/coaching route against the
release-pinned acquisition policy, and writes an append-only activation receipt.
An exact-source stage approval without an acquisition policy is intentionally
insufficient for a global next-plan selection.

The current c437 activation evidence contains the runnable bounded route:
ElevenLabs `scribe_v2` for C2 transcription and Gemini `gemini-3.8-flash` for
C4 facts and C5 coaching. Catalog entries such as Groq or Gemini 3.1 Pro remain
unavailable to activation until a new pinned policy contains their exact
configuration digest, route recipe, credential/privacy/pricing references and
cost bounds. This leaf does not synthesize that approval or call a provider.

Validation evidence from the isolated worktree:

- Python focused provider/approval/router/plan tests: `101 passed`.
- Admin provider, control-center and benchmark UI tests: `13 passed`.
- `uv run ruff check` on the changed Python source and tests: passed.
- `uv run mypy packages/python`: `Success: no issues found in 284 source files`.
- Admin web TypeScript check and Prettier check: passed.
