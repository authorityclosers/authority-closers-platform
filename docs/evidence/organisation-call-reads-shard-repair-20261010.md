# AUT-1712: Python shard 3 fixture repair

PR #422's application run 38029879957 failed one of 3,343 tests in shard 3:
`test_provenance_or_current_binding_mismatch_refuses_before_mutation[renderer]`.
The log shows six extra Git maintenance files under the disposable fixture's
`.git` directory, including `info/refs`, `objects/info/packs` and a multi-pack
index. The full filesystem snapshot assertion caught background Git maintenance
running after fixture commits; it did not identify a call-read policy failure.

The synthetic `Bundle` repository now disables automatic GC and maintenance
before its first commit. The complete snapshot comparison and refusal checks
remain in place. No application, deployment or host Git configuration changes.

Focused verification:

```sh
ac-heavy uv run pytest tests/infra/test_prepare_dev_sales_xray_native.py tests/unit/test_native_artifact_compatibility.py -q --tb=short
```

Result: **125 passed in 87.58 seconds**. CI must confirm the final PR SHA;
the earlier shard result was 3,317 passed, one failed, 25 skipped. PR #422
continues to require CTO/CEO review because its existing implementation touches
identity authorization. This test-only repair does not change that routing.
