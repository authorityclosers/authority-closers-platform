#!/bin/bash
# End to end with the exhaustive-facts prompt: transcript from each transcriber -> one pass (onepass2).
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
R="nice -n 19 ionice -c3 $PY run.py"
for t in asr/openrouter_google_gemini-3.1-flash-lite/phone_8k asr/openrouter_google_gemini-3.8-flash/phone_8k \
         asr/sarvam_saaras-v4/phone_8k asr/deepgram_nova-3/phone_8k asr/groq_whisper-large-v3-turbo/phone_8k; do
  $R text --shape onepass2 --model google/gemini-3.8-flash --transcript $t
done
$R text --shape onepass2 --model anthropic/claude-haiku-5.5
$R text --shape onepass2 --model anthropic/claude-haiku-5.5 --transcript asr/openrouter_google_gemini-3.1-flash-lite/phone_8k
