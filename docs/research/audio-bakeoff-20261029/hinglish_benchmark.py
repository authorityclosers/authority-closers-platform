# ruff: noqa: E402, S310, S603
"""MUCS public test split, six first rows; licence conservatively CC BY-SA 4.0."""

import argparse
import hashlib
import json
import resource
import time
import unicodedata
import urllib.request
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("model", choices=["prepare", "small", "turbo"])
a = p.parse_args()
if a.model == "prepare":
    url = "https://datasets-server.huggingface.co/rows?dataset=dianavdavidson%2FMUCS-Hinglish&config=default&split=test&offset=0&length=6"
    data = json.load(urllib.request.urlopen(url, timeout=60))
    samples = []
    for r in data["rows"]:
        row = r["row"]
        path = Path("data") / f"hinglish-{r['row_idx']}.wav"
        urllib.request.urlretrieve(row["audio"][0]["src"], path)
        samples.append(
            dict(
                path=str(path),
                id=row["segment_id"],
                reference=row["transcript"],
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    Path("hinglish-samples.json").write_text(json.dumps(samples, ensure_ascii=False))
    print(json.dumps(dict(prepared=len(samples))))
    raise SystemExit

import soundfile as sf
from faster_whisper import WhisperModel
from jiwer import cer, wer


def norm(text):
    return " ".join(
        "".join(
            c.lower() if not unicodedata.category(c).startswith("P") else " "
            for c in unicodedata.normalize("NFC", text)
        ).split()
    )


start = time.perf_counter()
name = {
    "small": "Systran/faster-whisper-small",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}[a.model]
model = WhisperModel(
    name,
    device="cpu",
    compute_type="int8",
    cpu_threads=2,
    num_workers=1,
    download_root="models",
    local_files_only=True,
)
cold = (time.perf_counter() - start) * 1000
refs = []
hyps = []
duration = 0
words = 0
valid_words = 0
examples = []
t = time.perf_counter()
cpu = time.process_time()
for row in json.loads(Path("hinglish-samples.json").read_text()):
    audio, rate = sf.read(row["path"], dtype="float32")
    duration += len(audio) / rate
    segments, _ = model.transcribe(
        audio,
        language="hi",
        beam_size=1,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    segments = list(segments)
    hyp = " ".join(s.text for s in segments)
    for seg in segments:
        for w in seg.words or []:
            words += 1
            valid_words += int(0 <= w.start <= w.end <= len(audio) / rate + 0.05)
    refs.append(norm(row["reference"]))
    hyps.append(norm(hyp))
    examples.append(
        dict(
            id=row["id"],
            reference=refs[-1],
            hypothesis=hyps[-1],
            words=[
                dict(start_ms=w.start * 1000, end_ms=w.end * 1000, word=w.word)
                for seg in segments
                for w in seg.words or []
            ],
        )
    )
elapsed = time.perf_counter() - t
print(
    json.dumps(
        dict(
            engine=a.model,
            language="hinglish",
            n=len(refs),
            audio_ms=duration * 1000,
            cold_model_ms=cold,
            inference_ms=elapsed * 1000,
            rtf=elapsed / duration,
            cpu_seconds_per_minute=(time.process_time() - cpu) / duration * 60,
            peak_ram_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            wer=wer(refs, hyps),
            cer=cer(refs, hyps),
            word_count=words,
            word_times_in_bounds=valid_words,
            word_timing_accuracy="unmeasured_no_reference_word_alignment",
            examples=examples,
        ),
        ensure_ascii=False,
    )
)
