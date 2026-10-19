"""Partner webhooks for Sales X-Ray: signed ``analysis.completed`` events with quote facts.

First partner: Wise Life (contract ``sx.analysis_completed.v1``, 18 Oct 2026).
Modules: ``models`` (tables, migration 20261018_0096), ``number_words`` (closed
number word lists), ``amounts`` (our own reader for sizes, counts and rupee
amounts), ``summary_mask`` (every number in the summary as "[n]"),
``quote_facts`` (profile, prompt and validation), ``extraction`` (paid-attempt
ledger), ``payload`` (event body), ``pipeline`` (candidates and enqueue),
``delivery`` (signing, retries, erasure sweep), ``endpoints`` (operator
commands) and ``cli`` (the runner).
"""
