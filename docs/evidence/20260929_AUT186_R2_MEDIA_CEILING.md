# AUT-186: approved R2 media ceiling

Owner decision: [option A, AUT-10, 29 Sep 2026](/AUT/issues/AUT-10#comment-495303be-6aee-41ae-983f-d5520e8dc799); [CEO decisions](/AUT/issues/AUT-10#comment-f1117fe3-c64a-44d7-8b88-33951e01a442).

Policy: 107,374,182,400 bytes = 100 GiB ceiling; 80,530,636,800 bytes = 75 GiB warning. Only the periodic guard fails on warnings; backups retain the hard-limit and projection checks. At the shared ceiling database backups stop too; the 5.25 GiB reservation can refuse writes earlier. Operation ceilings, six-month foundation window and separate 32 GiB acquisition cap are unchanged.

[Cloudflare Standard pricing](https://developers.cloudflare.com/r2/pricing/): $0.015/GB-month after 10 GB free. At steady 21 GB, `(21 - 10) × .015 = $0.165`, about $0.17/month. At 100 GiB, `(107.3741824 - 10) × .015 = $1.460612736`, about $1.46/month before unit rounding (about $1.47 billed), excluding other account usage and operations.

First snapshot: approximately 20 GB media from AUT-10 plus other included sources and metadata. [Restic 0.16.4 pack sizing](https://restic.readthedocs.io/en/v0.16.4/047_tuning_backup_parameters.html#pack-size) defaults to 16 MiB: `ceil(20e9 / 2^24) = 1,193` data-pack PUTs, an approximate Class A baseline plus tree/index/snapshot/lock PUTs, LISTs, maintenance, retries and multipart overhead. No compression credit; no pack override in the committed callers.

Timeout evidence: [restic 0.16.4 FAQ](https://restic.readthedocs.io/en/v0.16.4/faq.html#will-restic-resume-an-interrupted-backup) documents reuse of indexed uploaded data after interruption. [Prune](https://restic.readthedocs.io/en/v0.16.4/060_forget.html) removes data unreferenced by retained snapshots. The existing daily job prunes before backup, so after its 90-minute timeout the next scheduled run can discard incomplete upload progress. Source media and completed snapshots survive, but automatic upload resumption is not assured. The card requires a CTO decision before merge; timeout and maintenance order are outside this change.

Fictional [AUT-628 retention-v2 forecast](/AUT/issues/AUT-628#document-media-sizing), independently reproduced offline:

| kbit/s | `10 × 730 × 1,800 × bitrate × 1,000 / 8 / 2^30` live GiB | `10 × 910 × 1,800 × bitrate × 1,000 / 8 / 2^30 + 20e9 / 2^30` retained GiB |
| --- | ---: | ---: |
| 32 | 48.95 | 79.65 |
| 128 | 195.80 | 262.71 |

The 180-day tail approximates the unchanged six-month backup window. Identical live snapshot bytes count once; no unmeasured compression saving; other stores and overhead are additional. The lower retained forecast exceeds the warning, the higher exceeds the shared hard ceiling. More than 100 GiB requires a separate owner-approved decision through the CEO; no retention shortening or new spending is authorized here.

Verification: evaluator boundary/missing-invalid-policy/projection tests; committed PostgreSQL policy parsing and unchanged 5.25 GiB logical projection; static periodic-only flag checks; foundation lint and repository format/lint/type gates. Commands and results are recorded on the task/PR after execution. All fixtures and sizing constants are fictional; no host/provider calls or deployment occurred. Historical `FINAL_HANDOFF.md` and `IMPLEMENTATION_STATUS.md` remain unchanged and are superseded only for this ceiling by this note.
