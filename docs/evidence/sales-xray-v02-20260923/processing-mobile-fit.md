# Processing states on short screens

The normal and observed processing views use the same ProcessingExperience component and stylesheet. A baseline layout overflow was visible in both paths; selecting an observation did not create a separate mobile layout. The shared stylesheet now uses a compact two-column stage trail on mobile and reduces spacing on screens at most 720 pixels high. Interactive targets retain a minimum 44-pixel height.

Synthetic browser checks exercised C2, C4, C5 and held at 320x568, 375x667, 390x844 and 1440x900. The 390 and desktop cases fit the declared main viewport. At smaller heights, inner scrolling is intentional: after scrolling to the footer, status/link actions and the held state's additional actions are inside the visible main area, with the privacy entry above fixed navigation. No horizontal page overflow was measured. The permanent harness asserts these conditions and rejects an empty viewport selection.

The 320x568 C5 scrolled screenshot was visually inspected: the stage trail, saved-work panel, next-step disclosure, status/link actions and privacy entry are legible and reachable. This is selected-state Chromium evidence, not proof for every browser, translation, screen or physical device. All API responses in the harness are intercepted synthetic fixtures; no customer recording or paid provider request was made.

Reproduce with Node 24 and the local review launcher running:

```powershell
$env:SALES_XRAY_QA_WIDTH='320'
$env:SALES_XRAY_QA_STATES='C2,C4,C5,held'
$env:SALES_XRAY_QA_OBSERVED='1'
node scripts/verify-sales-xray-viewport.mjs
```

Screenshots and measured geometry are written under the ignored `.tmp/sales-xray-ui-qa/observed-progress` directory. Successful fixture coverage does not replace authenticated VPS capture acceptance or the owner's visual review before UI promotion.
