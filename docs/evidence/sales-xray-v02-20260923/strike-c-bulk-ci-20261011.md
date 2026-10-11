# Bulk import continuation: cancellation fixture

PR #437's preview-head application run 38094362078 failed only
`test_cancel_after_final_authority_can_commit_private_bytes_but_drains_before_return`.
Its two-second thread-readiness wait elapsed before final byte publication; the
cleanup then expected cancellation from a request it had never cancelled.

The fixture now allows ten seconds for the explicit readiness event, keeps the
writer held for up to twenty seconds, and cancels/drains an outstanding request
even when readiness fails. Successful readiness still proves cancellation cannot
return while private byte publication holds its slot, and replay publishes the
same hash. It avoids a second cancellation of an already cancelling task. No
studio-video runtime code changes.

On the integrated `f88161f` tree, 52 focused bulk/native/authority/backup checks
passed (110.10s), including the original failing test. After the fixture change,
all 41 studio-video byte tests passed (49.98s). This is loopback/disposable and
fictional-data proof; final-head CI remains required. No hosted write or provider
dispatch occurred.
