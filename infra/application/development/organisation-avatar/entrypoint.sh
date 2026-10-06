#!/bin/sh
set -eu
# The pinned image's readiness probe uses /tmp/clamd.sock.
rm -f /run/ac-dev-organisation-avatar/clamd.sock /tmp/clamd.sock
ln -s /run/ac-dev-organisation-avatar/clamd.sock /tmp/clamd.sock
exec /init-unprivileged "$@"
