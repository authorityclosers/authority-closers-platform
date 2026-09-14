// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { File as NodeFile } from "node:buffer";
import {
  StudioVideoUpload,
  videoFileSize,
} from "../../../../../packages/typescript/operations-web/src/studio/studio-video-upload";
import {
  activateStudioUploadScope,
  restrictStudioUploadScope,
  studioUploadSession,
} from "../../../../../packages/typescript/operations-web/src/studio/studio-video-upload-session";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const program = "11111111-1111-4111-8111-111111111111";
const upload = "22222222-2222-4222-8222-222222222222";
const asset = "33333333-3333-4333-8333-333333333333";
const version = "44444444-4444-4444-8444-444444444444";
const scope = "synthetic-person-tenant-session";
const digest =
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
const capability = {
  available: true,
  max_source_bytes: 10 * 1024 ** 2,
  accepted_content_types: ["video/mp4", "video/webm"],
  reason: null,
};
const intent = {
  upload_id: upload,
  media_id: asset,
  media_version_id: version,
  version_number: 1,
  state: "uploading",
  object_key: "private/never-render",
  upload_url: `/v1/admin/studio/programs/${program}/video-uploads/${upload}/bytes`,
  upload_headers: {
    "content-type": "video/mp4",
    "content-length": "3",
    "x-content-sha256": digest,
  },
  expires_at: "2099-01-01T00:00:00Z",
  max_bytes: 1000,
};
let container: HTMLDivElement;
let root: Root;
let state = "uploading";
let fetcher: ReturnType<typeof vi.fn>;
const ready = vi.fn();
const pending = vi.fn();
function file() {
  return new NodeFile(["abc"], "Sales discovery.mp4", {
    type: "video/mp4",
  }) as unknown as File;
}
beforeEach(() => {
  activateStudioUploadScope("");
  ready.mockClear();
  pending.mockClear();
  state = "uploading";
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/video-upload-capability"))
      return Response.json(capability);
    if (path.endsWith("/video-uploads")) return Response.json(intent);
    if (path.endsWith("/bytes"))
      return new Response(null, {
        status: 204,
        headers: { "x-ac-upload-bytes": "3", "x-ac-upload-sha256": digest },
      });
    if (path.endsWith("/complete")) {
      state = "processing";
      return Response.json({
        upload_id: upload,
        asset_id: asset,
        version_id: version,
        state,
        processing_job_id: program,
        replayed: false,
      });
    }
    if (init?.method === "GET")
      return Response.json({
        upload_id: upload,
        asset_id: asset,
        version_id: version,
        state,
        label: "Sales discovery.mp4",
        declared_bytes: 3,
        uploaded_bytes: state === "uploading" ? null : 3,
        expires_at: intent.expires_at,
        duration_seconds: state === "ready" ? 1 : null,
        width: state === "ready" ? 320 : null,
        height: state === "ready" ? 180 : null,
      });
    throw new Error("Unexpected route");
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  activateStudioUploadScope("");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function mount(canWrite = true) {
  await act(async () =>
    root.render(
      <StrictMode>
        <StudioVideoUpload
          programId={program}
          recoveryContext={scope}
          canWrite={canWrite}
          onReady={ready}
          onPendingChange={pending}
        />
      </StrictMode>,
    ),
  );
}
function button(text: string) {
  return [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
}
it("mounts a labelled, format/limit-aware upload control only after verified capability", async () => {
  await mount();
  expect(container.textContent).toContain("MP4 or WebM, up to 10.5 MB");
  expect(button("Choose video")).toBeDefined();
  expect(
    container.querySelector('input[type="file"]')?.getAttribute("aria-label"),
  ).toBe("Choose a course video");
  expect(container.textContent).not.toContain("private/");
});
it("labels the decimal source ceiling without converting it to a binary limit", () => {
  expect(videoFileSize(2_000_000_000)).toBe("2.0 GB");
});
it("offers no misleading file control when runtime is not configured or the editor is read only", async () => {
  fetcher.mockImplementation(async () =>
    Response.json({
      ...capability,
      available: false,
      max_source_bytes: null,
      reason: "not_configured",
    }),
  );
  await mount();
  expect(button("Choose video")).toBeUndefined();
  expect(container.textContent).toContain("aren’t available");
  await mount(false);
  expect(container.textContent).toBe("");
});
it("shows processing separately from ready and refreshes the library only for canonical ready", async () => {
  await mount();
  await act(async () =>
    studioUploadSession(scope, program).start(
      file(),
      capability.max_source_bytes,
    ),
  );
  expect(container.textContent).toContain("Your upload is saved");
  expect(ready).not.toHaveBeenCalled();
  expect(button("Choose video")).toBeUndefined();
  expect(container.querySelector("video,iframe")).toBeNull();
  state = "ready";
  await act(async () => studioUploadSession(scope, program).check());
  expect(container.textContent).toContain("Ready in your video library");
  expect(ready).toHaveBeenCalledOnce();
  expect(pending).toHaveBeenLastCalledWith(false);
});
it("a failed processing status read keeps recovery visible without permitting a replacement upload", async () => {
  await mount();
  await act(async () =>
    studioUploadSession(scope, program).start(
      file(),
      capability.max_source_bytes,
    ),
  );
  fetcher.mockRejectedValueOnce(new TypeError("offline"));
  await act(async () => studioUploadSession(scope, program).check());
  expect(button("Check video status")).toBeDefined();
  expect(button("Choose video")).toBeUndefined();
  expect(ready).not.toHaveBeenCalled();
});
it("hides filename and releases the selected File when verified course authority is revoked", async () => {
  await mount();
  fetcher.mockRejectedValueOnce(new TypeError("lost admission response"));
  await act(async () =>
    studioUploadSession(scope, program).start(
      file(),
      capability.max_source_bytes,
    ),
  );
  await act(async () => restrictStudioUploadScope(scope, () => false));
  expect(container.textContent).not.toContain("Sales discovery.mp4");
  expect(button("Select the same video")).toBeDefined();
  expect(studioUploadSession(scope, program).getSnapshot().needsFile).toBe(
    true,
  );
});

it("drops one file through the same admitted upload and rejects multiple selections", async () => {
  await mount();
  const dropzone = container.querySelector("[data-dragging]")!;
  const multiple = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(multiple, "dataTransfer", {
    value: { files: [file(), file()] },
  });
  await act(async () => {
    dropzone.dispatchEvent(multiple);
  });
  expect(container.textContent).toContain("Drop one video at a time.");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false,
  );
  const drop = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file()] } });
  await act(async () => {
    dropzone.dispatchEvent(drop);
    await vi.waitFor(() => {
      expect(studioUploadSession(scope, program).getSnapshot().stage).toBe(
        "processing",
      );
    });
  });
  expect(drop.defaultPrevented).toBe(true);
  expect(container.textContent).toContain("Your upload is saved");
  expect(container.textContent).not.toContain("Drop one video at a time.");
  expect(
    fetcher.mock.calls.filter(([path]) =>
      String(path).endsWith("/video-uploads"),
    ),
  ).toHaveLength(1);
  expect(
    fetcher.mock.calls.filter(([, init]) => init?.method === "PUT"),
  ).toHaveLength(1);
});

it("checks availability once when its memory session attaches outside StrictMode", async () => {
  await act(async () =>
    root.render(
      <StudioVideoUpload
        programId={program}
        recoveryContext={scope}
        canWrite
      />,
    ),
  );
  expect(
    fetcher.mock.calls.filter(([path]) =>
      String(path).endsWith("/video-upload-capability"),
    ),
  ).toHaveLength(1);
});
