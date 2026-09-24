# C5 evidence contract prevention

A retained C5 response exceeded the existing three-reference limit for two
overview SourceNotes. Its separately bounded repair then failed the existing
before/change/after chronology validation. The primary evidence references were
valid individually; neither failure justified changing source text, timestamps,
or weakening validation. Incident identifiers and customer material remain in
private operational receipts.

The generation instruction and compact format now explicitly specify one to
three distinct supported references per SourceNote and exactly one per rewatch
moment. Conversation-change guidance states both native timestamp inequalities
and requires null for an unclear or overlapping transition. This modifies the
prepared-input digest for new requests; retained requests must continue using
their original bound inputs. Parser and response-model limits are unchanged.

Local validation: 117 tests passed across overview prompt, legacy evidence
compatibility, overview parsing, coaching-v5 integration and retained C5 recovery.
The new regressions reject four individually valid references at both affected
SourceNote paths, reject overlap on either side of the transition, and verify
that parsing does not mutate the source payload. The provider prompt contract
is tested separately from parser behavior. Focused Ruff formatting, lint and
diff checks passed. Independent read-only review found no blocking issue. Its
wording observation was addressed by specifying overlap between the three
chronology groups, matching the validator. Duplicate-span rejection remains a
separate pre-existing validator gap; the prompt's distinct-span guidance does
not imply that a new duplicate-validation rule was added.

This is prevention guidance, not proof that a model will always comply. It does
not authorize a new provider attempt, release uncertain charges, or mark an
original failed job successful. A source-bound retained draft was independently
recovered through the canonical append-only service without another provider
request; browser reload, reading/tabbed view and transcript excerpt playback
were verified on staging. That draft is not a fresh automatic completion or
evidence of improved report quality. Exact-successor CI and real acceptance
remain required before any production readiness claim.
