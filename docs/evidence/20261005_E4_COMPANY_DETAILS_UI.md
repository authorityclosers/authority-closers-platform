# E4-W2 Company details — implementation evidence

Task: [AUT-1320](/AUT/issues/AUT-1320). Card revision: `720b97fe-3e8c-452d-94d4-1a10e1417336`.

Source base: `ce753781ba69f9b2e74b9300619473173bab2be1`. Implementation and tests: `80d9cb8eb7b74f61f3e929e5afe165e026558818`. This evidence commit changes documentation only; the final PR head is recorded on the task. `git merge-base --is-ancestor f5fbd6f88608a6431b0eeea1777afbf830aa72d3 HEAD` passed, confirming the merged settings contract is present.

The latest-main gate reported main green and sx-org FREE; the checkout was clean. `ac-gate start sx-org 1320-company-details-form` claimed a fresh branch from latest main. The old local branch was preserved after its name prevented the first start.

The Company tab now reads and saves all eight fields through the merged settings API. Owner/admin authority comes from the organisation API, with the returned organisation and settings tenants checked against the authenticated selection. Members receive a permission explanation; Personal makes no settings request. Existing email-domain controls remain owner-only.

The form submits the complete draft, accepts canonical server values, announces success and refreshes the organisation header. It keeps failed drafts, offers explicit same-key conflict retries and creates a new UUIDv4 for edited intent. Access loss clears the editor and refreshes access. Tenant/role changes, sign-out and unmount abort requests and ignore late responses. Only the seven allowed organisation source/test/style files and this note changed.

## Executed checks

Run from the repository root. All final commands below passed (exit 0).

```sh
pnpm exec prettier --write apps/sales-xray-web/app/organisation/organisation-api.ts apps/sales-xray-web/app/organisation/organisation-api.test.ts apps/sales-xray-web/app/organisation/company-details-panel.tsx apps/sales-xray-web/app/organisation/company-details-panel.test.tsx apps/sales-xray-web/app/organisation/organisation-view.tsx apps/sales-xray-web/app/organisation/organisation-view.test.tsx apps/sales-xray-web/app/organisation/organisation.module.css docs/evidence/20261005_E4_COMPANY_DETAILS_UI.md
pnpm exec prettier --check apps/sales-xray-web/app/organisation/organisation-api.ts apps/sales-xray-web/app/organisation/organisation-api.test.ts apps/sales-xray-web/app/organisation/company-details-panel.tsx apps/sales-xray-web/app/organisation/company-details-panel.test.tsx apps/sales-xray-web/app/organisation/organisation-view.tsx apps/sales-xray-web/app/organisation/organisation-view.test.tsx apps/sales-xray-web/app/organisation/organisation.module.css docs/evidence/20261005_E4_COMPANY_DETAILS_UI.md
pnpm --filter @ac/sales-xray-web exec vitest run app/organisation/organisation-api.test.ts app/organisation/company-details-panel.test.tsx app/organisation/organisation-view.test.tsx
pnpm --filter @ac/sales-xray-web typecheck
pnpm --filter @ac/sales-xray-web exec eslint app/organisation/organisation-api.ts app/organisation/company-details-panel.tsx app/organisation/organisation-view.tsx app/organisation/organisation-api.test.ts app/organisation/company-details-panel.test.tsx app/organisation/organisation-view.test.tsx --max-warnings 0
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
uv run pytest tests/unit/http/test_organisation_settings.py -q
git diff --check
ac-gate check
```

- Vitest: 3 files, 137 tests passed. Coverage includes strict payloads, HTTP failures, full PUT bodies, unchanged member-write behavior, validation, persistence, canonical header refresh, duplicate submission, conflict keys and delayed responses after scope loss.
- Web typecheck and targeted ESLint: passed. An initial test mock annotation failed typecheck; the corrected annotation passed.
- Ruff format: 1,027 files already formatted. Ruff check: passed. Mypy: 426 source files passed.
- Existing settings HTTP suite: 34 tests passed.
- Gate: `ok: task/sx-org/1320-company-details-form may be worked on`.

## Chromium evidence with fictional responses

The actual component, organisation CSS and existing Lightbox tokens were bundled into an isolated browser fixture. Its HTTPS `.test` origin is intercepted entirely by Playwright. Every request/result contains fictional data; the neighbouring domain card is a fixture placeholder. This verifies the form and its layout, not a deployed full-page journey or real persistence.

The driver is a run-owned scratch file. Its executed command was:

```sh
TASK_UI_FIXTURE_DIR="${PAPERCLIP_RUN_SCRATCH_DIR:-$PAPERCLIP_SCRATCH_DIR}/company-details-browser"
node "$TASK_UI_FIXTURE_DIR/check.cjs"
```

Final result: pass at 1440×900 and 390×844. Eight accessible labels and keyboard order passed. Loading, pending, saved and explicit 409 retry states were visible. An 80-character unbroken name and a 1,000-character address draft were submitted; their canonical values survived a fresh GET. Empty optional strings stayed editable. Neither width had horizontal overflow or clipped action/error text. Saved desktop, saved phone and rejected phone screenshots were also visually inspected.

Uploaded task artifacts:

- Desktop: [loading](/api/attachments/79b974e9-8734-42c8-b40c-0376f044f8b0/content), [saved](/api/attachments/b0c952f3-6271-401d-acdd-d795858dd6e5/content), [rejected save](/api/attachments/56e9f8e0-d21f-4740-bbe7-0cae977e3b1c/content).
- Phone: [loading](/api/attachments/9b676277-0a7f-46ff-9248-04c15fc686ed/content), [saved](/api/attachments/7fdfbfe8-03d1-4b8b-ab2b-4624286f5975/content), [rejected save](/api/attachments/9296bdb4-7dff-4dfe-a5f6-20cd88b3192f/content).
- [Sanitized request/result receipt](/api/attachments/c9a1a323-b3e3-4cd0-b0ba-9620ee8bf9e9/content) and [reproducible browser driver](/api/attachments/1d42f608-9a26-476a-a64c-f0b5352c7a2f/content).

## Deployed acceptance remains pending

The issue runtime read returned `currentExecutionWorkspace: null`. No service was started, checkout deployed, or real account/session used. No actual served UI/API revision or dev/staging acceptance is claimed.

After independent CTO review, CEO exact-head approval and the governed merge/release path, the Organisation Engineer must verify the merged UI on dev, then staging: owner/admin saves and reloads all fields; member and Personal make no private request; failed saves preserve the draft and saved server state; tenant switching retains no prior private fields. Record actual served revisions and ancestry containing both this implementation and settings API `f5fbd6f`. Reuse [AUT-515](/AUT/issues/AUT-515) and [AUT-1285](/AUT/issues/AUT-1285) only if their session/API outputs are actually missing at that acceptance step. Existing [AUT-1309](/AUT/issues/AUT-1309) recovery ownership remains unchanged. Review or merge approval alone does not complete this task.
