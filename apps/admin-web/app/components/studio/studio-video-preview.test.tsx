// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { StudioVideoPreview } from "../../../../../packages/typescript/operations-web/src/studio/studio-video-preview";
import { loadStudioVideoPreview } from "../../../../../packages/typescript/operations-web/src/studio/studio-video-preview-api";
import { StudioLessonVideoPreview } from "../../../../../packages/typescript/operations-web/src/studio/studio-lesson-video-preview";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const identity = {
  programId: "11111111-1111-4111-8111-111111111111",
  assetId: "22222222-2222-4222-8222-222222222222",
  versionId: "33333333-3333-4333-8333-333333333333",
};
const path = `/v1/admin/studio/programs/${identity.programId}/videos/${identity.assetId}/versions/${identity.versionId}/preview`;
const data = {
  program_id: identity.programId,
  asset_id: identity.assetId,
  version_id: identity.versionId,
  content_type: "video/mp4",
  byte_length: 12345,
  duration_seconds: 74,
  preview_href: `${path}/bytes`,
};
let root: Root;
let container: HTMLDivElement;
let fetcher: ReturnType<typeof vi.fn>;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetcher = vi.fn(async () => Response.json(data));
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
async function render(scope = "test-person:tenant:session") {
  await act(async () =>
    root.render(
      <StudioVideoPreview
        {...identity}
        recoveryContext={scope}
        label="Discovery lesson.mp4"
      />,
    ),
  );
}
async function click(text: string) {
  const button = [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes(text),
  );
  expect(button).toBeDefined();
  await act(async () => button!.click());
}
it("does not request video or descriptor until explicitly opened", async () => {
  await render();
  expect(fetcher).not.toHaveBeenCalled();
  expect(container.querySelector("video")).toBeNull();
  await click("Preview video");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith(
    path,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    }),
  );
  const video = container.querySelector("video")!;
  expect(video.getAttribute("src")).toBe(data.preview_href);
  expect(video.controls).toBe(true);
  expect(video.autoplay).toBe(false);
  expect(video.getAttribute("preload")).toBe("metadata");
  expect(video.getAttribute("playsinline")).not.toBeNull();
});
it("closes and unloads playback, then restores keyboard focus", async () => {
  await render();
  await click("Preview video");
  const video = container.querySelector("video")!;
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[aria-label="Close video preview"]')!
      .click(),
  );
  expect(video.pause).toHaveBeenCalled();
  expect(video.getAttribute("src")).toBeNull();
  expect(container.querySelector("video")).toBeNull();
  expect(document.activeElement?.textContent).toContain("Preview video");
});
it("isolates late descriptors across a session change", async () => {
  let resolve!: (value: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  await render();
  await click("Preview video");
  await render("other-session");
  await act(async () => resolve(Response.json(data)));
  expect(container.querySelector("video")).toBeNull();
  expect(container.textContent).not.toContain("Discovery lesson.mp4");
});
it.each([401, 403, 404, 410])(
  "shows a private access recovery for %i, never a video",
  async (status) => {
    fetcher.mockResolvedValueOnce(new Response(null, { status }));
    await render();
    await click("Preview video");
    expect(container.textContent).toContain("Preview access changed");
    expect(container.querySelector("video")).toBeNull();
  },
);
it("offers retry without claiming unconfigured video is playable", async () => {
  fetcher.mockResolvedValueOnce(new Response(null, { status: 503 }));
  await render();
  await click("Preview video");
  expect(container.textContent).toContain("not enabled");
  await click("Retry preview");
  expect(container.querySelector("video")).not.toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("unloads a failed media source and rechecks authority on retry", async () => {
  await render();
  await click("Preview video");
  await act(async () =>
    container.querySelector("video")!.dispatchEvent(new Event("error")),
  );
  expect(container.querySelector("video")).toBeNull();
  expect(container.textContent).toContain("couldn’t play");
  await click("Retry preview");
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("keeps keyboard focus in the preview during retry and media failure", async () => {
  fetcher.mockResolvedValueOnce(new Response(null, { status: 503 }));
  await render();
  await click("Preview video");
  const retry = [...container.querySelectorAll("button")].find((item) =>
    item.textContent?.includes("Retry preview"),
  )!;
  retry.focus();
  await act(async () => retry.click());
  const stage = container.querySelector("section")!;
  expect(document.activeElement).toBe(stage);
  const video = container.querySelector("video")!;
  video.tabIndex = 0;
  video.focus();
  expect(document.activeElement).toBe(video);
  await act(async () => video.dispatchEvent(new Event("error")));
  expect(document.activeElement).toBe(stage);
  expect(container.querySelector("video")).toBeNull();
});
it("bounds descriptor and media loading with retryable failure states", async () => {
  vi.useFakeTimers();
  fetcher.mockImplementationOnce(() => new Promise<Response>(() => {}));
  await render();
  await click("Preview video");
  await act(async () => vi.advanceTimersByTimeAsync(12_000));
  expect(container.textContent).toContain("too long to respond");
  await click("Retry preview");
  expect(container.querySelector("video")).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(container.querySelector("video")).toBeNull();
  expect(container.textContent).toContain("taking too long to load");
});
it.each(["draft", "archived", "unavailable"])(
  "does not preview a lesson after its authoritative status becomes %s",
  async (version_status) => {
    fetcher.mockResolvedValueOnce(
      Response.json({
        activity_id: identity.assetId,
        version_status,
        binding: {
          binding_id: identity.programId,
          asset_id: identity.assetId,
          version_id: identity.versionId,
          label: "Private upload",
          state: "approved",
        },
      }),
    );
    await act(async () =>
      root.render(
        <StudioLessonVideoPreview
          programId={identity.programId}
          activityId={identity.assetId}
          recoveryContext="test-person:tenant:session"
          versionStatus="published"
          canWrite
        />,
      ),
    );
    expect(container.textContent).toContain("couldn’t be checked");
    expect(container.querySelector("button")).toBeNull();
    expect(fetcher).toHaveBeenCalledOnce();
  },
);
it("does not expose a source without a current recovery context", async () => {
  await render("");
  expect(container.querySelector("button")!.disabled).toBe(true);
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([
  "https://example.test/video.mp4",
  "//example.test/video.mp4",
  `${path}/bytes?tenant=other`,
  `${path}/bytes#fragment`,
  `/v1/media/arbitrary`,
])("rejects unowned descriptor target %s", async (preview_href) => {
  await expect(
    loadStudioVideoPreview(identity, {
      fetcher: vi.fn(async () => Response.json({ ...data, preview_href })),
    }),
  ).rejects.toThrow();
});
it.each(["program_id", "asset_id", "version_id"])(
  "rejects mismatched %s",
  async (key) => {
    await expect(
      loadStudioVideoPreview(identity, {
        fetcher: vi.fn(async () =>
          Response.json({
            ...data,
            [key]: "44444444-4444-4444-8444-444444444444",
          }),
        ),
      }),
    ).rejects.toThrow();
  },
);
it.each([
  { byte_length: -1 },
  { byte_length: 9 * 1024 ** 3 },
  { content_type: "text/html" },
  { duration_seconds: 0 },
  { unexpected: true },
])("rejects malformed descriptor %j", async (changed) => {
  await expect(
    loadStudioVideoPreview(identity, {
      fetcher: vi.fn(async () => Response.json({ ...data, ...changed })),
    }),
  ).rejects.toThrow();
});
