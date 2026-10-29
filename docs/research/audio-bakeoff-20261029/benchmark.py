# ruff: noqa: E402, S310, S603
"""AWS-only public corpus smoke benchmark. Run each engine in a fresh process."""

import argparse
import io
import itertools
import json
import os
import resource
import time
import unicodedata
from pathlib import Path

start = time.perf_counter()
cpu_start = time.process_time()
p = argparse.ArgumentParser()
p.add_argument("engine", choices=["prepare", "vad", "diar", "tiny", "small", "turbo"])
a = p.parse_args()
root = Path.cwd()


def emit(result):
    result.update(
        elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
        process_cpu_ms=round((time.process_time() - cpu_start) * 1000, 2),
        peak_ram_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


def normalize(text):
    return " ".join(
        "".join(
            c.lower() if not unicodedata.category(c).startswith("P") else " "
            for c in unicodedata.normalize("NFC", text)
        ).split()
    )


import numpy as np
import soundfile as sf

if a.engine == "prepare":
    import pyarrow.parquet as pq

    manifest = []
    for lang in ["hi_in", "mr_in", "en_us"]:
        rows = next(
            pq.ParquetFile(root / "data" / f"{lang}.parquet").iter_batches(batch_size=6)
        ).to_pylist()
        for i, row in enumerate(rows):
            wav, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
            path = f"data/{lang}-{i}.wav"
            sf.write(path, wav, rate)
            manifest.append(
                dict(
                    path=path,
                    language=lang[:2],
                    reference=row["transcription"],
                    gender=row["gender"],
                    row=i,
                    id=row["id"],
                    duration_ms=len(wav) / rate * 1000,
                )
            )
    Path("samples.json").write_text(json.dumps(manifest, ensure_ascii=False))
    # Two voices, each repeated three times, alternate with a 500 ms gap.
    pair = [next(r for r in manifest if r["language"] == "hi" and r["gender"] == g) for g in [0, 1]]
    clips = [sf.read(r["path"], dtype="float32")[0] for r in pair]
    pieces = []
    ref = []
    offset = 0
    for i in range(6):
        x = clips[i % 2]
        pieces.extend([x, np.zeros(8000, dtype="float32")])
        ref.append([offset / 16000, (offset + len(x)) / 16000, i % 2])
        offset += len(x) + 8000
    sf.write("data/synthetic.wav", np.concatenate(pieces), 16000)
    Path("synthetic-reference.json").write_text(json.dumps(ref))
    emit(dict(prepared=len(manifest), synthetic_reference="clip extent, includes internal silence"))
    raise SystemExit

if a.engine in ["vad", "diar"]:
    import sherpa_onnx as s

    t = time.perf_counter()
    if a.engine == "vad":
        c = s.VadModelConfig()
        c.silero_vad.model = "models/silero.onnx"
        c.num_threads = 2
        c.sample_rate = 16000
        c.silero_vad.threshold = float(os.environ.get("VAD_THRESHOLD", "0.5"))
        model = s.VoiceActivityDetector(c, buffer_size_in_seconds=120)
    else:
        c = s.OfflineSpeakerDiarizationConfig(
            segmentation=s.OfflineSpeakerSegmentationModelConfig(
                pyannote=s.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model="models/sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx"
                ),
                num_threads=2,
            ),
            embedding=s.SpeakerEmbeddingExtractorConfig(
                model=os.environ.get("DIAR_EMBEDDING", "models/embedding.onnx"), num_threads=2
            ),
            clustering=s.FastClusteringConfig(num_clusters=2),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        model = s.OfflineSpeakerDiarization(c)
    cold = (time.perf_counter() - t) * 1000
    for path in ["data/synthetic.wav", "data/ami.wav"]:
        x, rate = sf.read(path, dtype="float32")
        x = x[: 16000 * 120]
        if x.ndim > 1:
            x = x.mean(axis=1)
        t = time.perf_counter()
        cpu = time.process_time()
        if a.engine == "vad":
            model.reset()
            for i in range(0, len(x), 512):
                model.accept_waveform(x[i : i + 512])
            model.flush()
            pred = []
            while not model.empty():
                seg = model.front
                pred.append([seg.start / 16000, (seg.start + len(seg.samples)) / 16000, 0])
                model.pop()
        else:
            c.clustering.num_clusters = 2 if "synthetic" in path else 4
            model = s.OfflineSpeakerDiarization(c)
            pred = [[r.start, r.end, r.speaker] for r in model.process(x).sort_by_start_time()]
        elapsed = time.perf_counter() - t
        cpus = time.process_time() - cpu
        if "synthetic" in path:
            ref = json.loads(Path("synthetic-reference.json").read_text())
        else:
            ref = []
            for line in Path("data/ami.rttm").read_text().splitlines():
                r = line.split()
                ref.append([float(r[3]), float(r[3]) + float(r[4]), r[7]])
        # 10ms frame DER, zero collar, include overlap; optimal global speaker permutation.
        grid = np.arange(0, len(x) / rate, 0.01)

        def masks(rows, grid=grid):
            speakers = sorted(set(r[2] for r in rows), key=str)
            return np.array(
                [[any(b <= v < e and z == sp for b, e, z in rows) for v in grid] for sp in speakers]
            )

        rr = masks(ref)
        hh = masks(pred)
        if a.engine == "vad":
            r = rr.any(axis=0)
            h = hh.any(axis=0) if len(hh) else np.zeros(len(grid), bool)
            metrics = dict(
                vad_miss_fraction=float(np.sum(r & ~h) / max(1, np.sum(r))),
                vad_false_alarm_fraction=float(np.sum(~r & h) / max(1, np.sum(~r))),
            )
        else:
            n = max(len(rr), len(hh))
            rr = np.pad(rr, ((0, n - len(rr)), (0, 0)))
            hh = np.pad(hh, ((0, n - len(hh)), (0, 0)))
            nr = rr.sum(axis=0)
            nh = hh.sum(axis=0)
            correct = max(
                np.minimum(nr, nh).sum()
                if n == 0
                else sum((rr[i] & hh[j]).sum() for i, j in enumerate(perm))
                for perm in itertools.permutations(range(n))
            )
            error = np.maximum(nr, nh).sum() - correct
            metrics = dict(der=float(error / max(1, nr.sum())), collar_ms=0, overlap_included=True)
        emit(
            dict(
                engine=a.engine,
                path=path,
                audio_ms=len(x) / rate * 1000,
                cold_model_ms=cold,
                vad_threshold=float(os.environ.get("VAD_THRESHOLD", "0.5"))
                if a.engine == "vad"
                else None,
                inference_ms=elapsed * 1000,
                rtf=elapsed / (len(x) / rate),
                cpu_seconds_per_minute=cpus / (len(x) / rate) * 60,
                prediction=pred,
                **metrics,
            )
        )
else:
    from faster_whisper import WhisperModel
    from jiwer import cer, wer

    name = {
        "tiny": "Systran/faster-whisper-tiny",
        "small": "Systran/faster-whisper-small",
        "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    }[a.engine]
    t = time.perf_counter()
    model = WhisperModel(
        name,
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
        download_root="models",
    )
    cold = (time.perf_counter() - t) * 1000
    samples = json.loads(Path("samples.json").read_text())
    for lang in ["hi", "mr", "en"]:
        refs = []
        hyps = []
        total = 0
        t = time.perf_counter()
        cpu = time.process_time()
        for row in [r for r in samples if r["language"] == lang]:
            audio, _ = sf.read(row["path"], dtype="float32")
            segments, info = model.transcribe(
                audio,
                language=lang,
                beam_size=1,
                word_timestamps=True,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            hyp = " ".join(seg.text for seg in segments)
            refs.append(normalize(row["reference"]))
            hyps.append(normalize(hyp))
            total += row["duration_ms"] / 1000
        elapsed = time.perf_counter() - t
        cpus = time.process_time() - cpu
        emit(
            dict(
                engine=a.engine,
                language=lang,
                n=len(refs),
                audio_ms=total * 1000,
                cold_model_ms=cold,
                inference_ms=elapsed * 1000,
                rtf=elapsed / total,
                cpu_seconds_per_minute=cpus / total * 60,
                wer=wer(refs, hyps),
                cer=cer(refs, hyps),
                references=refs,
                hypotheses=hyps,
            )
        )
