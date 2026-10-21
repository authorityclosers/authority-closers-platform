#!/usr/bin/env python3
"""Real-call judging on the Claude subscription (Claude Code CLI on ac, model Sonnet), no API spend.

Same prompt as realcalls.cmd_judge; the verdict is written as judge "claude-sub/sonnet". Usage:
  subjudge.py <shape:model> [<shape:model> ...]      e.g. brain4n:openai/gpt-6-luna today:google/gemini-3.8-flash
"""

from __future__ import annotations

import json
import subprocess
import sys

from common import parse_json_text
import realcalls as RC
import run as R

CLAUDE = "/home/acdev/.local/bin/claude"
JUDGE = "claude-sub/sonnet"


def main() -> int:
    gold = RC.truths()
    schema = json.dumps(RC.rjudge_real_schema())
    for arm in sys.argv[1:]:
        shape, model = arm.split(":", 1)
        for cid in RC.ids():
            notes = gold.get(cid) or []
            path = RC.result_dir(shape, model) / f"{cid}.json"
            out = RC.result_dir(shape, model) / "rjudge" / JUDGE.replace("/", "_") / f"{cid}.json"
            if not notes or not path.exists() or out.exists():
                continue
            coaching = R.system_coaching(json.loads(path.read_text(encoding="utf-8")))
            transcript = R.load_transcript(cid, RC.TRANSCRIPT)
            prompt = (RC.RJUDGE_REAL + "\n\nAnswer with ONE JSON object only (no prose, no code fence) matching this "
                      "JSON schema:\n" + schema + "\n\nExpert coach's notes:\n" + json.dumps(notes, ensure_ascii=False)
                      + "\n\nSystem coaching output:\n" + json.dumps(coaching, ensure_ascii=False)[:60000]
                      + "\n\nTranscript (MM:SS from start):\n"
                      + "\n".join(f"[{s['start_ms'] // 60000}:{s['start_ms'] // 1000 % 60:02d}] {s['speaker_id']}: {s['text']}"
                                  for s in transcript["segments"]))
            try:
                p = subprocess.run([CLAUDE, "-p", "--model", "sonnet"], input=prompt, capture_output=True, text=True,
                                   timeout=600, cwd="/tmp")
                verdict = parse_json_text(R.strip_fences(p.stdout) or "")
            except Exception as exc:
                print(cid, arm, "failed", type(exc).__name__, flush=True)
                continue
            verdict["n_truths"] = len(notes)
            R._write(out, verdict)
            print(cid, arm, "judged by", JUDGE, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
