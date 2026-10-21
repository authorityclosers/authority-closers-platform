#!/bin/bash
# Round 1 of the analysis-cost benchmark (fictional calls only). Keys come from Infisical dev /sales-xray-bench:
#   sudo -n env AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/sales-xray-bench GROUTE=or /usr/local/sbin/ac-infisical-run -- \
#     setpriv --reuid=acdev --regid=acdev --init-groups -- \
#     /home/acdev/research/analysis-cost-20261020/harness/round1.sh <step>
# GROUTE=direct uses the bench AI Studio key for Gemini; GROUTE=or sends Gemini through OpenRouter (paid from the $20).
# Steps run in decision order: the things that decide "tomorrow" first. Every step resumes; missing keys are skipped.
set -u
cd /home/acdev/research/analysis-cost-20261020/harness
export HOME=/home/acdev BENCH_ROOT=/home/acdev/research/analysis-cost-20261020
PY=/home/acdev/src/dev-live/authority-closers-platform/.venv/bin/python
SPY=/home/acdev/research/analysis-cost-20261020/venv/bin/python
export PYTHONPATH=/home/acdev/src/dev-live/authority-closers-platform/packages/python:.
R="nice -n 19 ionice -c3 $PY run.py"
GROUTE=${GROUTE:-or}
log() { echo "== $(date -u +%H:%M:%S) $*"; }
have() { [ -n "${!1:-}" ] || { echo "skip: $1 not set"; return 1; }; }
gm() { [ "$GROUTE" = or ] && echo "google/$1" || echo "$1"; }              # Gemini model name for the route
gkey() { [ "$GROUTE" = or ] && have OPENROUTER_API_KEY || have GEMINI_API_KEY; }
gasr() { [ "$GROUTE" = or ] && echo "openrouter:google/$1" || echo "gemini:$1"; }
gdir() { [ "$GROUTE" = or ] && echo "openrouter_google_$1" || echo "gemini_$1"; }
CHEAP="anthropic/claude-haiku-5.5 openai/gpt-6-luna deepseek/deepseek-v4.1-flash z-ai/glm-5.3-flash qwen/qwen3.8-flash xiaomi/mimo-v2.6-flash openai/gpt-oss-120b"
step=${1:-all}

base() {   # A. today's pipeline and the one-pass shape on today's model, oracle transcript
  log "A baseline"
  gkey || return 0
  $R text --shape today --model $(gm gemini-3.8-flash)
  $R text --shape onepass --model $(gm gemini-3.8-flash)
}

gasr_step() {   # B. Gemini as the transcriber (the Scribe replacement inside Google)
  log "B Gemini audio -> transcript"
  gkey || return 0
  for m in gemini-3.1-flash-lite gemini-3.8-flash gemini-3.5-flash-lite; do $R asr --arm $(gasr $m) --variant phone_8k; done
}

e2e() {   # C. transcript from each ASR arm -> one pass on today's model
  log "C end to end"
  gkey || return 0
  for t in asr/$(gdir gemini-3.1-flash-lite)/phone_8k asr/$(gdir gemini-3.8-flash)/phone_8k asr/sarvam_saaras-v4/phone_8k \
           asr/deepgram_nova-3/phone_8k asr/assemblyai_universal-2/phone_8k asr/elevenlabs_scribe_v2/phone_8k; do
    [ -d "../results/$t" ] || { echo "skip e2e: no $t"; continue; }
    $R text --shape onepass --model $(gm gemini-3.8-flash) --transcript $t
  done
}

audio() {   # D. audio in, one call
  log "D audio one call"
  gkey || return 0
  for m in gemini-3.1-flash-lite gemini-3.8-flash; do $R audio1 --model $(gm $m) --variant phone_8k; done
}

cheap() {   # E. cheaper text models, one pass, oracle transcript
  log "E cheap text models"
  if gkey; then for m in gemini-3.1-flash-lite gemini-3.5-flash-lite; do $R text --shape onepass --model $(gm $m); done; fi
  have OPENROUTER_API_KEY || return 0
  for m in $CHEAP; do $R text --shape onepass --model $m; done
}

repeat() {   # F. run-to-run consistency
  log "F second runs"
  gkey && { $R text --shape onepass --model $(gm gemini-3.8-flash) --run 2; $R text --shape today --model $(gm gemini-3.8-flash) --run 2 --calls fx-01 fx-03 fx-07 fx-11 fx-12 fx-06; }
  have OPENROUTER_API_KEY && for m in anthropic/claude-haiku-5.5 openai/gpt-6-luna; do $R text --shape onepass --model $m --run 2; done
}

retain() {
  log "retention of critical facts in transcripts"
  have OPENROUTER_API_KEY || return 0
  for d in $(find ../results/asr -mindepth 2 -maxdepth 2 -type d | sort); do $R retain --result $d --judge anthropic/claude-haiku-5.5; done
}

judge() {   # primary judge Haiku 5.5 (cheap, different family from Gemini); Gemini 3.8 Flash as second judge
  log judge
  for d in $(find ../results/text ../results/audio1 -type d -name 'run*' 2>/dev/null | sort); do
    have OPENROUTER_API_KEY && { $R judge --result $d --judge anthropic/claude-haiku-5.5; $R rjudge --result $d --judge anthropic/claude-haiku-5.5; }
  done
  [ "${SECOND_JUDGE:-1}" = 1 ] && gkey && for d in $(find ../results/text -type d -name run1 -path '*oracle*' | sort); do
    $R judge --result $d --judge $(gm gemini-3.8-flash)
  done
}

score() {
  log score
  mkdir -p ../results/scores
  for w in asr retain facts report consistency cost; do nice -n 19 $SPY score.py $w > ../results/scores/$w.md 2>&1; done
  tail -n +1 ../results/scores/*.md
}

case "$step" in
  base) base ;; gasr) gasr_step ;; e2e) e2e ;; audio) audio ;; cheap) cheap ;; repeat) repeat ;;
  retain) retain ;; judge) judge ;; score) score ;;
  decide) base; gasr_step; e2e; retain; judge; score ;;           # minimum for the "tomorrow" decision
  all) base; gasr_step; e2e; audio; cheap; repeat; retain; judge; score ;;
  *) echo "unknown step $step"; exit 2 ;;
esac
log done
