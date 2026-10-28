#!/usr/bin/env bash
# Dev drill for graceful edge switches (docs/ops/ZERO-DOWNTIME-RELEASES.md, S1).
#
# Starts a scratch edge from the running router's exact image and this checkout's
# infra/application/edge/Caddyfile, with the router's own security settings, on a
# scratch network and 127.0.0.1:18080. A scratch upstream (the API image's Python,
# no secrets, no database) answers fast and slow requests. The release probe hits
# two hosts every 200 ms while routes switch, first by restarting the router (what
# a recreate costs) and then by `caddy reload` on the admin socket, each with a
# slow request in flight. Nothing shared is touched; everything is removed after.
#
#   sudo scripts/ops/edge-reload-drill.sh <output-dir> [switches] [slow-seconds]
set -euo pipefail

[[ "$(id -u)" -eq 0 ]] || { printf 'Run as root (Docker).\n' >&2; exit 1; }
out="${1:?output directory}"
switches="${2:-5}"
slow_seconds="${3:-20}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
probe="$here/scripts/ops/release-probe.py"
caddyfile_source="$here/infra/application/edge/Caddyfile"
[[ -f "$caddyfile_source" && -f "$probe" ]]
install -d -m 0755 "$out"

edge_image="$(docker inspect --format '{{.Image}}' ac-edge-router)"
upstream_image="$(docker inspect --format '{{.Image}}' ac-application-staging-api-1)"
network=zdr-drill-net
edge=zdr-drill-edge
upstream=zdr-drill-upstream
work="$(mktemp -d /tmp/zdr-drill.XXXXXX)"
chmod 0755 "$work"

cleanup() {
  docker rm -f "$edge" "$upstream" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf -- "$work"
}
trap cleanup EXIT
# Leftovers of an interrupted drill are scratch containers too.
docker rm -f "$edge" "$upstream" >/dev/null 2>&1 || true
docker network rm "$network" >/dev/null 2>&1 || true

projection_root=/srv/authority-closers/application/edge-route-releases
mkdir -p "$work/selectors" "$work/projections/a" "$work/projections/b"
for release in a b; do
  for environment in production staging; do
    host="$environment.drill.invalid"
    printf '\t@%s host %s\n\thandle @%s {\n\t\theader X-Authority-Closers-Route "%s-%s"\n\t\treverse_proxy %s:8000\n\t}\n' \
      "$environment" "$host" "$environment" "$environment" "$release" "$upstream" \
      > "$work/projections/$release/$environment.caddy"
  done
done
for environment in production staging; do
  ln -s "$projection_root/a/$environment.caddy" "$work/selectors/$environment.caddy"
done
install -m 0444 "$caddyfile_source" "$work/Caddyfile"
chmod -R a+rX "$work"

docker network create "$network" >/dev/null
# Fast answers on every path; /slow streams one byte a second for ?s= seconds.
docker run -d --name "$upstream" --network "$network" --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --user 65534:65534 --entrypoint python \
  "$upstream_image" -c '
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        url = urlparse(self.path)
        seconds = int(parse_qs(url.query).get("s", ["0"])[0]) if url.path == "/slow" else 0
        self.send_response(200)
        self.send_header("Content-Length", str(max(seconds, 2)))
        self.end_headers()
        if seconds:
            for _ in range(seconds):
                self.wfile.write(b".")
                self.wfile.flush()
                time.sleep(1)
        else:
            self.wfile.write(b"ok")
    def log_message(self, *args):
        pass
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
' >/dev/null

docker run -d --name "$edge" --network "$network" --publish 127.0.0.1:18080:8080 \
  --read-only --init --security-opt no-new-privileges:true --cap-drop ALL \
  --cap-add NET_BIND_SERVICE --user 1000:1000 \
  --tmpfs /config:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --tmpfs /data:rw,noexec,nosuid,nodev,size=32m,uid=1000,gid=1000 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000 \
  --tmpfs /run/caddy:rw,noexec,nosuid,nodev,size=1m,uid=1000,gid=1000,mode=0700 \
  --volume "$work/Caddyfile:/etc/caddy/Caddyfile:ro" \
  --volume "$work/selectors:/etc/caddy/application-routes:ro" \
  --volume "$work/projections:$projection_root:ro" \
  "$edge_image" >/dev/null

ready() {
  curl --silent --fail --max-time 2 --header 'Host: production.drill.invalid' \
    http://127.0.0.1:18080/ >/dev/null
}
for _ in $(seq 1 60); do ready && break; sleep 0.5; done
ready

flip() {
  local release="$1" environment
  for environment in production staging; do
    ln -sfn "$projection_root/$release/$environment.caddy" "$work/selectors/.$environment.tmp"
    mv -T "$work/selectors/.$environment.tmp" "$work/selectors/$environment.caddy"
  done
}

run_phase() {
  local phase="$1" release=b stop="$work/stop-$1"
  python3 "$probe" \
    --target production=production.drill.invalid/ \
    --target staging=staging.drill.invalid/ \
    --port 18080 --interval 0.2 --until-file "$stop" \
    --out "$out/$phase-probe.json" --samples "$out/$phase-samples.jsonl" \
    > "$out/$phase-probe.txt" &
  local probe_pid=$!
  # A long request that is in flight through every switch of this phase.
  curl --silent --show-error --output "$work/slow-$phase" \
    --write-out '{"status": %{http_code}, "bytes": %{size_download}, "seconds": %{time_total}}\n' \
    --header 'Host: production.drill.invalid' --max-time "$((slow_seconds + 30))" \
    "http://127.0.0.1:18080/slow?s=$slow_seconds" > "$out/$phase-slow.json" 2> "$out/$phase-slow.err" &
  local slow_pid=$!
  sleep 2
  for _ in $(seq 1 "$switches"); do
    flip "$release"
    if [[ "$phase" == restart ]]; then
      docker restart --time 10 "$edge" >/dev/null
    else
      docker exec "$edge" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile \
        --address unix//run/caddy/admin.sock >/dev/null 2>>"$out/$phase-reload.err"
    fi
    [[ "$release" == b ]] && release=a || release=b
    sleep "$(( (slow_seconds - 4) / switches > 1 ? (slow_seconds - 4) / switches : 1 ))"
  done
  wait "$slow_pid" || true
  sleep 2
  touch "$stop"
  wait "$probe_pid"
}

state() {
  docker inspect --format '{"restart_count": {{.RestartCount}}, "started": "{{.State.StartedAt}}"}' "$edge"
}
run_phase restart
for _ in $(seq 1 60); do ready && break; sleep 0.5; done
before_reload="$(state)"
run_phase reload
printf '{"before_reload_phase": %s, "after_reload_phase": %s}\n' "$before_reload" "$(state)" \
  > "$out/edge-state.json"
printf 'drill: edge image %s, %s switches per phase, slow request %ss\n' \
  "$edge_image" "$switches" "$slow_seconds" | tee "$out/README.txt"
for phase in restart reload; do
  printf '%s: %s | slow %s\n' "$phase" "$(cat "$out/$phase-probe.txt")" "$(cat "$out/$phase-slow.json")" \
    | tee -a "$out/README.txt"
done
