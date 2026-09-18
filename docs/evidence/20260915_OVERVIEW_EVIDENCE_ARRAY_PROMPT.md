# Explicit overview evidence arrays

Base: `bce2938cfb3a34d3389ef83849e203fd2e27b37d`.

The release recovery investigation reported a complete Gemini C5 response rejected
with `report_overview_invalid` / `list_type`: nested source notes contained one
evidence object instead of an evidence array. The old overview prompt used
`{text,evidence}` without specifying that nested type. This leaf changes prompt
shape only; it does not edit a saved response or relax any validator.

The prompt now defines a span as `{segment_id,quote,start_ms,end_ms}`, requires every
evidence value to be a nonempty JSON array of span objects (including one-span
cases), and uses `evidence:[span]` at all eleven nested source-note paths. Required
overview fields, enums, source quotes/times, chronology, financial uncertainty,
human review, the null progress field, and the source profile remain governed by
the existing parser. The instructions and repeated shape descriptions were
compacted to preserve the existing Groq and Gemini Pro input budgets. No budget or
output-token ceiling changes are included.

The Gemini transport continues to request JSON output using its existing native
envelope. This leaf does not claim native JSON Schema enforcement or guarantee
that a future provider response will satisfy semantic validation. The release
owner separately owns strict singleton compatibility and audited saved-response
recovery.

## Tested here

Receipt:
`D:/AC-authority-closers-release-audit/peer-overview-arrays-final-v2-20260915.xml`.

- 163 tests passed in 3.11 seconds across the new evidence prompt tests and existing
  full-context, extended-budget, report, overview, structure, inference-task and
  Gemini-task suites.
- The synthetic full overview populates all eleven evidence locations and passes
  the actual report parser unchanged. Each bare-object variant reproduces exactly
  the strict model's expected `list_type` error at its own path.
- Prepared Gemini and Groq inputs round-trip; the prompt change affects the C5
  request hash while keeping C2/C4 preparation, transcript/profile revisions and
  output allocations unchanged.
- Existing one- and three-turn Groq/Gemini Pro/Flash routes with 3,200 output
  tokens pass their unchanged input limits. Full-context/tamper and the 96,000
  total-unit Flash boundary regressions also pass.
- Ruff lint and format checks, targeted mypy and `git diff --check` pass.

Earlier local runs caught legacy input-budget overflow from the longer prompt;
the descriptions were compacted and the final receipt above is passing. The
earlier receipts were preserved outside Git.

No provider calls, private recording copies, database operations, deployment,
browser checks, numerical publication, profile promotion or training occurred in
this leaf. Production recovery and deployment remain separate release steps.
