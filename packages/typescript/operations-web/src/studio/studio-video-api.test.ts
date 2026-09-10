import { afterEach, expect, it, vi } from "vitest";
import { AdminApiProblem } from "../admin-api";
import {
  loadStudioActivityVideo,
  loadStudioVideos,
  saveStudioActivityVideo,
  type StudioVideoSelection,
} from "./studio-video-api";

const programId = "11111111-1111-4111-8111-111111111111";
const activityId = "22222222-2222-4222-8222-222222222222";
const assetId = "33333333-3333-4333-8333-333333333333";
const versionId = "44444444-4444-4444-8444-444444444444";
const bindingId = "55555555-5555-4555-8555-555555555555";
const item = {
  asset_id: assetId,
  version_id: versionId,
  version_number: 2,
  label: "Discovery.mp4",
  state: "ready",
  actual_bytes: 1000,
  duration_seconds: 14.5,
  width: 1920,
  height: 1080,
};
const selection: StudioVideoSelection = {
  asset_id: assetId,
  version_id: versionId,
  expected_binding_id: null,
  approval_reference: "Reviewed source",
};
const receipt = {
  binding_id: bindingId,
  asset_id: assetId,
  version_id: versionId,
  state: "approved",
  replayed: false,
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
afterEach(() => vi.restoreAllMocks());

it("requests a bounded same-origin library page with credentials, no cache, and no redirects", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json({ items: [item], next_cursor: assetId }));
  const result = await loadStudioVideos({ programId, fetcher });
  expect(result.items[0].label).toBe("Discovery.mp4");
  expect(fetcher).toHaveBeenCalledWith(
    `/v1/admin/studio/programs/${programId}/videos?limit=24`,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
});

it("passes the cursor as a validated position and rejects nonadvancing responses", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json({ items: [item], next_cursor: null }));
  await expect(
    loadStudioVideos({ programId, after: assetId, fetcher }),
  ).rejects.toThrow("did not advance");
  expect(fetcher.mock.calls[0][0]).toBe(
    `/v1/admin/studio/programs/${programId}/videos?limit=24&after=${assetId}`,
  );
});

it.each([
  "https://private.example/video",
  "../another-course",
  `${programId}?tenant=other`,
])("refuses untrusted identifiers before fetch: %s", async (invalid) => {
  const fetcher = vi.fn<typeof fetch>();
  await expect(
    loadStudioVideos({ programId: invalid, fetcher }),
  ).rejects.toThrow();
  await expect(
    loadStudioVideos({ programId, after: invalid, fetcher }),
  ).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([
  { ...item, url: "https://private.example" },
  { ...item, provider_asset_id: "private-provider" },
  { ...item, width: null },
  { ...item, actual_bytes: 0 },
  { ...item, duration_seconds: -1 },
  { ...item, state: "processing" },
])("rejects malformed or expanded media metadata", async (candidate) => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json({ items: [candidate], next_cursor: null }));
  await expect(loadStudioVideos({ programId, fetcher })).rejects.toThrow();
});

it("rejects duplicated rows, oversized pages, and a cursor unrelated to the returned page", async () => {
  for (const payload of [
    { items: [item, item], next_cursor: null },
    { items: Array.from({ length: 25 }, () => item), next_cursor: null },
    { items: [item], next_cursor: versionId },
    { items: [], next_cursor: assetId },
  ]) {
    await expect(
      loadStudioVideos({
        programId,
        fetcher: vi.fn<typeof fetch>().mockResolvedValue(json(payload)),
      }),
    ).rejects.toThrow();
  }
});

it("binds the current-video response to the requested activity", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
    json({
      activity_id: activityId,
      version_status: "published",
      binding: null,
    }),
  );
  expect(
    (await loadStudioActivityVideo({ programId, activityId, fetcher })).binding,
  ).toBeNull();
  expect(fetcher.mock.calls[0][0]).toBe(
    `/v1/admin/studio/programs/${programId}/activities/${activityId}/video`,
  );
  fetcher.mockResolvedValue(
    json({
      activity_id: bindingId,
      version_status: "published",
      binding: null,
    }),
  );
  await expect(
    loadStudioActivityVideo({ programId, activityId, fetcher }),
  ).rejects.toThrow("context changed");
});

it("sends only the exact selection and caller-retained idempotency key", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockImplementation(async () => json(receipt));
  await saveStudioActivityVideo({
    programId,
    activityId,
    selection,
    idempotencyKey: "same-command",
    fetcher,
  });
  await saveStudioActivityVideo({
    programId,
    activityId,
    selection,
    idempotencyKey: "same-command",
    fetcher,
  });
  const first = fetcher.mock.calls[0];
  expect(first[0]).toBe(
    `/v1/admin/studio/programs/${programId}/activities/${activityId}/video`,
  );
  expect(first[1]).toMatchObject({
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    body: JSON.stringify(selection),
    headers: { "idempotency-key": "same-command" },
  });
  expect(fetcher.mock.calls[1][1]).toEqual(first[1]);
});

it("rejects forged scope, missing expectation, unsafe approval, or header injection before save", async () => {
  const fetcher = vi.fn<typeof fetch>();
  for (const body of [
    { ...selection, tenant_id: programId },
    {
      asset_id: assetId,
      version_id: versionId,
      approval_reference: "Reviewed",
    },
    { ...selection, approval_reference: "   " },
    { ...selection, approval_reference: "Reviewed\u202e" },
  ]) {
    await expect(
      saveStudioActivityVideo({
        programId,
        activityId,
        selection: body as StudioVideoSelection,
        idempotencyKey: "command",
        fetcher,
      }),
    ).rejects.toThrow();
  }
  await expect(
    saveStudioActivityVideo({
      programId,
      activityId,
      selection,
      idempotencyKey: "bad\nheader",
      fetcher,
    }),
  ).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});

it("treats a mismatched success receipt as unconfirmed", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json({ ...receipt, asset_id: bindingId }));
  await expect(
    saveStudioActivityVideo({
      programId,
      activityId,
      selection,
      idempotencyKey: "command",
      fetcher,
    }),
  ).rejects.toThrow("receipt did not match");
});

it("uses the existing AdminApiProblem identity and safely handles non-JSON errors", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
    json(
      {
        code: "media_conflict",
        title: "Conflict",
        detail: "Changed",
        request_id: "request-1",
      },
      409,
    ),
  );
  const failure = await loadStudioVideos({ programId, fetcher }).catch(
    (error: unknown) => error,
  );
  expect(failure).toBeInstanceOf(AdminApiProblem);
  expect(failure).toMatchObject({
    status: 409,
    code: "media_conflict",
    requestId: "request-1",
  });
  fetcher.mockResolvedValue(
    new Response("gateway unavailable", { status: 502 }),
  );
  await expect(loadStudioVideos({ programId, fetcher })).rejects.toMatchObject({
    status: 502,
    code: "http_502",
  });
});
