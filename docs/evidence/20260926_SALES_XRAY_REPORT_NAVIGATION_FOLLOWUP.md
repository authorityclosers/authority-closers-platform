# Sales Xray saved-report navigation follow-up

This follow-up to the frozen `6d16f0573e6d84d21b0214eb3aa8715f7cb79e57` UI package fixes the workspace navigation context. Opening a saved call, including its loading/recovery view, now marks **Calls** as current. A completed report also marks Calls; a fresh upload entry retains **New analysis**. It does not change upload, processing or provider behaviour.

Opus identified the issue in a read-only source review. Root confirmed the shell default was being used at every acquisition render branch. The existing studio integration cases now assert the current workspace link for fresh entry and a restored playable report, retaining their other assertions.

Validation: all 90 acquisition-studio integration tests passed with Node 24; Prettier and `git diff --check` passed. The new assertions check both fresh-entry and restored-report navigation while keeping the existing single-player/source checks. This follow-up is separate from the frozen web artifact and does not claim live deployment.
