// @vitest-environment happy-dom
import { File as NodeFile } from "node:buffer";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  activateStudioUploadScope,
  restrictStudioUploadScope,
  studioUploadSession,
} from "../../../../packages/typescript/operations-web/src/studio/studio-video-upload-session";
import { newIdempotencyKey } from "../../../../packages/typescript/operations-web/src/admin-api";
const program = "11111111-1111-4111-8111-111111111111";
const upload = "22222222-2222-4222-8222-222222222222";
const asset = "33333333-3333-4333-8333-333333333333";
const version = "44444444-4444-4444-8444-444444444444";
const digest =
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
const file = () =>
  new NodeFile(["abc"], "Lesson.mp4", { type: "video/mp4" }) as unknown as File;
const intent = {
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
    "x-content-sha256": digest,
  },
  expires_at: "2099-01-01T00:00:00Z",
  max_bytes: 1000,
};
const status = (state = "uploading") => ({
  upload_id: upload,
  asset_id: asset,
  version_id: version,
  state,
  label: "Lesson.mp4",
  expires_at: intent.expires_at,
  declared_bytes: 3,
  uploaded_bytes: state === "uploading" ? null : 3,
  duration_seconds: state === "ready" ? 1 : null,
  width: state === "ready" ? 320 : null,
  height: state === "ready" ? 180 : null,
});
function harness() {
  let state = "uploading";
  const fetcher = vi.fn(
    async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const path = String(url);
      if (path.endsWith("/video-uploads")) return Response.json(intent);
      if (path.endsWith("/bytes"))
        return new Response(null, {
          status: 204,
          headers: { "x-ac-upload-bytes": "3", "x-ac-upload-sha256": digest },
        });
      if (path.endsWith("/complete")) {
        state = "processing";
        return Response.json(
          {
            upload_id: upload,
            asset_id: asset,
            version_id: version,
            state,
            processing_job_id: program,
            replayed: false,
          },
          { status: 202 },
        );
      }
      if (init?.method === "GET") return Response.json(status(state));
      throw new Error("Unexpected request");
    },
  );
  vi.stubGlobal("fetch", fetcher);
  return {
    fetcher,
    setState: (value: string) => {
      state = value;
    },
  };
}
beforeEach(() => activateStudioUploadScope("synthetic-session"));
afterEach(() => {
  activateStudioUploadScope("");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it("runs admission → file → completion → canonical processing, not fake ready/publication", async () => {
  const { fetcher, setState } = harness();
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 1000);
  expect(session.getSnapshot()).toMatchObject({
    stage: "processing",
    pending: false,
    busy: false,
    status: { state: "processing" },
  });
  expect(
    fetcher.mock.calls.filter(([url]) => String(url).endsWith("/bytes")),
  ).toHaveLength(1);
  expect(
    fetcher.mock.calls.some(([url]) =>
      /publish|\/activities\//.test(String(url)),
    ),
  ).toBe(false);
  setState("ready");
  await session.check();
  expect(session.getSnapshot()).toMatchObject({
    stage: "ready",
    status: { width: 320, height: 180 },
  });
});
it("retries an unknown admission with the exact key and file checksum", async () => {
  const { fetcher } = harness();
  fetcher.mockRejectedValueOnce(new TypeError("synthetic lost response"));
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 1000);
  expect(session.getSnapshot()).toMatchObject({
    stage: "error",
    pending: true,
  });
  await session.start(file(), 1000); // no second command may replace unresolved intent
  await session.resume();
  const creates = fetcher.mock.calls.filter(([url]) =>
    String(url).endsWith("/video-uploads"),
  );
  expect(creates).toHaveLength(2);
  expect(creates[0][1]?.headers).toEqual(creates[1][1]?.headers);
  expect(creates[0][1]?.body).toBe(creates[1][1]?.body);
  expect(JSON.parse(String(creates[1][1]?.body)).checksum_sha256).toBe(digest);
  expect(session.getSnapshot().stage).toBe("processing");
});
it("retains completion identity without resending bytes after an uncertain completion", async () => {
  const { fetcher } = harness();
  const handler = fetcher.getMockImplementation()!;
  let first = true;
  fetcher.mockImplementation(async (url, init) => {
    if (String(url).endsWith("/complete") && first) {
      first = false;
      throw new TypeError("synthetic timeout");
    }
    return handler(url, init);
  });
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 1000);
  expect(session.getSnapshot().stage).toBe("error");
  const same = studioUploadSession("synthetic-session", program);
  expect(same).toBe(session);
  await same.resume();
  const completes = fetcher.mock.calls.filter(([url]) =>
    String(url).endsWith("/complete"),
  );
  expect(completes).toHaveLength(2);
  expect(completes[0][1]?.headers).toEqual(completes[1][1]?.headers);
  expect(
    fetcher.mock.calls.filter(([url]) => String(url).endsWith("/bytes")),
  ).toHaveLength(1);
});
it("refuses invalid/oversized files before any hashing or API write", async () => {
  const { fetcher } = harness();
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 2);
  await session.start(
    new NodeFile(["abc"], "bad.exe", {
      type: "application/octet-stream",
    }) as unknown as File,
    1000,
  );
  expect(fetcher).not.toHaveBeenCalled();
  expect(session.getSnapshot().pending).toBe(false);
});
it("changing verified identity destroys private source state and stops the next mutation", async () => {
  const { fetcher } = harness();
  let release!: (value: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const session = studioUploadSession("synthetic-session", program);
  const running = session.start(file(), 1000);
  while (!release) await new Promise((resolve) => setTimeout(resolve, 1));
  activateStudioUploadScope("another-session");
  release(Response.json(intent));
  await running;
  expect(fetcher).toHaveBeenCalledOnce();
  expect(session.getSnapshot().filename).toBe("");
  expect(
    studioUploadSession("another-session", program).getSnapshot().stage,
  ).toBe("idle");
});
it("pauses admitted work and keeps a global unload guard after the UI unsubscribes", async () => {
  const { fetcher } = harness();
  const handler = fetcher.getMockImplementation()!;
  let release!: (value: Response) => void;
  fetcher.mockImplementation((url, init) =>
    String(url).endsWith("/bytes")
      ? new Promise((resolve) => {
          release = resolve;
        })
      : handler(url, init),
  );
  const session = studioUploadSession("synthetic-session", program);
  const unsubscribe = session.subscribe(() => {});
  const running = session.start(file(), 1000);
  while (!release) await new Promise((resolve) => setTimeout(resolve, 1));
  session.pause();
  unsubscribe();
  release(
    new Response(null, {
      status: 204,
      headers: { "x-ac-upload-bytes": "3", "x-ac-upload-sha256": digest },
    }),
  );
  await running;
  expect(session.getSnapshot()).toMatchObject({
    stage: "paused",
    pending: true,
    busy: false,
  });
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(
    fetcher.mock.calls.some(([url]) => String(url).endsWith("/complete")),
  ).toBe(false);
});
it("visiting more than twenty courses evicts only empty inactive entries", () => {
  const subscribed = studioUploadSession("synthetic-session", program);
  const unsubscribe = subscribed.subscribe(() => {});
  for (let index = 0; index < 30; index++)
    expect(() =>
      studioUploadSession("synthetic-session", `course-${index}`),
    ).not.toThrow();
  expect(studioUploadSession("synthetic-session", program)).toBe(subscribed);
  unsubscribe();
});
it("a processing status read failure cannot be replaced with a new upload", async () => {
  const { fetcher } = harness();
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 1000);
  fetcher.mockRejectedValueOnce(new TypeError("offline"));
  await session.check();
  expect(session.getSnapshot()).toMatchObject({
    stage: "error",
    pending: false,
    status: { state: "processing" },
  });
  const count = fetcher.mock.calls.length;
  await session.start(file(), 1000);
  expect(fetcher).toHaveBeenCalledTimes(count);
  await session.check();
  expect(session.getSnapshot().stage).toBe("processing");
});
it("a verified permission downgrade releases the file but preserves exact recovery identity", async () => {
  const { fetcher } = harness();
  fetcher.mockRejectedValueOnce(new TypeError("lost admission response"));
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 1000);
  const original = fetcher.mock.calls[0][1];
  restrictStudioUploadScope("synthetic-session", () => false);
  expect(session.getSnapshot()).toMatchObject({
    stage: "denied",
    needsFile: true,
    pending: true,
  });
  await session.resume();
  expect(session.getSnapshot()).toMatchObject({
    stage: "paused",
    needsFile: true,
  });
  expect(
    fetcher.mock.calls.some(([url]) => String(url).endsWith("/bytes")),
  ).toBe(false);
  await session.start(
    new NodeFile(["xyz"], "Lesson.mp4", {
      type: "video/mp4",
    }) as unknown as File,
    1000,
  );
  expect(session.getSnapshot()).toMatchObject({
    needsFile: true,
    message: expect.stringContaining("different file"),
  });
  await session.start(file(), 1000);
  expect(session.getSnapshot().stage).toBe("processing");
  const creates = fetcher.mock.calls.filter(([url]) =>
    String(url).endsWith("/video-uploads"),
  );
  expect(creates[1][1]?.headers).toEqual(original?.headers);
});
it("unmounting during a processing status check retains automatic and manual recovery", async () => {
  const { fetcher } = harness();
  const session = studioUploadSession("synthetic-session", program);
  await session.start(file(), 1000);
  let release!: (value: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const checking = session.check();
  session.pause();
  release(Response.json({}));
  await checking;
  expect(session.getSnapshot()).toMatchObject({
    stage: "processing",
    pending: false,
    busy: false,
  });
  await session.check();
  expect(session.getSnapshot().stage).toBe("processing");
});
it("can create idempotency keys in this secure local browser fixture", () => {
  expect(newIdempotencyKey()).toMatch(/^[A-Za-z0-9_-]{1,128}$/);
});
