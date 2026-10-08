# Fictional phone audio

These one-second files contain no recorded voices. `tone.*` is a generated
440 Hz mono tone. The AMR fixtures contain 50 artificial mode-0 frames with
all-zero payload bits (12 payload bytes for NB; 17 for WB), preceded by the
AMR file magic. They exercise the native AMR decoders without an AMR encoder
package or downloaded customer audio.

Generation (ffmpeg 6.1.1; no new packages):

```python
from pathlib import Path
import subprocess

fixtures = Path("tests/fixtures/phone_audio")
for name, magic, size in [
    ("synthetic-nb.amr", b"#!AMR\n", 12),
    ("synthetic-wb.awb", b"#!AMR-WB\n", 17),
]:
    (fixtures / name).write_bytes(magic + (b"\x04" + bytes(size)) * 50)

for name, codec, container in [
    ("tone.aac", "aac", "adts"),
    ("tone.3ga", "aac", "3gp"),
    ("tone.m4a", "aac", "ipod"),
    ("tone.webm", "libopus", "webm"),
    ("tone.opus", "libopus", "ogg"),
    ("tone.mp3", "libmp3lame", "mp3"),
    ("tone.wav", "pcm_s16le", "wav"),
    ("tone.flac", "flac", "flac"),
    ("tone.ogg", "libvorbis", "ogg"),
]:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=1",
            "-map_metadata",
            "-1",
            "-ac",
            "1",
            "-c:a",
            codec,
            "-f",
            container,
            "-n",
            str(fixtures / name),
        ],
        check=True,
    )
```

Container metadata and lossy padding can vary by encoder version. The tests
measure actual decoded samples, bind each receipt and C1 artifact to the source
SHA, and prove that decoding never changes the original bytes.
