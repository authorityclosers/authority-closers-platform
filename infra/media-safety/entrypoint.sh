#!/bin/sh
set -eu

# clamav/clamav's /init-unprivileged waits for /tmp/clamd.sock even when
# clamd.conf intentionally places the shared socket under /run/ac-media-safety.
# /tmp is a private container tmpfs, so this bridge cannot expose host files.
rm -f /run/ac-media-safety/clamd.sock
rm -f /tmp/clamd.sock
ln -s /run/ac-media-safety/clamd.sock /tmp/clamd.sock
exec /init-unprivileged "$@"
