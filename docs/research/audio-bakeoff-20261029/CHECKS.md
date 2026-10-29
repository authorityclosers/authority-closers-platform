# Implementation evidence, 29 Oct 2026

- Final isolated AWS pytest: **14 passed in 0.03 s**. Covers disabled exact C1 result,
  fallback on optional failure/disk error/invalid helper JSON, model tamper rejection,
  invalid/non-finite/out-of-range times, same-speaker union, overlap, gaps and empty speech.
  Tests ran with a minimal config because this isolated benchmark venv has no async plugin;
  a pytest cache-directory warning did not fail a test. No database or customer fixture.
- Final Ruff with the repository's exact pyproject.toml: **All checks passed**.
- Final Ruff format check: **8 files already formatted**.
- Earlier local `uv run python -c 'import ac_platform.http'`: exit 0.
- Earlier local strict mypy on the three implementation modules: no issues.
- Actual AWS worker proof on public synthetic audio: canonical C1 retained, experimental
  sidecar present with schema `ac.local-audio-experiment/1`; 12,632 ms for 45,660 ms audio.
- Fresh-process native baseline: 1,282 ms for the same audio; 51,240 KiB child peak RSS.
- Hosted wb-ci request respected the active v1.7.0 release-cut hold; **CI pending**.
  Its waiting process and local queued final checks were stopped; no hold/slot bypass.
  Final isolated checks ran after benchmark inference on the idle AWS machine.

Numeric receipts: results.json. Model/dataset hashes: hashes.txt, asr-hashes.txt.
Exact benchmark dependencies: requirements.txt. ARM wheel availability: arm-wheels.json.
Full raw public-data results and test logs remain in the requested scratch directory
and the AWS experiment folder. No model binary or audio is committed.
