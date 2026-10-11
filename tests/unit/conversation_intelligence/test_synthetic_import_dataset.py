"""Dry-run adapter boundaries: exact published folders, stable identities and safe targets."""

import gzip
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from ac_platform.conversation_intelligence.synthetic_import_cli import (
    AC_SANDBOX,
    allowed_origin,
    apply_dataset,
    validate_dataset,
)
from ac_platform.conversation_intelligence.synthetic_import_contracts import SyntheticRecordInput
from ac_platform.conversation_intelligence.synthetic_import_dataset import (
    OPERATIONS,
    attachments,
    bundles,
    exact_file,
    record_batches,
)
from tests.unit.conversation_intelligence.test_synthetic_import_audio import media_bundle
from tests.unit.conversation_intelligence.test_synthetic_import_contracts import bundle


def dataset(root):
    data = bundle()
    business = data["metadata"]["business_id"]
    call = data["metadata"]["call_id"]
    header = {"synthetic": True, "schema_version": "synthetic-sales-v1.0"}

    def write(path, value):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))

    def compressed(path, rows):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")

    write("simulation/config.json", {"synthetic": True, "start": "2017-01-01"})
    compressed(
        "simulation/operations/business_history.jsonl.gz",
        [{**header, "business_id": business, "at": "2017-01-01T00:00:00+05:30"}],
    )
    write(f"world/{business}.json", {**header, "business_id": business})
    for name, *_ in OPERATIONS:
        compressed(f"simulation/operations/{name}.jsonl.gz", [])
    compressed(
        "simulation/calls/2017-01.jsonl.gz", [{**data["metadata"], "report": data["report"]}]
    )
    write(
        "import_ready/index.json",
        {
            "synthetic": True,
            "calls": 1,
            "bundles": [{"call_id": call, "folder": "import_ready/" + call}],
        },
    )
    for key in ("metadata", "transcript", "answer_key", "report", "coaching"):
        write(f"import_ready/{call}/{key}.json", data[key])
    return data


def test_offline_dry_run_preserves_unique_corpus_fingerprint_without_network(tmp_path, monkeypatch):
    dataset(tmp_path)

    def unavailable(*args, **kwargs):
        raise AssertionError("Dry-run must not open an HTTP session.")

    monkeypatch.setattr("httpx.Client", unavailable)
    first = validate_dataset(tmp_path)
    assert first["counts"] == {"world": 1, "business_history": 1, "call_summary": 1, "call": 1}
    assert validate_dataset(tmp_path) == first


def test_indexed_folders_cannot_escape_the_dataset_or_change_call_identity(tmp_path):
    data = dataset(tmp_path)
    outside = tmp_path.parent / "outside-fictional.json"
    outside.write_text("{}")
    (tmp_path / "link.json").symlink_to(outside)
    with pytest.raises(ValueError, match="out-of-root"):
        exact_file(tmp_path, "link.json")
    with pytest.raises(ValueError, match="out-of-root"):
        exact_file(tmp_path, "../outside-fictional.json")
    path = tmp_path / "import_ready/index.json"
    path.write_text(
        json.dumps(
            {
                "synthetic": True,
                "calls": 1,
                "bundles": [{"call_id": data["metadata"]["call_id"], "folder": "../outside"}],
            }
        )
    )
    with pytest.raises(ValueError, match="folder identity"):
        list(bundles(tmp_path))


@pytest.mark.parametrize(
    "origin",
    [
        "https://salesxray.authorityclosers.com",
        "https://other.invalid",
        "https://salesxray-staging.authorityclosers.com/path",
        "https://salesxray-staging.authorityclosers.com?x=1",
        "https://user:password@salesxray-staging.authorityclosers.com",
    ],
)
def test_operator_never_sends_session_to_production_or_an_arbitrary_target(origin):
    with pytest.raises(ValueError):
        allowed_origin(origin, AC_SANDBOX)


def test_operator_requires_the_exact_staging_sandbox_id_and_allows_disposable_loopback():
    origin = "https://salesxray-staging.authorityclosers.com"
    assert allowed_origin(origin, AC_SANDBOX) == origin
    with pytest.raises(ValueError):
        allowed_origin(origin, uuid4())
    assert allowed_origin("http://127.0.0.1:1234", uuid4()) == "http://127.0.0.1:1234"


def test_large_records_split_before_the_normal_http_body_limit_and_preserve_order():
    rows = [
        SyntheticRecordInput.model_validate(
            {
                "kind": "companies",
                "key": f"syn-fixture-company-{index}",
                "business_id": "syn-fixture",
                "revision": 1,
                "occurred_at": "2017-01-01T00:00:00Z",
                "payload": {
                    "synthetic": True,
                    "schema_version": "synthetic-sales-v1.0",
                    "description": "x" * 600_000,
                },
            }
        )
        for index in range(3)
    ]
    batches = list(record_batches(rows))
    assert len(batches) == 3
    assert [row.key for batch in batches for row in batch.records] == [row.key for row in rows]
    assert all(
        len(batch.model_dump_json(by_alias=True).encode()) < 1024 * 1024 for batch in batches
    )


def test_dry_run_rejects_repeated_identity_across_separate_request_batches(tmp_path):
    data = dataset(tmp_path)
    business = data["metadata"]["business_id"]
    rows = [
        {
            "synthetic": True,
            "schema_version": "synthetic-sales-v1.0",
            "business_id": business,
            "company_id": f"{business}-company-{index}",
            "founded_on": "2017-01-01",
        }
        for index in range(128)
    ]
    path = tmp_path / "simulation/operations/companies.jsonl.gz"
    with gzip.open(path, "wt") as stream:
        for row in [*rows, rows[0]]:
            stream.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="repeated"):
        validate_dataset(tmp_path)


def test_verified_media_is_source_pinned_sent_in_bounded_transport_and_read_back(
    tmp_path, monkeypatch
):
    dataset(tmp_path)
    payload = b"fictional-mp3-transport"
    data, manifest = media_bundle(payload)
    call = data["metadata"]["call_id"]
    folder = tmp_path / "import_ready" / call
    for key in ("metadata", "transcript", "answer_key", "report", "coaching"):
        (folder / f"{key}.json").write_text(json.dumps(data[key]))
    (folder / "audio.mp3").write_bytes(payload)
    timing = json.dumps(manifest["timing"]).encode()
    (folder / "audio.timing.json").write_bytes(timing)
    manifest["verification"]["timing_sha256"] = hashlib.sha256(timing).hexdigest()
    (tmp_path / "validation").mkdir()
    (tmp_path / "validation/audio_verification.json").write_text(
        json.dumps({"synthetic": True, "calls": [manifest["verification"]]})
    )
    decoded = []
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.synthetic_import_dataset.verify_decode",
        lambda path, **kwargs: decoded.append((path, kwargs)),
    )
    receipt = validate_dataset(tmp_path)
    assert receipt["counts"]["audio"] == receipt["counts"]["audio_manifest"] == 1
    assert len(decoded) == 1
    real_client = httpx.Client
    sent = []

    def respond(request):
        sent.append(request)
        assert request.headers.get("x-ac-sandbox-tenant") == str(AC_SANDBOX)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "synthetic": True,
                    "sandbox": True,
                    "tenant_id": str(AC_SANDBOX),
                    "records": [
                        {"kind": kind, "count": count} for kind, count in receipt["counts"].items()
                    ],
                },
            )
        if request.method == "PUT":
            assert request.content == payload
            assert request.headers["content-length"] == str(len(payload))
            assert "transfer-encoding" not in request.headers
            return httpx.Response(201, json={"synthetic": True, "state": "done", "created": True})
        return httpx.Response(201, json={"synthetic": True, "state": "done", "created": 1})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    result = apply_dataset(
        tmp_path,
        origin="http://127.0.0.1:1234",
        tenant=AC_SANDBOX,
        cookie="fictional-test-session",
        receipt=receipt,
    )
    assert result["dataset_sha256"] == receipt["dataset_sha256"]
    assert sum(request.method == "PUT" for request in sent) == 1
    (folder / "audio.mp3").write_bytes(b"x" * len(payload))
    with pytest.raises(ValueError):
        list(attachments(tmp_path))


def test_operator_does_not_claim_verification_when_authored_source_changes_after_dry_run(
    tmp_path, monkeypatch
):
    data = dataset(tmp_path)
    receipt = validate_dataset(tmp_path)
    real_client = httpx.Client
    reads = []

    def respond(request):
        if request.method == "GET":
            reads.append(request.url.path)
            return httpx.Response(
                200,
                json={
                    "synthetic": True,
                    "sandbox": True,
                    "tenant_id": str(AC_SANDBOX),
                    "records": [],
                },
            )
        if request.url.path.endswith("/records"):
            call = data["metadata"]["call_id"]
            section = {"authored": "changed after the dry-run"}
            data["report"]["the_big_picture"] = section
            data["answer_key"]["report"]["the_big_picture"] = section
            for key in ("report", "answer_key"):
                (tmp_path / f"import_ready/{call}/{key}.json").write_text(json.dumps(data[key]))
        return httpx.Response(201, json={"synthetic": True, "state": "done", "created": 1})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(ValueError, match="source pin"):
        apply_dataset(
            tmp_path,
            origin="http://127.0.0.1:1234",
            tenant=AC_SANDBOX,
            cookie="fictional-test-session",
            receipt=receipt,
        )
    assert len(reads) == 1


@pytest.mark.parametrize(
    "readback",
    [
        "wrong_tenant",
        "missing_synthetic",
        "missing_sandbox",
        "not_object",
        "duplicate_counts",
        "boolean_count",
    ],
)
@pytest.mark.parametrize("stage", ["before", "after"])
def test_operator_requires_the_same_explicit_sandbox_before_writes_and_final_readback(
    tmp_path, monkeypatch, readback, stage
):
    dataset(tmp_path)
    receipt = validate_dataset(tmp_path)
    real_client = httpx.Client
    reads, writes = [], []

    def respond(request):
        if request.method != "GET":
            writes.append(request.url.path)
            return httpx.Response(201, json={"synthetic": True, "state": "done", "created": 1})
        reads.append(request.url.path)
        result = {
            "synthetic": True,
            "sandbox": True,
            "tenant_id": str(AC_SANDBOX),
            "records": [
                {"kind": kind, "count": count} for kind, count in receipt["counts"].items()
            ],
        }
        if len(reads) == (1 if stage == "before" else 2):
            if readback == "duplicate_counts":
                result["records"].append(result["records"][0])
            elif readback == "boolean_count":
                result["records"][0]["count"] = True
            elif readback == "wrong_tenant":
                result["tenant_id"] = str(uuid4())
            elif readback == "not_object":
                result = []
            else:
                result.pop(readback.removeprefix("missing_"))
        return httpx.Response(200, json=result)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    with pytest.raises(ValueError, match="sandbox"):
        apply_dataset(
            tmp_path,
            origin="http://127.0.0.1:1234",
            tenant=AC_SANDBOX,
            cookie="fictional-test-session",
            receipt=receipt,
        )
    assert len(reads) == (1 if stage == "before" else 2)
    if stage == "before":
        assert writes == []
