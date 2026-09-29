# Start gate: running main

- Starts are allowed while main CI runs; red and unknown remain guarded, with a red-only fix flag. Push and dispatch workflow runs count.
- `uv run pytest tests/infra/test_ac_task.py` — 54 passed.
- Owner decision: [AUT-72](/AUT/issues/AUT-72).
