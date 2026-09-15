# Private SCP input transport for the canonical Studio uploader

The optional `--transport scp` stages a workstation video in verified 16MiB
parts on the existing `ssh ac` host. A random, exclusively created mode0700
directory holds only temporary input. Each part and the assembled whole object
are size/hash checked. Only then is the normal Coach upload intent created.
The exact same authenticated intent/byte PUT/complete/status operations run via
loopback Caddy; the cache never becomes authoritative media. Success and failure
remove the generated cache. Browser upload semantics are unchanged.

Transfer retries are bounded. A verification response lost after the rename can
be retried only against an already-finalized part with matching size/hash. Paths
are restricted to a generated UUID directory, session credentials never enter
SCP arguments/files/output, and canonical API responses remain authoritative.

Actual Windows/SSH tests:25 passed including a2MiB synthetic three-part SCP
roundtrip, remote size/hash/mode verification and confirmed cache removal, plus
real unauthenticated staging intent/PUT rejection. Local lifecycle tests check
that staging failure creates no intent and that cleanup follows completion.
An initial real rejection test exposed an existing collector bug: intentionally
stopping SSH after receiving a non2xx response caused its exit code to hide the
canonical response. The corrected run passes; deadlines/output bounds remain.

This is operator transport proof, not publication or playback of the633MB4K
course fixture. That upload remains pending. The user's latest Sales Xray-first
instruction takes precedence over further noncritical media work.
