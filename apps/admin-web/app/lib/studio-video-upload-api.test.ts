import { createHash } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { hashBlobSha256 } from "@ac/ui/blob-sha256";
import {
  createStudioVideoUpload,
  putStudioVideoBytes,
  completeStudioVideoUpload,
  loadStudioUploadCapability,
  loadStudioUploadStatus,
  type StudioUploadIntent,
} from "../../../../packages/typescript/operations-web/src/studio/studio-video-upload-api";
const program = "11111111-1111-4111-8111-111111111111";
const upload = "22222222-2222-4222-8222-222222222222";
const asset = "33333333-3333-4333-8333-333333333333";
const version = "44444444-4444-4444-8444-444444444444";
const body = {
  filename: "lesson.mp4",
  content_type: "video/mp4" as const,
  content_length: 3,
  checksum_sha256: createHash("sha256").update("abc").digest("hex"),
};
const intent: StudioUploadIntent = {
  upload_id: upload,
  media_id: asset,
  media_version_id: version,
  version_number: 1,
  state: "uploading",
  object_key: "private/not-rendered",
  upload_url: `/v1/admin/studio/programs/${program}/video-uploads/${upload}/bytes`,
  upload_headers: {
    "content-type": "video/mp4",
    "content-length": "3",
    "x-content-sha256": body.checksum_sha256,
  },
  expires_at: "2099-01-01T00:00:00Z",
  max_bytes: 1000,
};
afterEach(() => vi.restoreAllMocks());
it.each([0, 1, 55, 56, 63, 64, 65, 256 * 1024 + 1, 2 * 1024 * 1024 + 29])(
  "hashes %i bytes against independent Node SHA256 without whole-file reads",
  async (length) => {
    const bytes = new Uint8Array(length).map((_, index) => index % 251);
    const blob = new Blob([bytes]);
    const whole = vi
      .spyOn(blob, "arrayBuffer")
      .mockRejectedValue(new Error("whole file forbidden"));
    const slice = vi.spyOn(blob, "slice");
    expect(await hashBlobSha256(blob)).toBe(
      createHash("sha256").update(bytes).digest("hex"),
    );
    expect(whole).not.toHaveBeenCalled();
    for (const [start = 0, end = length] of slice.mock.calls)
      expect(end - start).toBeLessThanOrEqual(256 * 1024);
  },
);
it("yields to rendering and can cancel a large file check before admission", async () => {
  const controller = new AbortController();
  const progress = vi.fn(() => controller.abort());
  await expect(
    hashBlobSha256(new Blob([new Uint8Array(1024 * 1024)]), {
      signal: controller.signal,
      onProgress: progress,
    }),
  ).rejects.toThrow();
  expect(progress).toHaveBeenCalledOnce();
});
it.each([
  "https://other.invalid/file",
  "//other.invalid/file",
  `/v1/admin/studio/programs/${asset}/video-uploads/${upload}/bytes`,
  intent.upload_url + "?token=anything",
])("rejects off-context upload target %s", async (upload_url) => {
  await expect(
    createStudioVideoUpload(program, body, "same-key", {
      fetcher: vi
        .fn()
        .mockResolvedValue(Response.json({ ...intent, upload_url })),
    }),
  ).rejects.toThrow();
});
it("uses the exact request identity and refuses changed envelope/extra receipt headers", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json(intent));
  expect(
    await createStudioVideoUpload(program, body, "same-key", { fetcher }),
  ).toEqual(intent);
  expect(fetcher.mock.calls[0][1]).toMatchObject({
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { "idempotency-key": "same-key" },
    body: JSON.stringify(body),
  });
  for (const headers of [
    { ...intent.upload_headers, authorization: "not-allowed" },
    { ...intent.upload_headers, "content-length": "4" },
  ]) {
    await expect(
      createStudioVideoUpload(program, body, "same-key", {
        fetcher: vi
          .fn()
          .mockResolvedValue(
            Response.json({ ...intent, upload_headers: headers }),
          ),
      }),
    ).rejects.toThrow();
  }
});
it("sends a File, not a buffered lecture, and verifies the exact 204 byte receipt", async () => {
  const file = new File(["abc"], body.filename, { type: body.content_type });
  const fetcher = vi.fn().mockResolvedValue(
    new Response(null, {
      status: 204,
      headers: {
        "x-ac-upload-bytes": "3",
        "x-ac-upload-sha256": body.checksum_sha256,
      },
    }),
  );
  await putStudioVideoBytes(program, intent, file, body, { fetcher });
  expect(fetcher.mock.calls[0][1]).toMatchObject({
    body: file,
    redirect: "error",
    credentials: "same-origin",
  });
  expect(
    new Headers(fetcher.mock.calls[0][1].headers).has("content-length"),
  ).toBe(false);
  await expect(
    putStudioVideoBytes(program, intent, file, body, {
      fetcher: vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
    }),
  ).rejects.toThrow();
});
it("completion is bodyless and bound to the same source identity", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    Response.json(
      {
        upload_id: upload,
        asset_id: asset,
        version_id: version,
        state: "processing",
        processing_job_id: program,
        replayed: false,
      },
      { status: 202 },
    ),
  );
  await completeStudioVideoUpload(program, intent, "finish-key", { fetcher });
  expect(fetcher.mock.calls[0][1].body).toBeUndefined();
  expect(fetcher.mock.calls[0][1].headers).toEqual({
    "idempotency-key": "finish-key",
  });
  await expect(
    completeStudioVideoUpload(program, intent, "finish-key", {
      fetcher: vi.fn().mockResolvedValue(
        Response.json({
          upload_id: asset,
          asset_id: asset,
          version_id: version,
          state: "processing",
          processing_job_id: program,
          replayed: true,
        }),
      ),
    }),
  ).rejects.toThrow();
});
it("rejects contradictory capability and cross-upload status", async () => {
  await expect(
    loadStudioUploadCapability(program, {
      fetcher: vi.fn().mockResolvedValue(
        Response.json({
          available: true,
          max_source_bytes: null,
          accepted_content_types: ["video/mp4", "video/webm"],
          reason: "not_configured",
        }),
      ),
    }),
  ).rejects.toThrow();
  await expect(
    loadStudioUploadStatus(program, intent, {
      fetcher: vi.fn().mockResolvedValue(
        Response.json({
          upload_id: asset,
          asset_id: asset,
          version_id: version,
          state: "ready",
          label: "Lesson",
          expires_at: intent.expires_at,
          declared_bytes: 3,
          uploaded_bytes: 3,
          duration_seconds: 1,
          width: 320,
          height: 180,
        }),
      ),
    }),
  ).rejects.toThrow();
});
it("rejects a ready status with incomplete bytes or missing measured video metadata", async () => {
  const ready = {
    upload_id: upload,
    asset_id: asset,
    version_id: version,
    state: "ready",
    label: "Lesson",
    expires_at: intent.expires_at,
    declared_bytes: 3,
    uploaded_bytes: 3,
    duration_seconds: 1,
    width: 320,
    height: 180,
  };
  for (const patch of [
    { uploaded_bytes: 1 },
    { uploaded_bytes: null },
    { duration_seconds: null },
    { width: null, height: null },
  ]) {
    await expect(
      loadStudioUploadStatus(program, intent, {
        fetcher: vi
          .fn()
          .mockResolvedValue(Response.json({ ...ready, ...patch })),
      }),
    ).rejects.toThrow();
  }
});
