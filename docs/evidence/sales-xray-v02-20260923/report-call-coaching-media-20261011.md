# Per-call Report Coaching examples (AUT-1677)

The Report adopts Strike D main bcd4e40's optional reviewed `media_clips` with its existing fixed-route codec and player. Legacy reads without clips keep the text lesson. Unsafe optional clips are dropped without making the Report unavailable; unavailable Coaching always clears clips. The player is bound to the current person/workspace/session/call/native source and both available report digests, so changed Coaching revisions reset playback even when an older acquisition envelope lacks a digest.

The player labels neutral placeholder narration, shows its transcript/slides and waits for an explicit play action. A failed source gives retry while the lesson and mission remain readable. It uses only the authenticated pinned Coaching media route; no external URL, provider request, eager audio, entitlement/payment change, catalogue activation or Coaching-owned file edit is introduced.

Validation completed: 79 focused call-Coaching codec/read/view, Report preload and shared-player cases (five files, 15.40 seconds), final app typecheck, changed-file ESLint/Prettier, browser-script Ruff and bounded fictional 390/1440 light/dark checks pass. No overflow or page errors; phone controls are at least 44 px. The bootstrap causes zero Coaching API reads and zero eager audio reads; the proof intercepts exactly four fictional media requests for two explicit play/retry pairs. Screenshots inspected; preview stopped and generated next-env restored.

Production/authenticated QA is still pending the authorized operator and Strike H. Fictional local proof is not a deployed receipt. Companies/outcome migrations remain blocked by #442/#437 and are not part of this change.
