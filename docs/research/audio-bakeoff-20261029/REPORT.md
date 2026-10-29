# Audio engine bake-off — 29 October 2026

**₹0/min provider saving from VAD/diarization alone. Local ASR is not recommended for adoption: the measured multilingual quality is insufficient.** The richer local worker is implemented, disabled, with AudioAtlas fallback.

## Measured CPU results; conditional ₹ estimates

| Engine / input | Audio ms | Processing ms | RTF | Peak RSS MiB | CPU seconds / audio-minute | Quality | Estimated ARM ₹ / audio-minute |
|---|---:|---:|---:|---:|---:|---|---:|
| AudioAtlas / synthetic | 45,660 | 1,282 | 0.0281 | 50.0 | 1.09 | DSP only | ₹0.0018–0.0036 |
| Segmentation + embedding (WeSpeaker) / synthetic.wav | 45,660 | 10,051 | 0.2201 | 213.8 | 25.83 | DER 17.58% | ₹0.0140–0.0280 |
| Segmentation + embedding (WeSpeaker) / ami.wav | 120,000 | 18,341 | 0.1528 | 324.7 | 18.31 | DER 29.16% | ₹0.0097–0.0194 |
| Segmentation + embedding (ERes2Net) / synthetic.wav | 45,660 | 11,106 | 0.2432 | 288.2 | 29.17 | DER 17.58% | ₹0.0155–0.0309 |
| Segmentation + embedding (ERes2Net) / ami.wav | 120,000 | 20,873 | 0.1739 | 504.1 | 20.85 | DER 28.66% | ₹0.0111–0.0221 |
| AudioAtlas + optional worker / synthetic | 45,660 | 12,632 | 0.2766 | ≤324.7† | 31.45 | sidecar smoke passed | ₹0.0176–0.0352 |
| Silero threshold 0.3 / synthetic.wav | 45,660 | 309 | 0.0068 | 78.4 | 0.80 | miss 12.52%; FA 0.00% | ₹0.0004–0.0009 |
| Silero threshold 0.3 / ami.wav | 120,000 | 720 | 0.0060 | 142.5 | 0.72 | miss 30.69%; FA 0.84% | ₹0.0004–0.0008 |
| Silero threshold 0.5 / synthetic.wav | 45,660 | 303 | 0.0066 | 78.7 | 0.79 | miss 14.72%; FA 0.00% | ₹0.0004–0.0008 |
| Silero threshold 0.5 / ami.wav | 120,000 | 673 | 0.0056 | 142.7 | 0.66 | miss 45.64%; FA 0.19% | ₹0.0004–0.0007 |

† Prototype child maximum RSS is a conservative inherited high-water mark from an earlier comparison subprocess in the same harness; it is an upper bound, not an isolated model peak. A fresh-process AudioAtlas rerun supplies its uncontaminated child peak. RAM for sequential models is a process high-water mark, not independent per-language resident memory.

**Costs are scenarios**, using ₹0.0636 per instance-minute and ARM at 1–2× measured x86 RTF; no ARM execution occurred. Excludes burst CPU credits and shared-service contention. The lower rows are not guaranteed production prices.

| ASR / language | Clips | Audio ms | Inference ms | RTF | Peak RSS MiB | CPU seconds / audio-minute | WER | CER | Estimated ARM ₹ / audio-minute |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| small / hinglish | 6 | 47,025 | 177,507 | 3.775 | 1255.2 | 238.21 | 81.55% | 58.90% | ₹0.2401–0.4801 |
| turbo / hinglish | 6 | 47,025 | 71,559 | 1.522 | 2026.8 | 107.73 | 50.49% | 39.63% | ₹0.0968–0.1936 |
| small / hi | 6 | 66,840 | 89,474 | 1.339 | 1424.1 | 85.27 | 62.42% | 21.97% | ₹0.0851–0.1703 |
| small / mr | 6 | 66,240 | 303,147 | 4.576 | 1539.1 | 288.31 | 110.64% | 71.76% | ₹0.2911–0.5821 |
| small / en | 6 | 52,280 | 17,803 | 0.341 | 1564.3 | 24.11 | 7.26% | 2.26% | ₹0.0217–0.0433 |
| tiny / hi | 6 | 66,840 | 28,187 | 0.422 | 322.6 | 26.19 | 117.45% | 105.39% | ₹0.0268–0.0536 |
| tiny / mr | 6 | 66,240 | 18,683 | 0.282 | 324.0 | 17.60 | 111.70% | 95.48% | ₹0.0179–0.0359 |
| tiny / en | 6 | 52,280 | 2,154 | 0.041 | 324.0 | 3.14 | 18.55% | 6.91% | ₹0.0026–0.0052 |
| turbo / hi | 6 | 66,840 | 122,287 | 1.830 | 2526.3 | 125.21 | 30.20% | 8.55% | ₹0.1164–0.2327 |
| turbo / mr | 6 | 66,240 | 77,302 | 1.167 | 2526.3 | 83.34 | 85.11% | 29.80% | ₹0.0742–0.1484 |
| turbo / en | 6 | 52,280 | 65,182 | 1.247 | 2526.3 | 91.48 | 5.65% | 1.97% | ₹0.0793–0.1586 |

| Fresh-process cached startup | Import ms | Model-load ms | Ready ms |
|---|---:|---:|---:|
| small | 267 | 8,821 | 9,088 |
| turbo | 145 | 16,737 | 16,883 |

Silero model construction: 174 ms; ERes2Net diarization pipeline: 502 ms; WeSpeaker pipeline: 451 ms. These exclude interpreter imports. Tiny cached model load: 603 ms. ASR first-load timings in raw rows include downloads where applicable (small 10,806 ms; turbo 62,028 ms); the separate cached-start table excludes downloads but retains warm OS page cache. Cold disk, HTTP startup and deployment startup are not measured.

small Hinglish emitted 119 words; 119 times were structurally in bounds. Actual boundary accuracy remains unmeasured.

turbo Hinglish emitted 111 words; 111 times were structurally in bounds. Actual boundary accuracy remains unmeasured.

## Recommendation from this run

Adopt the **disabled local sidecar architecture for evaluation**, retaining canonical AudioAtlas, and keep the current approved C2 transcription route. Silero + a small ONNX diarizer adds the missing speech/speaker evidence within this machine’s memory. It is not an accepted quality replacement, and it does not replace sales reasoning. Whisper turbo is the strongest of the three measured local ASR checkpoints on the sampled monolingual sets, but Marathi WER 85.1% and Hindi 30.2% disqualify automatic adoption. Tiny/small are not acceptable cheap Indic shortcuts. Benchmark Indic-specific models and a quantized native ARM runtime next, within existing hardware and gated access.

On a 30-minute planning example, prior C2 spend is ₹4.215. Turbo Hindi compute alone would be about ₹3.49–₹6.98, before diarization, alignment, retries or CPU surplus: **local does not automatically mean cheaper**. The same 45,660 ms public input took 1,352 ms with existing AudioAtlas versus 12,632 ms with the richer path in the worker proof. The latter supplies capabilities AudioAtlas does not have; it is not a DSP throughput improvement.

## What the measurements can decide

These are **smoke benchmarks**, not a sales-call acceptance test or a claim of a production-ready winner. All inference ran on the owner's existing Sydney rehearsal server, 2 vCPU / 3,812 MiB, Xeon Platinum 8488C, CPU-only. No resize, GPU, API inference credits, real calls, or customer files were used. The fictional stack was stopped with its existing `~/rehearsal/compose.sh down` wrapper because `docker compose down` in the parent had no default configuration. No `-v` flag or deletion was used; data and volumes remain. The stack is intentionally left stopped as instructed.

Public inputs:

- [Google FLEURS](https://huggingface.co/datasets/google/fleurs), CC BY 4.0: first six test rows each of `hi_in`, `mr_in`, `en_us`; 66,840 ms Hindi, 66,240 ms Marathi, 52,280 ms English. FLEURS has no `en_in` config. This English result does not certify Indian English. Selection was deterministic before observing accuracy; only six clips/language, no uncertainty or domain-general claims.
- [AMI ES2004a](https://groups.inf.ed.ac.uk/ami/corpus/), mixed headset audio, first 120,000 ms. References from [pyannote AMI setup](https://github.com/pyannote/AMI-diarization-setup/tree/main/only_words/rttms/test), word-only RTTM, 4 speakers. This is a meeting comparator; the two-speaker prototype is separately tested on a synthetic mix. The AMI corpus is CC BY 4.0.
- Synthetic two-speaker mix: first Hindi FLEURS male and female clips in the selected rows, each repeated three times, alternating with 500 ms gaps; 45,660 ms. Reference labels cover the **whole clip extents**, including internal silence. Its 17.6% DER is therefore an extent-proxy error, not a speech-annotated conversational DER or an independent six-turn sample. AMI has the actual annotated speech reference.
- [MUCS-Hinglish](https://huggingface.co/datasets/dianavdavidson/MUCS-Hinglish), first six test rows, technical spoken tutorials, not sales calls. [Original OpenSLR 104](https://www.openslr.org/104/) says CC BY-SA 4.0; the mirror says CC BY 4.0. Conservatively retain the original attribution/share-alike terms. No corpus redistributed in Git.

Timing: wall-clock inference ms, process CPU time (all threads), peak RSS via `getrusage`; native baseline also includes child CPU/RSS. Models run sequentially; one ASR engine per fresh process. ASR uses CPU int8, two threads, beam 1, word timestamps, no VAD trimming, no previous-text conditioning; WAV read to float32 before ASR to avoid a PyAV 19 / faster-whisper metadata API mismatch. VAD and diarization operate on unmodified 16 kHz speech. Data preparation peaked at 2,624,508 KiB; it is excluded from inference cost, and did not resize the machine. Short setup/download activity was not a controlled dedicated-host load test; repeat performance under steady production load before adoption.

WER/CER use NFC Unicode, lower-case, punctuation-to-space, whitespace collapse; numerals and script are preserved. WER above 100% is possible from insertions. Romanized output is scored against the required Devanagari reference, not forgiven as a correct product transcript. Word timestamps being in bounds is a structural check, **not word-alignment accuracy**; the sampled corpora do not supply reference word boundaries.

DER uses optimal global speaker permutation, 10 ms frames, zero collar, includes overlap, and divides missed + false-alarm + confused speaker time by reference speaker time. No production confidence score derives from this metric. VAD miss and false-alarm fractions have different denominators (reference speech / reference non-speech respectively). Default and 0.3 thresholds are compared on the same excerpt: threshold selection must be validated on a separate held-out set.

## What call analysis needs

| Requirement | Required evidence and calculation | Candidate / constraint |
|---|---|---|
| Speech and silence | Timestamped speech regions, retained source clock; silence = call duration minus union of speech | Silero ONNX. Tune for quiet speech; distinguish music/noise from speech. Do not delete silence from the canonical clock. |
| Who spoke when | Anonymous speaker turns; overlap regions; confirmed role mapping separately | ONNX segmentation + speaker embedding/clustering; compare Community-1. Two speakers is an assumption, not speaker identity or waveform separation. Conferences/transfer/hold music need abstention. |
| Talk ratio | Union each speaker's intervals, divide by total speaker-time; overlap counts for both | Local deterministic math, no score. Label whether denominator includes silence or overlap. Seller/prospect labels require verified mapping. |
| Interruptions | Overlap onset is observable; interruption intent/turn ownership requires context | Publish overlap events initially. Do not count every backchannel or simultaneous laugh as an interruption. |
| Longest monologue | Merge same-speaker contiguous intervals; distinguish contiguous speech from long turns with pauses | Prototype reports longest contiguous turn only. A product monologue threshold requires owner/coaching definition; do not invent it. |
| Response latency | Non-overlapping speaker-change gap, ms | Prototype reports raw non-overlapping gaps; overlapping replies and backchannels need separate event handling. |
| Pitch / energy | Robust F0/voicing, intensity, range, clipping; within-speaker and within-recording interpretation | Keep AudioAtlas descriptors for now; evaluate Praat/Parselmouth as a separate DSP replacement. Mixed mono overlap cannot be attributed reliably to an individual speaker. Absolute loudness depends on microphone/AGC. |
| Pace / filler words | Timestamped word transcript, language-aware normalization and approved filler lexicon | Local ASR + validated aligner; WPM needs spoken-time vs elapsed-time definition. Acoustic energy cannot produce words/minute. Hindi/Marathi filler/backchannel lists require coach review. |
| hi/mr/en/Hinglish word transcript | Correct words AND scripts AND timings, numerals, names, currencies, code-switching | Quantized multilingual Whisper turbo candidate; IndicConformer/IndicWhisper comparison required. No mistranslation/English-only distil substitution. |
| Tone / emotion cues | Descriptive pitch/energy/speaking-rate changes with uncertainty and channel/noise context | Signals only. English acted-emotion labels are not validated Indic sales emotion. No confident/stressed/personality/skill score from pitch or energy. |

## Current source path and external exposure

Read at workbench source pin `dc29acf4e8a2faa96be7e212ce70197b55ea60c7` (files read, not a deployment attestation):

1. `signals.py` uses bounded ffprobe/ffmpeg on a private snapshot, 16 kHz hosted profile, 40 ms windows / 10 ms hop. It retains decoded-track timing and explicitly does **not** certify codec-delay/container/video clock mapping. `atlas_dsp.cpp` performs YIN and spectral/energy descriptors. This is not VAD, ASR, diarization or source separation.
2. `worker.py` verifies source SHA/bytes, persists native `features.aaf` plus C1 payload and cache identity. `alignment.py` explicitly validates the AudioAtlas format/profile/support/hash/native receipt. The existing checkpoint cannot be replaced by an arbitrary diarization JSON without changing its provenance contract.
3. C2 provider paths in `providers.py` include Gemini audio, Scribe and Deepgram. `gemini_audio.py`'s route uses Gemini 3.1 Flash-Lite: mono 16 kHz / 32 kbps MP3. Beyond 15 minutes it uses 10-minute parts with 30-second overlaps (up to eight concurrently); audio may be inline or uploaded through the provider file endpoint. The prompt requests verbatim Devanagari Hindi/Marathi, Latin English, anonymous speaker turns and MM:SS times. Those are provider estimates, not forced word alignment.
4. `reporting_pipeline.py` constructs C3 alignment from C1 + C2, then C4 fact extraction and C5 coaching/report tasks from transcript and approved context/profile/derived facts. Those text/model calls remain necessary if local ASR replaces C2. `measurement_view.py` checks provenance before showing measurements. `signals.fuse_segments` refuses mixed-overlap speaker attribution and requires matching source digest and decoded clock. `brain4.py` explicitly treats delivery/audio evidence as insufficient from transcript alone.

This review exercised **none** of those live provider paths. Existing production consent/provider approvals are not extended to a new provider, new retained transcript, emotion inference, or official score by this task. No provider keys or real recording paths were accessed. AC-SVAL's gold-set report was read for context; no new official scoring was built.

## Cost model: estimates, not an ARM measurement

Planning inputs: t4g.medium Sydney Linux on-demand **US$0.0424/hour** as a conditional planning rate; INR **₹90/US$ is an explicit scenario**, not an FX quote. Thus an otherwise dedicated instance minute costs ₹0.0636. ARM speed multiplier `k=1..2` is a sensitivity range, not a validated x86-to-ARM conversion:

`allocated ₹/audio-minute = measured x86 RTF × k × 0.0636`.

Use the actual contracted price and exchange rate before a purchasing decision. AWS's [T4g specs](https://aws.amazon.com/ec2/instance-types/t4/) give 2 vCPU, 4 GiB, 20% baseline per vCPU and 24 credits/hour: sustained free baseline CPU budget is only **1,440 CPU-seconds/hour**, before API/database/other workers. The base-price table excludes CPU surplus credits, EBS, transfers, model download/storage, idle time, retries and API contention. [AWS burstable billing](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode.html) must be included for sustained high CPU, or standard mode throttling will increase latency.

On dev `ac`, no heavy inference ran, as ordered. It is a 4-vCPU x86 AMD EPYC 9354P VM; we do not have an allocated hourly invoice in this task. Incremental prepaid-idle-compute cash spend is ₹0 while spare capacity lasts, **not free capacity**. To estimate allocated dev cost, let H be its ₹/hour allocation: `₹/audio-minute = x86 RTF × k_ac × H / 60`. At an illustrative H=₹4/hour and k_ac=1, multiply RTF by **₹0.06667**. This is explicitly conditional; an actual ac speed/₹ claim would require the disallowed heavy ac benchmark and the host invoice.

External savings:

- Phase (a), local VAD/diarization only: **₹0.00/min of provider spend removed**. C2 still sends audio; the disabled prototype also still runs the existing C1 DSP. It adds capability/cost, not a demonstrated speedup over the native DSP.
- Phase (b), approved local ASR replacing C2: remove C2 audio ingestion/transcription spend, not C4/C5 sales reasoning. Owner baseline is ~₹0.27/min all-in. Upper bound removed is ₹0.27/min; actual savings need route-specific token receipts. No billing/receipt semantics were edited.
- Existing code-adjacent cost research (`docs/research/2026-10-20-analysis-cost/results/scores/fits.md`) fitted Gemini Flash-Lite ASR as **₹0.090/call + ₹0.1375/min**, from that older experiment. This is a prior, not today's invoice: a 30-minute illustrative call gives ₹0.1405/min C2. Net saving is `actual C2/min – local compute/min – alignment/diarization/retries/min`. Leave the remaining reasoning bill in place. No claim that VAD silence trimming proportionally reduces audio billing, or that shrinking audio permits dropping canonical silence.

## Adoption plan and prototype

**(a) Prototype delivered disabled; activate only after acceptance.** Use Silero ONNX for speech regions, ONNX speaker segmentation + embedding + deterministic interval math for anonymous turn measurements. Keep AudioAtlas for pitch/energy and canonical C1 compatibility. Prefer a verified dual-channel speaker mapping when recording channels are actually isolated; never assume stereo means seller/prospect. Community-1 is the quality challenger after legitimate gated-model access and exact component licence review. The currently measured diarization/VAD errors are too high to call this an accepted replacement.

The new `audio_bakeoff.worker.inspect_with_local_audio(..., enabled=False)` adapter is deliberately not wired into the active service. With the flag off, it returns the exact normal AudioAtlas result with no experimental dependencies loaded. With explicit opt-in, it decodes a bounded mono PCM copy and runs the optional helper in a separate bounded subprocess; it writes `local-audio-experiment.json` with source digest, decoded clock, model hashes, VAD regions, anonymous turns and raw timing summaries. A failed optional path leaves the C1 result and writes a constant fallback status. No schema/DB/API/provider/UI change. Prototype ceiling is **600,000 ms**, two anonymous speakers, two CPU threads, 300,000 ms helper deadline, bounded decode/output. It does not claim the app's two-hour maximum is validated.

Model root is operator-provisioned; files must match compiled-in SHA-256 pins. The helper does not download weights, transcribe, assign sales roles, or generate scores. Optional dependencies are recorded separately, not added to the normal app dependency manifest. Before enabling on real recordings: network-denied/read-only-model worker isolation and OS memory limit, 2-hour streaming/chunk/speaker reconciliation, independent quiet/noisy/overlap evaluation, exact weight terms/consent/retention/provenance checks, and reviewed report read contract. The current subprocess bounds are not an OS sandbox.

**(b) Local ASR remains gated.** Benchmark the selected multilingual checkpoint on larger held-out Hindi/Marathi/Hinglish/Indian-English sets before routing any real call locally or persisting a new transcript. Compare IndicConformer/IndicWhisper with proper access; do not install an FP32 large model that exceeds the box. Sequentially unload ASR/diarizer/aligner, one worker job at a time. Validate currency, phone numbers, names, code-switch script, hallucinations in silence, overlap and actual word boundary error. Only after owner/gate approval, add a new C2 recipe/receipt/cache identity and retain the previous provider fallback. Do not impersonate a Gemini native response or mutate old transcripts/audit history.

**(c) Shadow then adopt.** Run public smoke/full held-out tests, then explicitly approved in-environment real-call shadow with consent/retention/provenance. Compare the same source/version against existing C2 and human corrections; measure latency, WER/CER, DER, boundary error and downstream report factuality. Define product acceptance thresholds with owner/coach rather than inventing protected semantics. Owner/operator owns staging/production shipping. No production change was made by this work.

## Evidence, reproduction, limits

`docs/research/audio-bakeoff-20261029/` contains the source survey, benchmark harnesses, sanitized measured results, dependency versions and hashes. Full public references/hypotheses and word-timing examples stay in the scratch results and the isolated AWS benchmark folder, not the application database. `ARTIFACTS` in the new engine pins Silero, segmentation and embedding bytes. Reproduction downloads source public models/datasets, runs `benchmark.py prepare`, then `vad`, `diar`, `tiny`, `small`, `turbo` sequentially with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2`; the additional scripts cover cached load, Hinglish and the actual worker adapter. Do not run model work on ac.

Not measured: actual t4g/ARM execution, Indian English, independent sales-domain/generalizable Hinglish quality, forced word-alignment error, source separation, calibrated emotion, every surveyed candidate, 2-hour memory/latency, multi-job concurrency or all-in production cost. Gated models were not bypassed; models without a verified downloadable local checkpoint were surveyed only. Full FP32 large-v3 weights alone are ~6.2 GB and exceed the 3.8 GB box; several full NeMo/WhisperX/IndicConformer configurations also lack safe combined residency headroom. No instance resize or purchase was made.

AC Orchestra's supplied Windows skill path is unavailable on this Linux host, no corresponding local skill was found, and no authorized Pro browser tool was available. No cloud handoff was used or treated as evidence. Hosted workbench CI was attempted and waited on the active v1.7.0 release hold; the waiting task was stopped without bypassing that hold. Final isolated AWS validation passed 14 focused tests and repository-configured Ruff/format checks. The isolated pytest run had a cache-directory warning under /dev from its minimal config; no test failed. Earlier local validation passed ten focused tests, strict mypy on the three implementation modules, Ruff, and the required HTTP import. Local final-check queue entries were stopped while both shared slots were occupied; final checks ran on the now-idle AWS box instead. CI remains separately pending until a run is actually green.
