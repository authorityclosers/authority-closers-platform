"""Operator windows move past attention items without inventing canonical success."""

import json
from uuid import UUID, uuid4

import httpx
import pytest

from ac_platform.conversation_intelligence import recording_import_cli as cli
from ac_platform.conversation_intelligence.bulk_import_preview import (
    ImportMember,
    project_import_preview,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from tests.unit.conversation_intelligence.test_recording_import_cli import POLICY, fixture


def operator(
    tmp_path,
    monkeypatch,
    *,
    failed_at=None,
    errors=(),
    first_state=None,
    ongoing=False,
    ambiguous=False,
    refusal_detail=None,
):
    manifest_path, assignments, member = fixture(tmp_path)
    assignments.write_text(json.dumps({"Rep A": member, "Rep B": member}))
    value = cli.inventory(manifest_path, assignments)
    manifest = value.manifest(assigned=True)
    tenant, batch_id = str(uuid4()), str(uuid4())
    submissions, recordings, plans = ([str(uuid4()) for _ in range(2)] for _ in range(3))
    rows = [
        {
            "item_index": index,
            "state": "awaiting_upload",
            "source_sha256": source.source_sha256,
            "source_bytes": source.source_bytes,
            "upload_submission_id": submissions[index],
            "submission_id": None,
            "person_id": member,
            "confirmed_person_id": member,
            "local_state": None,
            "plan_state": None,
        }
        for index, source in enumerate(manifest.files)
    ]
    if first_state:
        rows[0].update(
            state=first_state,
            submission_id=submissions[0],
            local_state="completed",
            plan_state="held",
        )
    batch = {
        "batch_id": batch_id,
        "tenant_id": tenant,
        "manifest_sha256": content_hash(manifest.model_dump(mode="json")),
        "policy_sha256": POLICY,
        "total_files": 2,
        "total_bytes": sum(f.source_bytes for f in manifest.files),
        "terminal_state": None,
        "files": rows,
    }
    clock, sleeps, sent, failures = [0.0], [], [], list(errors)
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        assert seconds >= 60
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(cli.time, "sleep", sleep)

    def respond(request):
        sent.append(request)
        path = request.url.path.removeprefix(cli.PREFIX)
        if path == "/imports/preview":
            return httpx.Response(
                200,
                json={
                    **project_import_preview(manifest, [ImportMember(UUID(member), "Rep", "Rep")]),
                    "tenant_id": tenant,
                },
            )
        if path == "/upload-policy":
            return httpx.Response(200, json={"policy_sha256": POLICY})
        if path == "/imports" or path == f"/imports/{batch_id}":
            return httpx.Response(201 if request.method == "POST" else 200, json=batch)
        index = int(request.headers["X-Recording-Import-Item"])
        assert request.headers["X-Recording-Import"] == batch_id
        assert path.startswith(f"/submissions/{submissions[index]}")
        operation = (
            "upload" if path.endswith("/source") else "quote" if path.endswith("/quote") else None
        )
        if index == 0 and operation == failed_at and failures:
            status = failures.pop(0)
            return httpx.Response(
                status,
                json={
                    "detail": refusal_detail
                    or (cli.CAPACITY_DETAIL if status == 409 else "private provider detail")
                },
            )
        if operation == "upload":
            assert request.content == value.files[index].path.read_bytes()
            assert request.headers["X-Source-SHA256"] == manifest.files[index].source_sha256
            rows[index].update(
                state="working", submission_id=submissions[index], local_state="completed"
            )
            if ambiguous and index == 0:
                raise httpx.ReadTimeout("fictional upload response lost", request=request)
            return httpx.Response(
                202,
                json={
                    "submission_id": submissions[index],
                    "source_sha256": manifest.files[index].source_sha256,
                },
            )
        if path == f"/submissions/{submissions[index]}":
            return httpx.Response(
                200,
                json={
                    "recording_id": recordings[index],
                    "source_sha256": manifest.files[index].source_sha256,
                    "local_state": "completed",
                    "automatic_progression": rows[index]["plan_state"] == "active",
                    "has_report": False,
                    "run_state": "working",
                },
            )
        if request.method == "GET" and path.endswith("/plan"):
            return httpx.Response(404)
        plan = {
            "id": plans[index],
            "recording_id": recordings[index],
            "plan_fingerprint": "b" * 64,
            "privacy_revision": "sales-xray-processing-plan-v1",
            "accepted": False,
            "state": "quoted",
            "expires_at_epoch": 9999999999,
        }
        if operation == "quote":
            assert request.headers["Idempotency-Key"] == f"import-plan:{batch_id}:{index}"
            return httpx.Response(201, json=plan)
        assert path.endswith("/plan") and request.method == "POST"
        assert request.headers["Idempotency-Key"] == f"accept-plan:{plans[index]}"
        rows[index].update(
            state="working" if ongoing and index == 0 else "done", plan_state="active"
        )
        return httpx.Response(202, json={**plan, "accepted": True, "state": "active"})

    client = httpx.Client(base_url="http://127.0.0.1:1234", transport=httpx.MockTransport(respond))
    return client, value, tenant, batch, sent, sleeps


def test_capacity_wait_reopens_same_source_then_completes_both_items(tmp_path, monkeypatch):
    client, value, tenant, batch, sent, sleeps = operator(
        tmp_path,
        monkeypatch,
        failed_at="upload",
        errors=[409],
    )
    with client:
        result = cli.apply(client, value, tenant, max_wait=900)
    assert result["state"] == "done"
    uploads = [r for r in sent if r.method == "PUT"]
    assert uploads[0].content == uploads[1].content
    assert uploads[0].url == uploads[1].url
    assert uploads[0].headers == uploads[1].headers
    assert sleeps[0] == 60
    assert not result["attention"]
    assert result["batch"]["batch_id"] == batch["batch_id"]


def test_capacity_timeout_is_resumable_and_backoff_is_bounded(tmp_path, monkeypatch):
    client, value, tenant, _, sent, sleeps = operator(
        tmp_path,
        monkeypatch,
        failed_at="upload",
        errors=[409] * 8,
    )
    with client:
        result = cli.apply(client, value, tenant, max_wait=240)
    assert result["state"] == "waiting" and result["waiting_reason"] == "local_capacity"
    assert result["batch"]["files"][0]["state"] == "awaiting_upload"
    assert sleeps == [60, 120]
    assert sum(r.method == "PUT" for r in sent) == 3


@pytest.mark.parametrize("state", ["failed", "held"])
def test_terminal_attention_item_does_not_stop_second_file_or_auto_retry(
    tmp_path, monkeypatch, state
):
    client, value, tenant, _, sent, _ = operator(tmp_path, monkeypatch, first_state=state)
    with client:
        result = cli.apply(client, value, tenant, max_wait=900)
    assert result["state"] == "failed"
    assert result["batch"]["files"][0]["state"] == state
    assert result["batch"]["files"][1]["state"] == "done"
    assert result["attention"] == [{"item_index": 0, "reason": state}]
    assert not any(r.url.path.endswith("/retry") for r in sent)


@pytest.mark.parametrize("operation,status", [("upload", 422), ("upload", 413), ("quote", 422)])
def test_permanent_item_refusal_stays_visible_and_later_file_finishes(
    tmp_path, monkeypatch, operation, status
):
    client, value, tenant, _, sent, _ = operator(
        tmp_path,
        monkeypatch,
        failed_at=operation,
        errors=[status],
    )
    with client:
        result = cli.apply(client, value, tenant, max_wait=900)
    assert result["state"] == "failed"
    assert result["batch"]["files"][0]["state"] != "done"
    assert result["batch"]["files"][1]["state"] == "done"
    assert result["attention"] == [{"item_index": 0, "reason": "item_refused", "status": status}]
    assert "private provider detail" not in json.dumps(result)
    assert not any(r.url.path.endswith("/retry") for r in sent)


def test_provider_active_allows_next_local_upload_and_never_claims_done(tmp_path, monkeypatch):
    client, value, tenant, _, sent, _ = operator(tmp_path, monkeypatch, ongoing=True)
    with client:
        result = cli.apply(client, value, tenant, max_wait=480)
    assert result["state"] == "waiting"
    assert result["batch"]["files"][0]["state"] == "working"
    assert result["batch"]["files"][1]["state"] == "done"
    assert sum(r.method == "PUT" for r in sent) == 2
    assert sum(r.url.path.endswith("/plan/quote") for r in sent) == 2


def test_lost_upload_response_reads_canonical_state_before_another_write(tmp_path, monkeypatch):
    client, value, tenant, _, sent, _ = operator(tmp_path, monkeypatch, ambiguous=True)
    with client:
        result = cli.apply(client, value, tenant, max_wait=900)
    assert result["state"] == "done"
    assert sum(r.method == "PUT" for r in sent) == 2
    assert not any(r.url.path.endswith("/retry") for r in sent)


def test_authority_refusal_stops_the_window_before_later_upload(tmp_path, monkeypatch):
    client, value, tenant, _, sent, sleeps = operator(
        tmp_path,
        monkeypatch,
        failed_at="upload",
        errors=[403],
    )
    with client, pytest.raises(cli.RequestRefused) as failure:
        cli.apply(client, value, tenant, max_wait=900)
    assert failure.value.reason == "authority_or_conflict"
    assert sum(r.method == "PUT" for r in sent) == 1
    assert not sleeps


@pytest.mark.parametrize("status,detail", sorted(cli.ITEM_REFUSALS))
def test_exact_allowance_and_budget_refusals_only_hold_their_item(
    tmp_path, monkeypatch, status, detail
):
    client, value, tenant, _, _, _ = operator(
        tmp_path,
        monkeypatch,
        failed_at="upload",
        errors=[status],
        refusal_detail=detail,
    )
    with client:
        result = cli.apply(client, value, tenant, max_wait=900)
    assert result["batch"]["files"][1]["state"] == "done"
    assert result["attention"][0]["status"] == status


def test_source_changed_during_capacity_wait_stops_before_resending(tmp_path, monkeypatch):
    client, value, tenant, _, sent, _ = operator(
        tmp_path, monkeypatch, failed_at="upload", errors=[409]
    )
    sleep = cli.time.sleep

    def change(seconds):
        sleep(seconds)
        value.files[0].path.write_bytes(b"changed")

    monkeypatch.setattr(cli.time, "sleep", change)
    with client, pytest.raises(ValueError, match="recording changed"):
        cli.apply(client, value, tenant, max_wait=900)
    assert sum(r.method == "PUT" for r in sent) == 1


def test_unavailable_readback_retries_reads_before_sending_more_audio(tmp_path, monkeypatch):
    client, value, tenant, _, sent, sleeps = operator(tmp_path, monkeypatch, ambiguous=True)
    original = client._transport.handler
    unavailable = [True, True]

    def respond(request):
        if request.method == "GET" and "/imports/" in request.url.path and unavailable:
            sent.append(request)
            unavailable.pop()
            return httpx.Response(503)
        return original(request)

    client._transport.handler = respond
    with client:
        result = cli.apply(client, value, tenant, max_wait=1200)
    assert result["state"] == "done"
    assert sleeps[:3] == [60, 120, 240]
    assert sum(r.method == "PUT" for r in sent) == 2


def test_unrelated_conflict_does_not_retry_or_skip_invalid_consent(tmp_path, monkeypatch):
    client, value, tenant, _, sent, _ = operator(
        tmp_path, monkeypatch, failed_at="upload", errors=[409]
    )
    original = client._transport.handler

    def respond(request):
        if request.method == "PUT":
            sent.append(request)
            return httpx.Response(
                409, json={"detail": "The upload terms changed. Review them and try again."}
            )
        return original(request)

    client._transport.handler = respond
    with client, pytest.raises(cli.RequestRefused) as failure:
        cli.apply(client, value, tenant, max_wait=900)
    assert failure.value.reason == "authority_or_conflict"
    assert sum(r.method == "PUT" for r in sent) == 1
