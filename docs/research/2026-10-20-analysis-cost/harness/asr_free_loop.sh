#!/bin/bash
# Fetch rendered audio as it lands and run the free-credit ASR arms on new calls (resumable). Stops when every call
# with a script has audio and every arm ran, or after 3 hours.
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
N="nice -n 19 ionice -c3"
end=$(( $(date +%s) + 10800 ))
while [ "$(date +%s)" -lt "$end" ]; do
  ../bench/fetch_audio.sh $(cat ../logs/runs.txt) >/dev/null 2>&1 || true
  calls=$(cd ../bench/audio && ls -d fx-* 2>/dev/null | tr '\n' ' ')
  if [ -n "$calls" ]; then
    $N $PY run.py asr --arm deepgram:nova-3 --variant phone_8k --calls $calls
    $N $SPY sarvam_asr.py --variant phone_8k --calls $calls
    if [ -n "${ASSEMBLYAI_API_KEY:-}" ]; then
      for m in universal-2 universal-3-5-pro; do $N $PY run.py asr --arm assemblyai:$m --variant phone_8k --calls $calls; done
    fi
  fi
  want=$(cd ../bench/calls && ls -d fx-* | wc -l)
  n() { ls ../results/asr/$1/phone_8k/fx-*.json 2>/dev/null | wc -l; }
  echo "$(date -u +%H:%M) audio=$(echo $calls | wc -w) deepgram=$(n deepgram_nova-3) sarvam=$(n sarvam_saaras-v4) aai2=$(n assemblyai_universal-2) aai35=$(n assemblyai_universal-3-5-pro) want=$want"
  [ "$(n deepgram_nova-3)" -ge "$want" ] && [ "$(n sarvam_saaras-v4)" -ge "$want" ] && [ "$(n assemblyai_universal-3-5-pro)" -ge "$want" ] && break
  sleep 90
done
