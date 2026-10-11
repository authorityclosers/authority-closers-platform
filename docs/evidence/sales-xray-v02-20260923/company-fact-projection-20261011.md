# Company fact read boundary (AUT-1677)

Source: binding spec SHA256
`a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`.

The pure Company projection is prepared for canonical storage integration.
It grants no source access, invokes no provider and creates no identity.
The caller must supply an authorised, verified current C5/C2 pair and the
effective withholding plan. The whole pinned candidate is revalidated for
literal business values, the original business subject, prospect speaker,
native quote/time, source SHA and transcript revision. Private purpose/name
withholds the candidate; a private attribute withholds that field.

Human values win regardless of history ordering. Human Unknown retains its
lock without exposing previous or later values. Changed requires the exact
visible predecessor of the same field; later source-backed disagreements are
bounded to five and do not overwrite the human value.

Validation: 68 focused projection/candidate/human-command unit cases pass;
strict module mypy and changed-file Ruff pass. All data is fictional. The
Company schema, store and HTTP prototype remain private and unmounted while
PRs #442 and #437 hold shared migration/registry/backup files. This receipt is
not a deployed Company feature or production Report verification.

The prepared C5 fallback reads only its explicit `company` fact as a literal
name. It does not reinterpret person industry/team-size/city or narrative
prose. A missing/old C5, unresolved speaker/quote, private purpose/name, stale
source or conflicting company names yields no candidate. A private alternative
does not resolve ambiguity. Repeated mentions remain one candidate payload;
there is no identity lookup or merge, and other fields stay absent/Unknown.
The seven new detection cases pass with adjacent candidate/projection cases
(43 total), plus strict module mypy and Ruff. This helper invokes no provider
and remains unmounted; canonical Company persistence is still private WIP.
