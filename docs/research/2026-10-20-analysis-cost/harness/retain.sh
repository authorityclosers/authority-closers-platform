#!/bin/bash
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
for a in openrouter_google_gemini-3.1-flash-lite openrouter_google_gemini-3.8-flash sarvam_saaras-v4 deepgram_nova-3 \
         assemblyai_universal-3-5-pro groq_whisper-large-v3-turbo openrouter_google_gemini-3.5-flash-lite assemblyai_universal-2 groq_whisper-large-v3; do
  nice -n 19 $PY run.py retain --result ../results/asr/$a/phone_8k --judge anthropic/claude-haiku-5.5
done
nice -n 19 $SPY score.py retain > ../results/scores/retain.md 2>&1; cat ../results/scores/retain.md
