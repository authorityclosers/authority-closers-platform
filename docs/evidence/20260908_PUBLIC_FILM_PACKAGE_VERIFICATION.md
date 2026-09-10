# Public-film demonstration package verification

Date: 2026-09-08. Source/test checkpoint only; no runtime activation or deployment.

The new [package manifest](../../packages/python/ac_platform/media/data/public_films_technical_demo_12s_v1.json) uses schema `ac-public-film-demonstration-pack.v1`, ID `public-films-technical-demo-12s-v1`, and SHA256 `dc8f635df33432aee83c461535823881286ded1577a8f8a72dc5b10f0ad86b42`. It retains the exact 30 measured objects from the previous immutable inventory: two 12.032-second excerpts, progressive H.264/AAC, adaptive HLS and synthetic English test captions. Its separate namespace and explicit provenance do not change the old staging manifest or its production rejection.

The [verifier and read-only processor](../../packages/python/ac_platform/media/public_film_manifest.py) require the package-owned digest, nonzero tenant, and full release SHA. Both deployed environments additionally require the matching baked API release marker. Verification reuses the existing bounded storage checksum, probe, timeline and complete HLS graph checks through a narrowly parameterized identity factory. No caller source URL, mutable inventory or external provider is accepted.

The films retain the historical source registry's CC-BY attribution and modification notices. They are technical demonstrations, not full films, Dipak's instructional content, eligibility, enrollment, Watch completion or provider activation.

Validation:

- 63 focused manifest/processor tests passed.
- Combined new package, staging import/runtime, local fixture and read-only storage regression run: **253 passed**, 24.73 seconds.
- Scoped Ruff and mypy: passed, two production modules checked.

Tests use hermetic structural media doubles. They prove boundaries and regressions, not codec decoding, actual packaged-image startup, VPS delivery or production readiness. Independent source review was requested before integration. No media bytes were downloaded or changed; no database, service or remote state was modified.
