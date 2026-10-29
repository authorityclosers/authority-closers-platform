# Audio bake-off, 29 October 2026

Owner-authorized public-data experiment. The report is mirrored here when measurements
finish; the requested working report is `/home/acdev/scratch/audio-bakeoff-20261029/REPORT.md`.
No model binary, corpus audio, real call, provider key or transcript database is committed.

- `SURVEY.md`: primary-source shortlist, weight/code licences, hardware/language caveats.
- `benchmark.py`: FLEURS first six test rows/language, synthetic two-voice mix,
  AMI ES2004a first 120 seconds, CPU resource timings and quality metrics.
- `hinglish_benchmark.py`: MUCS first six test rows, actual code-switching and structural
  word-time checks (not word-time accuracy).
- `cold_load.py`: fresh process with cached weights (not cold disk/page cache).
- `finish_benchmark.py`: second embedding comparator, native AudioAtlas baseline and
  actual optional-worker smoke with public input.
- `results.json`: sanitized numeric evidence; full public hypotheses remain in scratch/AWS.
- `hashes.txt`, `requirements.txt`, `arm-wheels.json`: reproducibility records.

Run model benchmarks only on the authorized AWS rehearsal box. Library installation
uses a dedicated virtual environment. Source models: Silero upstream commit
60b7ffa243625ebdc1070275a29f18c87843786a; ONNX segmentation and embeddings from the
k2-fsa/sherpa-onnx public release assets documented in SURVEY. Match every artifact
against hashes.txt before loading. Model weights must be provisioned read-only; the
new worker never downloads them. Optional runtime: sherpa-onnx==1.12.26,
sherpa-onnx-core==1.12.26, numpy==2.2.6, soundfile==0.13.1.

The production service does not import this experiment. Call
`audio_bakeoff.worker.inspect_with_local_audio(media, new_outdir, model_root=..., enabled=True)`
only from an explicitly opted-in isolated worker. Default `enabled=False` runs the
existing AudioAtlas path only. A sidecar is not a canonical C1 checkpoint or an
approval to process real calls, retain a transcript or infer a score.

`CHECKS.md` records validation and its limits; `asr-hashes.txt` pins the benchmark
ASR weights and immutable Hugging Face snapshot revisions. ARM wheels establish
packaging availability only. No actual ARM inference or deployment was performed.
