# Sealed fictional pack v1

This is authored fictional evidence for the Jev Phase 1 and P4 auditor research,
using the controlled revisions recorded in `truth/sources.json`. It contains
36 C2-shaped calls: twelve situations with English, Hindi–English and
Gujarati–English twins, 720 report items and 216 mutations. Each style has four
short, six medium and two long calls. Long calls are approximately 5,000 words.
The 120 red-team cases each have a clean twin, making 240 probe inputs.

Give evaluation arms **only `inputs/` and `questions/`**. Author intent labels,
facts, segment truth, mutation keys, attack pairings, review samples and source
pins stay in `truth/`. The author runs no evaluation arm, now or later. This
change contains no runner, scorer, provider call or product integration.

`questions/definitions.json` accompanies every request. Question IDs encode
their focal segment or report item. Triage is call-level; segment labels use
the construct definitions and full exchanges; ranking uses item severity;
confidence uses item support. The probability contract accompanies every use.
Report items are a synthetic item collection, rather than a production C5
payload. Segment IDs, speaker IDs and integer timings follow the C2 shape.

The five equally allocated turn constructions and bilingual token balance are
**synthetic design choices**, not measured calibration proportions. The frozen
reference remains 11 reports, 9 mixed-script / 2 Latin-only, 28,383 words;
within-turn calibration measurements remain not measured. R5 puts native-script
instructions inside English controls. Probe deltas are counted separately from
the clean base quotas. None of this certifies the separate containment review.

People and companies use `<PERSON_n>` / `<COMPANY_n>` category tokens. No real
call or identity source was read. The checker rejects phone/email/URL patterns,
invalid entity tokens and words outside the sealed fictional vocabulary. It
does not use or claim access to a real-person gazetteer; multilingual meaning
and naturalness also require the named human spot check.

Run locally, without CI or credentials:

```sh
python3 tools/research/check_jev_fictional_pack.py --selftest
uv run pytest tools/research/check_jev_fictional_pack.py -q
```

`MANIFEST.json` hashes every pack file except itself (self-hashing would be
recursive), and pins the checker hash. A set hash is SHA-256 of sorted UTF-8
`relative_path + NUL + file_sha256 + newline` records. The input set includes
`inputs/` and `questions/`; the truth set includes `truth/`. Publish both hashes
before evaluation. Numerical or content changes require a new pack version.

For aggregate receipts, pass `--receipt <outside-pack-path>`; output must stay
outside the sealed tree. Receipts report counts before rates: turn categories,
eligible/native tokens, within-turn language switches, script transitions and
eligible adjacent-token pairs per call, plus injection token deltas. Divide
switches by turns for the specified rate; token-pair diagnostics use the
separate pair denominator (N/A for zero). The four-call spot-check sample in
`truth/spot-check.json` covers 80 items and 24 mutations, exceeding 10% of each.
