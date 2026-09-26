# RISK13 committed upload replay evidence

Date: 2026-09-22

The intake boundary now permits an authenticated upload retry after the
30-minute quote window only when the server already has the recording in the
durable `ready` state. The retry still reloads the current actor/session,
recording, quote acceptance, local permission, retention, and storage digest.
Fresh `awaiting_upload` recordings continue to reject an expired quote, and
processing permission expiry remains unchanged.

## Synthetic checks

Against the disposable loopback PostgreSQL 18.6 harness:

```text
uv run pytest tests/database/test_conversation_intake_replay_postgresql.py --basetemp D:\ac-xray-reliable-upload-20260922-10 -q
4 passed in 12.21s

uv run pytest tests/database/test_conversation_intake_postgresql.py --basetemp D:\ac-xray-reliable-upload-20260922-06 -q
9 passed in 13.40s
```

The focused cases cover same-byte HTTP replay after expiry, changed-byte
digest rejection, wrong-session denial against a durably ready recording,
expired uncommitted upload denial, independently expired retention with a
still-valid permission, permission expiry and revocation, and deletion
fencing. All fixtures and source bytes are synthetic; no provider or customer
data is used.
