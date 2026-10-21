#!/bin/bash
# starts subscription judges (fact + report) for each round-8 variant once all 16 calls are analysed
H=/home/acdev/research/analysis-cost-20261020/harness
R=/home/acdev/research/analysis-cost-20261020/results/text
declare -A done
for i in $(seq 1 240); do
  for v in strong hybrid stronghigh; do
    [ -n "${done[$v]}" ] && continue
    n=$(ls $R/full_$v/openai_gpt-6-luna/*/run1/fx-*.json 2>/dev/null | wc -l)
    if [ "$n" -ge 16 ]; then
      D=../results/text/full_$v/openai_gpt-6-luna/asr_openrouter_google_gemini-3.1-flash-lite_phone_8k/run1
      for k in judge rjudge; do JUDGE_REVERSE=1 setsid nohup $H/subj.sh $k $D > /tmp/subj-rev-full_$v-$k.out 2>&1 < /dev/null & done
      done[$v]=1; echo "$(date +%H:%M) judging $v"
    fi
  done
  [ ${#done[@]} -ge 3 ] && { echo all-launched; exit 0; }
  sleep 30
done
