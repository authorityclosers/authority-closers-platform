# Offline benchmark integration evidence

This note records the later v0.2 integration leaf without rewriting the original benchmark evidence. Existing files under `docs/evidence/20260914_OFFLINE_BENCHMARK.md` and `docs/evidence/offline-benchmark-20260914/` remain unchanged.

- Integration base: `c437c1758d8a66ede0221f83fe787bb13de33c40`.
- Accepted offline benchmark source leaf: `9db2d1228b616eb9ac14a8de0c7fcf2841ccc9c2`.
- Imported commit on this isolated branch: `69bb4ae` (`codex/sales-xray-offline-benchmark-v02-integration-20260914`).
- Scoped validation on the imported leaf: **29 passed** in `tests/unit/conversation_intelligence/test_benchmark.py`. The original historical evidence records **68 passed** for its broader benchmark, context, and review regression subset; those counts describe different scopes and are not added together.
- Ruff check, Ruff format check, and strict mypy for `benchmark.py` and `benchmark_cli.py` passed. No provider, database, runtime, VPS, browser, or release operation was used.

The fresh synthetic CLI receipt is outside Git at
`D:\AC-authority-closers-release-audit\offline-benchmark-receipts-34f134a\a18d4b16-60ef-4ae5-8b6b-95da17c7f6e4\receipt.json`.
Its internal canonical `receipt_sha256` is
`1a2732170e330c8cfcd060f0b28f9eefe4af3b53b7064bcf949c38153311056c`.
The receipt file's own SHA-256 is
`61c29012e3d32791c0bae5d20faadc08e9eefb4c3e382cdd1d682d61dcd595ae`.
The run passed 8 selected cases and 16 comparisons with zero provider/ASR calls and ₹0 provider cost; it is synthetic context/profile replay evidence, not a live or hosted benchmark.

Root independently reviewed both runner modules with no blocking finding and verified implementation digest
`09a701254cb708203f77aa5ece22216d55110191a4bca08651d8946fa5919cbe` against the receipt. This leaf remains source-only and not staged, deployed, published, or activated.
