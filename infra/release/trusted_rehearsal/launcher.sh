#!/bin/sh
# PROPOSAL ONLY. Root installs together with the reviewed bundle after approval.
# current is a root-controlled selection of the exact config.bundle directory.
exec /opt/ac-schema-rehearsal/runtime/bin/python -IB /opt/ac-schema-rehearsal/current/infra/release/trusted_rehearsal/harness.py "$@"
