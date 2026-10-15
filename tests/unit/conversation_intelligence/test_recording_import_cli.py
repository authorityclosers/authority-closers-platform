"""The Drive operator uses published bytes, explicit members and ordinary intake only."""

import hashlib
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

POLICY = "a" * 64


def fixture(tmp_path):
    rows = []
    for person in ("Rep A", "Rep B"):
        folder = tmp_path / person
        folder.mkdir()
        file = folder / "recording 6"
        payload = (person + " audio").encode()
        file.write_bytes(payload)
        rows.append(
            {
                "person": person,
                "folder": person,
                "file": f"{person}/recording 6",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "duration_s": 30.5,
                "format": "mp3",
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": rows, "source": "fictional"}))
    member = str(uuid4())
    assignments = tmp_path / "members.json"
    assignments.write_text(json.dumps({"Rep A": member}))
    return manifest, assignments, member


def test_offline_manifest_uses_actual_extensionless_bytes_and_never_assigns_by_name(
    tmp_path, monkeypatch
):
    manifest, assignments, member = fixture(tmp_path)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Offline means no HTTP."))
    first = cli.inventory(manifest)
    assert first.receipt()["assigned_files"] == 0
    assert len(first.held) == 2
    confirmed = cli.inventory(manifest, assignments)
    assert confirmed.receipt()["assigned_files"] == 1
    assert confirmed.held == [{"index": 1, "person": "Rep B", "reason": "needs_member"}]
    assert confirmed.manifest(assigned=True).files[0].relative_path == "Rep A/recording 6"
    assert confirmed.files[0].person_id == member
    assert confirmed.sha256 != first.sha256


@pytest.mark.parametrize("change", ["bytes", "hash", "traversal", "symlink", "duplicate"])
def test_untrusted_or_changed_manifest_fails_before_any_session(tmp_path, change):
    manifest, assignments, _ = fixture(tmp_path)
    document = json.loads(manifest.read_text())
    row = document["files"][0]
    if change == "bytes":
        row["bytes"] += 1
    elif change == "hash":
        (tmp_path / row["file"]).write_bytes(b"x" * row["bytes"])
    elif change == "traversal":
        row["file"] = "../outside"
    elif change == "symlink":
        original = tmp_path / row["file"]
        outside = tmp_path.parent / "fictional-outside-recording"
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
    else:
        document["files"].append(row)
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        cli.inventory(manifest, assignments)


def test_over_limit_sources_are_verified_and_held_without_raising_the_normal_cap(
    tmp_path, monkeypatch
):
    manifest, assignments, _ = fixture(tmp_path)
    monkeypatch.setattr(cli, "MAX_AUDIO_BYTES", 5)
    value = cli.inventory(manifest, assignments)
    assert not value.files
    assert all(item["reason"] == "upload_limit" for item in value.held)
    assert value.total == 2


def server(tmp_path, *, outcome="done", wrong_target=False):
    manifest_path, assignments, member = fixture(tmp_path)
    value = cli.inventory(manifest_path, assignments)
    manifest = value.manifest(assigned=True)
    tenant, batch_id, submission, recording, plan_id = [str(uuid4()) for _ in range(5)]
    batch = {
        "batch_id": batch_id,
        "tenant_id": tenant,
        "manifest_sha256": content_hash(manifest.model_dump(mode="json")),
        "policy_sha256": POLICY,
        "total_files": 1,
        "total_bytes": manifest.files[0].source_bytes,
        "terminal_state": None,
        "files": [
            {
                "item_index": 0,
                "state": "awaiting_upload",
                "source_sha256": manifest.files[0].source_sha256,
                "source_bytes": manifest.files[0].source_bytes,
                "upload_submission_id": submission,
                "submission_id": None,
                "person_id": member,
                "confirmed_person_id": member,
            }
        ],
    }
    sent, quoted = [], False

    def respond(request):
        nonlocal quoted
        sent.append(request)
        assert request.headers["x-recording-import-tenant"] == tenant
        assert request.headers["origin"] == "http://127.0.0.1:1234"
        path = request.url.path.removeprefix(cli.PREFIX)
        if path == "/imports/preview":
            preview = project_import_preview(manifest, [ImportMember(UUID(member), "Rep A", "Rep")])
            return httpx.Response(
                200, json={**preview, "tenant_id": str(uuid4()) if wrong_target else tenant}
            )
        if path == "/upload-policy":
            return httpx.Response(200, json={"policy_sha256": POLICY})
        if path == "/imports":
            body = json.loads(request.content)
            assert body["rights_confirmed"] is True
            assert body["folders"] == [{"folder": "Rep A", "person_id": member}]
            assert request.headers["idempotency-key"] == "drive-import:" + content_hash(body)
            return httpx.Response(201, json=batch)
        if path == f"/imports/{batch_id}":
            return httpx.Response(200, json=batch)
        assert request.headers["x-recording-import"] == batch_id
        assert request.headers["x-recording-import-item"] == "0"
        if path.endswith("/source"):
            assert request.content == value.files[0].path.read_bytes()
            assert request.headers["content-type"] == "application/octet-stream"
            assert request.headers["content-length"] == str(len(request.content))
            assert request.headers["x-upload-policy"] == POLICY
            assert request.headers["x-upload-consent"] == "accepted"
            assert request.headers["x-source-sha256"] == manifest.files[0].source_sha256
            batch["files"][0].update(state="queued", submission_id=submission)
            return httpx.Response(
                201,
                json={
                    "submission_id": submission,
                    "source_sha256": manifest.files[0].source_sha256,
                },
            )
        if path == f"/submissions/{submission}":
            return httpx.Response(
                200,
                json={
                    "recording_id": recording,
                    "source_sha256": manifest.files[0].source_sha256,
                    "local_state": "completed",
                    "automatic_progression": False,
                    "has_report": False,
                    "run_state": "queued",
                },
            )
        if request.method == "GET" and path.endswith("/plan") and not quoted:
            return httpx.Response(404)
        plan = {
            "id": plan_id,
            "recording_id": recording,
            "plan_fingerprint": "b" * 64,
            "privacy_revision": "sales-xray-processing-plan-v1",
            "accepted": False,
            "state": "quoted",
            "expires_at_epoch": 9999999999,
        }
        if path.endswith("/plan/quote"):
            quoted = True
            assert json.loads(request.content) == {"report_language": "en"}
            return httpx.Response(201, json=plan)
        assert path.endswith("/plan") and request.method == "POST"
        body = json.loads(request.content)
        assert body["plan_id"] == plan_id and body["accepted"] is True
        assert body["plan_fingerprint"] == plan["plan_fingerprint"]
        batch["files"][0].update(state=outcome)
        batch["terminal_state"] = "done" if outcome == "done" else "failed"
        return httpx.Response(202, json={**plan, "accepted": True, "state": "active"})

    client = httpx.Client(
        base_url="http://127.0.0.1:1234",
        headers={"Origin": "http://127.0.0.1:1234", "X-Recording-Import-Tenant": tenant},
        transport=httpx.MockTransport(respond),
    )
    return client, value, tenant, batch, sent


@pytest.mark.parametrize("outcome", ["done", "failed"])
def test_operator_uses_normal_intake_quote_accept_and_replay_without_auto_retry(
    tmp_path, monkeypatch, outcome
):
    client, value, tenant, batch, sent = server(tmp_path, outcome=outcome)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    with client:
        result = cli.apply(client, value, tenant, max_wait=600)
        assert result["state"] == outcome
        assert result["held"] == [{"index": 1, "person": "Rep B", "reason": "needs_member"}]
        writes = len([r for r in sent if r.method != "GET"])
        replay = cli.apply(client, value, tenant, max_wait=60)
        assert replay["batch"]["batch_id"] == batch["batch_id"]
        assert len([r for r in sent if r.method != "GET"]) == writes + 2  # preview and confirm
        assert sum(r.method == "PUT" for r in sent) == 1
        assert sum(r.url.path.endswith("/plan/quote") for r in sent) == 1
        assert not any(r.url.path.endswith("/retry") for r in sent)


def test_operator_refuses_changed_target_before_confirmation_or_upload(tmp_path):
    client, value, tenant, _, sent = server(tmp_path, wrong_target=True)
    with client, pytest.raises(ValueError, match="exact organisation"):
        cli.apply(client, value, tenant, max_wait=60)
    assert len(sent) == 1


def test_bounded_window_keeps_pending_calls_honest_and_sends_no_audio(tmp_path):
    client, value, tenant, _, sent = server(tmp_path)
    with client:
        result = cli.apply(client, value, tenant, max_wait=0)
    assert result["state"] == "waiting"
    assert result["batch"]["files"][0]["state"] == "awaiting_upload"
    assert not any(r.method == "PUT" for r in sent)


@pytest.mark.parametrize("state", ["working", "failed", "needs_member"])
def test_readback_never_calls_undelivered_items_done(tmp_path, state):
    client, _, tenant, batch, _ = server(tmp_path)
    client.close()
    batch["terminal_state"] = "done"
    batch["files"][0]["state"] = state
    with pytest.raises(ValueError, match="reported as delivered"):
        cli.batch_receipt(batch, tenant=tenant)


def test_operator_receipts_omit_unknown_call_content_and_response_fields(tmp_path):
    client, _, tenant, batch, _ = server(tmp_path)
    client.close()
    batch["transcript"] = {"text": "fictional content must stay out of operator receipts"}
    batch["files"][0]["private_note"] = "fictional private field"
    receipt = cli.batch_receipt(batch, tenant=tenant)
    assert "transcript" not in receipt
    assert "private_note" not in receipt["files"][0]
    assert "fictional" not in json.dumps(receipt)


@pytest.mark.parametrize(
    "run_state, expected",
    [("failed", "failed"), ("working", "waiting"), (None, "already_imported"), ("done", "done")],
)
def test_duplicate_source_keeps_its_real_analysis_state_without_another_upload_or_plan(
    tmp_path, run_state, expected
):
    client, value, tenant, batch, sent = server(tmp_path)
    batch["terminal_state"] = "done"
    batch["files"][0].update(state="already_imported", run_state=run_state)
    with client:
        receipt = cli.apply(client, value, tenant, max_wait=60)
    assert receipt["state"] == expected
    assert sum(r.method == "PUT" for r in sent) == 0
    assert not any("/plan" in r.url.path or "/retry" in r.url.path for r in sent)
