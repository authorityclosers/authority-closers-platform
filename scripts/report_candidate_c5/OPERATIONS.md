# Report candidate preparation — AUT-1879

This is an offline review package for [AUT-1878](/AUT/issues/AUT-1878), under
[AUT-63](/AUT/issues/AUT-63). Root Operator is the single admitted executor.
No installation, provider request, activation, canonical write or delivery
closure is performed by this source. `--run` is not supported. CTO independently
reviews the eventual PR head before any installation or execution handoff.

## Source and reproducible checks

Candidate: PR #470 source `2b6391186518b374186b2ddd9a220ced3619fb8f`, merge
`b157caa50ff8197da3a0abddc00f6d4912f59f9d`. All 184 candidate library Python/JSON
files matched the admitted checkout byte for byte. `pins.json` records the tree
algorithm/hash, exact model, C4/C5 configuration, corpus and retained runner pins.
`SOURCE-SHA256SUMS` identifies the route files; the issue review packet records
the pushed full route commit separately to avoid a self-referential hash.

The route passes explicit `report-c5-v1`, authoritative transcript-bound roles,
the pinned profile and candidate's existing qualitative pack to the builder.
The parser uses the byte-frozen transcript and the same roles. It compares those
roles with the actual native request context before decoding and calling
`parse_groq_response`. It requires `report-content/1`; malformed, truncated,
legacy or mismatched output cannot fall back to v5. Complete C4 coverage is
validated against the audio source, revision, native timebase and segment IDs.
Request provenance records profile/schema/prompt/pack, C4 coverage, source,
role and request fingerprints. Runtime validation code is unchanged.

```bash
.venv/bin/pytest tests/unit/test_report_candidate_corpus_route.py -q
.venv/bin/ruff check scripts/report_candidate_c5/replay.py tests/unit/test_report_candidate_corpus_route.py
.venv/bin/ruff format --check scripts/report_candidate_c5/replay.py tests/unit/test_report_candidate_corpus_route.py
```

`offline-proof.json` records the executed isolated-Python CLI, selected revision,
actual run ID, exit 0, private ledger path/hash and all per-call dispositions.
Replay the same command with a **new** run ID and new output directory. Existing
outputs are refused, never replaced. The output must be outside retained corpus
v1; output directories are 0700 and files 0600. The runner's stdout contains
counts/refusals only. Do not publish native requests or retained call contents.

The route-level fictional test constructs and parses a native request under
blocked sockets, HTTP sends, provider construction, environment lookup and
subprocess entrypoints. Additional tests reject foreign/missing roles, wrong
image/library/schema, bad coverage, altered request provenance, legacy/malformed
output and unknown/non-finite/over-cap cost. These are local structural proofs,
not scientific quality acceptance or real-provider compatibility evidence.

## All-16 disposition and cost limits

All 16 are selected under `OWNER-20261010-ALL-CALLS`. A/B/E/F/G/H/I/J/K/L/M/N/X
retain completed baseline C5, all legacy coaching-v5; their Report candidate
output remains unavailable. C retains complete C2/C4 but no C5; D only C2;
O no baseline artifacts. C/D/O retain [AUT-1676](/AUT/issues/AUT-1676) as the
pipeline disposition owner. No technical diagnosis or repair is invented here.
Prospect and longitudinal Coaching are not evaluated and cannot be called passed.

Retained `baseline/plans.json` has null speaker_roles for every C2 call.
Call A alone has a historical speaker-map file. Its rows lack the frozen role
origin, map hash and account-holder attribution needed for this route. Ground
truth research roles, speaker order, names and old outcomes are not substitutes.
The exact missing output is a names-free authoritative snapshot for each of the
15 retained transcript revisions, including origin, transcript_revision,
map_revision and complete speaker_id/role/is_account_holder entries, supplied
through a reviewed read-only export by the existing delivery owner. C/D/O also
need their missing pipeline artifacts; an absent output language is refused.

The plan locally constructs 33 full facts-v2 requests from 15 C2 inputs, with
1,400 maximum output tokens per C4 chunk. Their retained-config subtotal is
$0.55148475. C4 regeneration is a hypothetical alternative, not a selected send.
There are zero candidate C5 requests: no input has valid authoritative roles.
C5 is configured for 8,000 maximum output tokens; its estimate and total are
null, not zero. O also prevents a complete 16-call C4 total. Actual spend is $0.

Estimator: the entire serialized native request, including schema and JSON
escapes, at one UTF-8 byte per input token, plus 128 framing tokens; output uses
the configured maximum, including thinking within the candidate's native cap.
Pricing is the **retained configuration**, `ref:pricing/gemini-38-intro-20260914`,
evidence `d2be76be50be45b17b66aa528eeff86806705bf9e90dce36772c715e3c312fde`,
input $0.75/output $3.75 per million. It is not a current provider-price receipt.
The estimator refuses absent/non-finite rates/estimates and over-cap plans.
No authorized candidate budget/cap was supplied; no cap was invented. Old v5
$1.6984/$2 values are excluded. A diagnostic `--max-usd` grants no spend approval.
Real sending remains unavailable even when a configured estimate fits that cap.

## Installation proposal — not executed

After exact-head CTO source/operator review, the parent owns a separate bounded
Root handoff. Obtain the existing Report delivery owner's immutable image digest,
build-source attestation and staging receipt first. No image/build receipt is
established by the preparation or candidate PR (its packaging was skipped).
The accepted receipt must name candidate merge `b157caa...`, library tree hash
and its immutable attestation reference. `require_image` rejects absent/unpinned
or unequal receipts. A later reviewed pin change is needed; do not fill it from
the mutable default image or self-attest a guessed digest.

Proposed source files: `replay.py` and `pins.json`, with exact hashes from
`SOURCE-SHA256SUMS`. Proposed destination for each is the same basename under
`/root/ac-corpus-routes/report-candidate-c5/<reviewed-full-route-sha>/`.
Root:root owns directories (0755) and files (0444), with no symlinks or
group/world write bits. The `/root` parent retains its private permissions.
An isolated non-root container may read the mounted child directory; no secrets
or call data belong there. Documentation/tests stay in Git and the review packet.

Future operator commands, to be materialized with the exact reviewed SHA and
receipt on the parent (these are proposals, not permission to execute):

```bash
# root-owned version destination is new; if present, verify identical bytes only
sudo -n /usr/local/sbin/ac-root run -- install -d -o root -g root -m 0755 /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA
sudo -n /usr/local/sbin/ac-root run -- install -o root -g root -m 0444 scripts/report_candidate_c5/replay.py /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA/replay.py
sudo -n /usr/local/sbin/ac-root run -- install -o root -g root -m 0444 scripts/report_candidate_c5/pins.json /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA/pins.json
sudo -n /usr/local/sbin/ac-root run -- stat -c '%u:%g %a %n' /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA/replay.py /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA/pins.json
sudo -n /usr/local/sbin/ac-root run -- sha256sum /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA/replay.py /root/ac-corpus-routes/report-candidate-c5/REVIEWED_FULL_SHA/pins.json
```

Before installing, Root verifies the frozen Git source hashes, parent ownership,
no symlinks and whether the version destination already exists. Existing different
bytes cause refusal, not overwrite. Install into a new version path only; capture
every exit code, byte/hash/ownership read-back and operator run ID under AUT-63.
The later task must materialize these commands with the reviewed exact SHA.

Proposed offline container boundary: digest-only candidate image, default
entrypoint overridden with `/app/.venv/bin/python -I /route/replay.py`,
`--network none --read-only --cap-drop ALL --security-opt no-new-privileges`,
`--user 1002:1002`; mount versioned route and corpus read-only and one new
0700 acdev-owned output parent read/write. Use `--tmpfs /tmp:rw,noexec,nosuid`
and no host network/socket/home/env/secret mounts. Inspect the accepted image's
paths first; Dockerfile expectations are not a deployed receipt. Build/parsing
remain isolated offline; any external provider adapter requires its own reviewed
execution handoff after all admission receipts below. This source has none.

Rollback: select retained `/root/ac-corpus-runner/replay.py` explicitly for its
existing reviewed route, or stop selecting the candidate. Verify its recorded
hashes first. This proposal never changes that runner, active pointers, prior
outputs, production services or `/etc/ac-release/production.HELD-*`. Retain
every version/output; no history deletion is proposed. Releases use ac-release.

## Evaluation admission inventory and actual owners

`controlled-source-receipts.json` identifies all 24 exact manifest IDs and
reused source captures from attachment `4ca7744c-7bc2-4df3-a853-ecc368385037`
on [AUT-1785](/AUT/issues/AUT-1785), with verified extracted-text hashes and
available Google document revision IDs. SVAL Office capture has no immutable
Drive revision receipt; GOV-AUD's supplied capture has no revision metadata.
No fresh Drive access or newer controlled revision is claimed. Historical BRD
does not supersede current owner scope. The CTO preflight used here is revision
`d929d13c-58f3-4b66-8db1-2859c6570ce8` on the parent.

| Receipt | Current evidence | Required output / owner |
| --- | --- | --- |
| Classification | Candidate implementation and CTO preflight classify offline AI feedback under SVAL Gate 2 | CTO exact-source isolated evaluation admission; current preparation is not that review |
| SVAL Gate 2 | AC-SVAL-01 `11yOvguvLLj4WRi7-gJonWM3nSzkGk0NC`, capture SHA `e5d838c8...` (full hash in manifest) | Auditor/CTO: blinded methodology consistency and grounding >=95%, zero critical harmful advice, unsupported recommendations <1–2%, noninferiority; evaluation plan/receipt before quality claims |
| Governance | AC-GOV-AUD-001 `17Gs86tkRo4jr8XcqgMPyO-UojXeTANnY`, capture SHA `fa7c7dad...` | Existing Report delivery owner supplies exact purpose/provider/data-boundary receipt and current controlled-source acceptance; CTO routes professional gaps |
| All-call selection | OWNER-20261010-ALL-CALLS in retained corpus approval | Selection only; does not waive any row below |
| Consent/purpose | No per-call external-evaluation permission receipt in this preparation | Existing delivery owner supplies all-16 consent/purpose scope and revocation handling |
| Retention/deletion | No test-output retention/withdrawal receipt | Existing delivery owner supplies private-input/output expiry, deletion and lawful-retention boundary |
| Provenance/minimization | Retained C2/C4 pins; all authoritative roles missing | Existing delivery owner supplies source-bound snapshots/export and minimized external request policy |
| Provider/professional | No current provider terms/processing approval or applicable professional sign-off supplied | Existing delivery owner/CTO supplies provider retention/subprocessors/terms and qualified review or recorded applicability decision |
| Model/cap | Retained Gemini configuration; no current evaluation-model/cap authorization | Existing delivery owner obtains existing-authority receipt; owner-only money/settings decisions go through CEO, no new purchase/model/secret/credits |
| Image/staging | Candidate source review/merge only; no digest/staging receipt | Existing Report delivery owner on AUT-1783 provides immutable build-source/digest/staging evidence |

Concrete next test path: CTO reviews this exact source and offline proof; parent
routes the specific receipt/snapshot gaps to the existing Report delivery owner.
After independent review and documented test admission, parent may authorize a
bounded Root installation and private per-call replay handoff to the auditor.
Keep `coaching_revision_runtime_block("report-c5-v1")`; no settings workaround
is proposed. Existing Report delivery owns staging/production-version/What's new
closure. Completion of this preparation does not close product delivery.
