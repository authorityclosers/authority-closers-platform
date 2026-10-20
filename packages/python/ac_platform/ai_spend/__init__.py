"""AI spend: where every rupee of model spend goes, and the caps that stop leaks.

Owner, 20 Oct 2026, after the shared Gemini credit ran out: "fix those pipelines and
unwanted burns like tests each time a new update goes for no reason … stop the leakage
of credits and tokens". This package reads every paid AI request this environment made
(from each feature's own ledger rows), and holds one environment-wide daily and monthly
cap, plus per-feature caps, that every background job checks before it calls a model.
"""
