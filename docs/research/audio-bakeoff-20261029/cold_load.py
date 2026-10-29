# ruff: noqa: E402, S310, S603
"""Fresh process with already-downloaded weights; page cache is not dropped."""

import json
import resource
import sys
import time

start = time.perf_counter()
from faster_whisper import WhisperModel

imports = time.perf_counter() - start
name = {
    "small": "Systran/faster-whisper-small",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}[sys.argv[1]]
t = time.perf_counter()
model = WhisperModel(
    name,
    device="cpu",
    compute_type="int8",
    cpu_threads=2,
    num_workers=1,
    download_root="models",
    local_files_only=True,
)
print(
    json.dumps(
        dict(
            engine=sys.argv[1],
            imports_ms=imports * 1000,
            cached_model_load_ms=(time.perf_counter() - t) * 1000,
            process_ready_ms=(time.perf_counter() - start) * 1000,
            peak_ram_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        )
    )
)
