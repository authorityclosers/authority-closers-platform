#!/bin/bash
# fetch_audio.sh <run-id>...: download bench-tts audio artifacts into bench/audio/<call>/ (flac + segments + render.json)
set -euo pipefail
cd /home/acdev/research/analysis-cost-20261020/bench
for run in "$@"; do
  tmp=$(mktemp -d /tmp/benchdl.XXXX)
  /home/acdev/.local/bin/gh run download "$run" -R authorityclosers/authority-closers-platform -D "$tmp" -p 'audio-*' >/dev/null
  for d in "$tmp"/audio-*/fx-*; do
    c=$(basename "$d"); mkdir -p audio/"$c"; cp -r "$d"/. audio/"$c"/
    rm -f audio/"$c"/stereo_16k.flac   # disk is 98% full; stereo stays in the GitHub artifact
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['call_id'], round(d['seconds']/60,1), 'min', d['engines'], d['snr_db'])" audio/"$c"/render.json
  done
  rm -rf "$tmp"
done
du -sh audio
