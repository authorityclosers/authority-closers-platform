// @vitest-environment happy-dom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as admin from "../admin-api";
import * as api from "./studio-video-api";
import {
  activateStudioVideoRecoveryScope,
  readStudioVideoRecoveryActivity,
  StudioVideoPanel,
  type StudioVideoPanelProps,
} from "./studio-video-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const programId = "11111111-1111-4111-8111-111111111111";
const activityId = "22222222-2222-4222-8222-222222222222";
const assetId = "33333333-3333-4333-8333-333333333333";
const versionId = "44444444-4444-4444-8444-444444444444";
const bindingId = "55555555-5555-4555-8555-555555555555";
const otherId = "66666666-6666-4666-8666-666666666666";
const choice: api.StudioVideoChoice = {
  asset_id: assetId,
  version_id: versionId,
  version_number: 2,
  label: "Discovery lesson.mp4",
  state: "ready",
  actual_bytes: 2 * 1024 * 1024,
  duration_seconds: 74,
  width: 1920,
  height: 1080,
};
const emptyCurrent: api.StudioActivityVideo = {
  activity_id: activityId,
  version_status: "published",
  binding: null,
};
const receipt: api.StudioVideoReceipt = {
  binding_id: bindingId,
  asset_id: assetId,
  version_id: versionId,
  state: "approved",
  replayed: false,
};
const props: StudioVideoPanelProps = {
  programId,
  activityId,
  versionStatus: "published",
  canWrite: true,
  recoveryContext: "synthetic-person:tenant:session",
};

let container: HTMLDivElement;
let root: Root;
let unmounted = false;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function problem(status: number) {
  return new admin.AdminApiProblem({
    status,
    code: `http_${status}`,
    title: "Synthetic rejection",
    detail: "Synthetic rejection",
    requestId: null,
  });
}
beforeEach(() => {
  activateStudioVideoRecoveryScope("");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
  vi.spyOn(api, "loadStudioActivityVideo").mockResolvedValue(emptyCurrent);
  vi.spyOn(api, "loadStudioVideos").mockResolvedValue({
    items: [choice],
    next_cursor: null,
  });
  vi.spyOn(api, "saveStudioActivityVideo").mockResolvedValue(receipt);
  let sequence = 0;
  vi.spyOn(admin, "newIdempotencyKey").mockImplementation(
    () => `video-command-${++sequence}`,
  );
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  activateStudioVideoRecoveryScope("");
  vi.restoreAllMocks();
});
async function mount(changes: Partial<StudioVideoPanelProps> = {}) {
  await act(async () =>
    root.render(
      <StrictMode>
        <StudioVideoPanel {...props} {...changes} />
      </StrictMode>,
    ),
  );
}
function button(text: string) {
  const result = [...container.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === text,
  );
  expect(result, `button ${text}`).toBeDefined();
  return result!;
}
async function click(element: HTMLElement) {
  await act(async () => element.click());
}
async function selectAndApprove(reference = "Reviewed lesson source") {
  const radio = container.querySelector<HTMLInputElement>(
    'input[type="radio"]',
  )!;
  expect(radio).not.toBeNull();
  await click(radio);
  const input = container.querySelector<HTMLInputElement>(
    'input:not([type="radio"])',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, reference);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("renders real source metadata and explicit approval without a form or preview", async () => {
  await mount();
  expect(container.textContent).toContain(
    "No video approved for this lesson yet",
  );
  expect(container.textContent).toContain(
    "Version 2 · 1:14 · 1920 × 1080 · 2.0 MB",
  );
  expect(container.querySelector("form, img, video, iframe")).toBeNull();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  expect(api.saveStudioActivityVideo).toHaveBeenCalledTimes(1);
  expect(api.saveStudioActivityVideo).toHaveBeenCalledWith(
    expect.objectContaining({
      programId,
      activityId,
      idempotencyKey: "video-command-1",
      selection: {
        asset_id: assetId,
        version_id: versionId,
        expected_binding_id: null,
        approval_reference: "Reviewed lesson source",
      },
    }),
  );
  expect(container.textContent).toContain("Video approved for this lesson");
  expect(container.textContent).toContain("Approved");
});

it.each([
  { canWrite: false },
  { versionStatus: "draft" },
  { versionStatus: "unknown" },
  { recoveryContext: "" },
])(
  "does not request or mutate videos for an unavailable context: %o",
  async (changes) => {
    await mount(changes);
    expect(api.loadStudioVideos).not.toHaveBeenCalled();
    expect(api.loadStudioActivityVideo).not.toHaveBeenCalled();
    expect(api.saveStudioActivityVideo).not.toHaveBeenCalled();
    expect(container.querySelector("input")).toBeNull();
  },
);

it("honors the freshly loaded draft status despite a stale published prop", async () => {
  vi.mocked(api.loadStudioActivityVideo).mockResolvedValue({
    ...emptyCurrent,
    version_status: "draft",
  });
  await mount();
  expect(api.loadStudioVideos).not.toHaveBeenCalled();
  expect(container.textContent).toContain(
    "unavailable for this course version",
  );
  expect(container.querySelector("input")).toBeNull();
});

it("shows loading, empty, and retryable read errors", async () => {
  const pending = deferred<api.StudioActivityVideo>();
  vi.mocked(api.loadStudioActivityVideo).mockReturnValue(pending.promise);
  await mount();
  expect(container.textContent).toContain("Loading video details");
  await act(async () => pending.reject(new Error("offline")));
  expect(container.textContent).toContain("could not be loaded");
  vi.mocked(api.loadStudioActivityVideo).mockResolvedValue(emptyCurrent);
  vi.mocked(api.loadStudioVideos).mockResolvedValue({
    items: [],
    next_cursor: null,
  });
  await click(button("Refresh lesson"));
  expect(container.textContent).toContain("No ready videos available");
  expect(container.querySelector("input")).toBeNull();
});

it("hides selection on a permission denial and explains access recovery", async () => {
  vi.mocked(api.loadStudioActivityVideo).mockRejectedValue(problem(403));
  await mount();
  expect(container.textContent).toContain(
    "editing access could not be confirmed",
  );
  expect(api.loadStudioVideos).not.toHaveBeenCalled();
  expect(container.querySelector("input")).toBeNull();
});

it("loads cursor pages without appending an unbounded collection", async () => {
  vi.mocked(api.loadStudioVideos).mockResolvedValue({
    items: [choice],
    next_cursor: assetId,
  });
  await mount();
  vi.mocked(api.loadStudioVideos).mockResolvedValue({
    items: [{ ...choice, asset_id: otherId, label: "Next lesson.mp4" }],
    next_cursor: null,
  });
  await click(button("Next videos"));
  expect(api.loadStudioVideos).toHaveBeenLastCalledWith(
    expect.objectContaining({ after: assetId }),
  );
  expect(container.textContent).toContain("Next lesson.mp4");
  expect(container.textContent).not.toContain("Discovery lesson.mp4");
  expect(button("Next videos").disabled).toBe(true);
  expect(button("Previous videos").disabled).toBe(false);
});

it("sends the exact loaded binding as the replacement expectation on superseded versions", async () => {
  vi.mocked(api.loadStudioActivityVideo).mockResolvedValue({
    ...emptyCurrent,
    version_status: "superseded",
    binding: {
      binding_id: bindingId,
      asset_id: otherId,
      version_id: otherId,
      label: "Existing approved lesson",
      state: "approved",
    },
  });
  await mount({ versionStatus: "superseded" });
  expect(container.textContent).toContain("Existing approved lesson");
  await selectAndApprove();
  await click(button("Approve replacement video"));
  expect(api.saveStudioActivityVideo).toHaveBeenCalledWith(
    expect.objectContaining({
      selection: expect.objectContaining({ expected_binding_id: bindingId }),
    }),
  );
});

it("preserves the exact body and key after an ambiguous save and prevents another selection", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new TypeError("network failed"),
  );
  await mount();
  await selectAndApprove(" Human review  ");
  await click(button("Approve lesson video"));
  const first = vi.mocked(api.saveStudioActivityVideo).mock.calls[0][0];
  expect(container.textContent).toContain("could not confirm the result");
  expect(container.textContent).toContain("Approval reference: Human review");
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
  expect(container.querySelector('input:not([type="radio"])')).toBeNull();
  vi.mocked(api.saveStudioActivityVideo).mockResolvedValue({
    ...receipt,
    replayed: true,
  });
  await click(button("Retry same approval"));
  const second = vi.mocked(api.saveStudioActivityVideo).mock.calls[1][0];
  expect(second.selection).toEqual(first.selection);
  expect(second.idempotencyKey).toBe(first.idempotencyKey);
  expect(admin.newIdempotencyKey).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("video request is confirmed");
});

it("keeps an uncertain request when a later retry is denied", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new Error("unknown"),
  );
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValue(problem(403));
  await click(button("Retry same approval"));
  expect(container.textContent).toContain(
    "earlier video request is unresolved",
  );
  expect(container.textContent).not.toContain(choice.label);
  expect(container.textContent).not.toContain("Reviewed lesson source");
  expect(container.querySelector("fieldset")).toBeNull();
  const first = vi.mocked(api.saveStudioActivityVideo).mock.calls[0][0];
  vi.mocked(api.saveStudioActivityVideo).mockResolvedValue({
    ...receipt,
    replayed: true,
  });
  await click(button("Check editing access"));
  await click(button("Retry same approval"));
  expect(vi.mocked(api.saveStudioActivityVideo).mock.calls[2][0]).toMatchObject(
    { selection: first.selection, idempotencyKey: first.idempotencyKey },
  );
});

it.each([401, 403, 404, 410])(
  "hides all private picker details after a fresh pagination denial %s",
  async (status) => {
    vi.mocked(api.loadStudioActivityVideo).mockResolvedValue({
      ...emptyCurrent,
      binding: {
        binding_id: bindingId,
        asset_id: otherId,
        version_id: otherId,
        label: "Private current video",
        state: "approved",
      },
    });
    vi.mocked(api.loadStudioVideos).mockResolvedValue({
      items: [choice],
      next_cursor: assetId,
    });
    await mount();
    await selectAndApprove("Private review reference");
    const staleSave = button("Approve replacement video");
    vi.mocked(api.loadStudioVideos).mockRejectedValue(problem(status));
    await click(button("Next videos"));
    expect(container.textContent).not.toContain("Private current video");
    expect(container.textContent).not.toContain(choice.label);
    expect(container.textContent).not.toContain("Private review reference");
    expect(container.querySelector("fieldset, input")).toBeNull();
    await click(staleSave);
    expect(api.saveStudioActivityVideo).not.toHaveBeenCalled();
    expect(button("Check editing access")).toBeDefined();
    // A failed recovery read must not restore the previously visible metadata.
    vi.mocked(api.loadStudioActivityVideo).mockRejectedValue(problem(status));
    await click(button("Check editing access"));
    expect(container.textContent).not.toContain("Private current video");
    expect(container.querySelector("fieldset, input")).toBeNull();
    vi.mocked(api.loadStudioActivityVideo).mockResolvedValue(emptyCurrent);
    vi.mocked(api.loadStudioVideos).mockResolvedValue({
      items: [choice],
      next_cursor: null,
    });
    await click(button("Check editing access"));
    expect(container.textContent).toContain(choice.label);
    expect(container.querySelector("fieldset")?.disabled).toBe(false);
    expect(container.querySelector('input:not([type="radio"])')).toBeNull();
  },
);

it.each(["current", "library"])(
  "hides a previously loaded panel when refresh receives an access denial from %s",
  async (source) => {
    vi.mocked(api.loadStudioActivityVideo).mockResolvedValue({
      ...emptyCurrent,
      binding: {
        binding_id: bindingId,
        asset_id: assetId,
        version_id: versionId,
        label: "Previously visible current video",
        state: "approved",
      },
    });
    await mount();
    if (source === "current")
      vi.mocked(api.loadStudioActivityVideo).mockRejectedValue(problem(403));
    else vi.mocked(api.loadStudioVideos).mockRejectedValue(problem(403));
    await click(button("Refresh videos"));
    expect(container.textContent).not.toContain(
      "Previously visible current video",
    );
    expect(container.textContent).not.toContain(choice.label);
    expect(container.querySelector("fieldset, input")).toBeNull();
    expect(api.saveStudioActivityVideo).not.toHaveBeenCalled();
  },
);

it("keeps an ambiguous request private during current-recovery denial and retries the same intent after access returns", async () => {
  const onPendingChange = vi.fn();
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new Error("unknown"),
  );
  await mount({ onPendingChange });
  await selectAndApprove("Private pending review");
  await click(button("Approve lesson video"));
  const first = vi.mocked(api.saveStudioActivityVideo).mock.calls[0][0];
  vi.mocked(api.loadStudioActivityVideo).mockRejectedValue(problem(403));
  await click(button("Check current lesson"));
  expect(container.textContent).not.toContain(choice.label);
  expect(container.textContent).not.toContain("Private pending review");
  expect(container.querySelector("fieldset, input")).toBeNull();
  expect(onPendingChange).toHaveBeenLastCalledWith(true);
  expect(
    readStudioVideoRecoveryActivity(props.recoveryContext, programId),
  ).toBe(activityId);
  // A capability-driven remount must not expose retained intent while the
  // first fresh authority request is still unresolved.
  await mount({ canWrite: false, onPendingChange });
  const restored = deferred<api.StudioActivityVideo>();
  vi.mocked(api.loadStudioActivityVideo).mockReturnValue(restored.promise);
  await mount({ canWrite: true, onPendingChange });
  expect(container.textContent).not.toContain(choice.label);
  expect(container.textContent).not.toContain("Private pending review");
  await act(async () => restored.resolve(emptyCurrent));
  expect(container.textContent).toContain("Private pending review");
  await click(button("Retry same approval"));
  expect(vi.mocked(api.saveStudioActivityVideo).mock.calls[1][0]).toMatchObject(
    { selection: first.selection, idempotencyKey: first.idempotencyKey },
  );
  expect(onPendingChange).toHaveBeenLastCalledWith(false);
});

it("returns only the pending activity navigation hint within its active browser scope and program", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new Error("unknown"),
  );
  await mount();
  await selectAndApprove("Private scoped review");
  await click(button("Approve lesson video"));
  expect(
    readStudioVideoRecoveryActivity(props.recoveryContext, programId),
  ).toBe(activityId);
  expect(
    readStudioVideoRecoveryActivity(props.recoveryContext, otherId),
  ).toBeNull();
  expect(
    readStudioVideoRecoveryActivity("other-session", programId),
  ).toBeNull();
  expect(readStudioVideoRecoveryActivity("", programId)).toBeNull();
  vi.stubGlobal("window", undefined);
  try {
    expect(
      readStudioVideoRecoveryActivity(props.recoveryContext, programId),
    ).toBeNull();
  } finally {
    vi.unstubAllGlobals();
  }
  await mount({ recoveryContext: "new-person:tenant:session" });
  expect(
    readStudioVideoRecoveryActivity(props.recoveryContext, programId),
  ).toBeNull();
  expect(
    readStudioVideoRecoveryActivity("new-person:tenant:session", programId),
  ).toBeNull();
  expect(container.textContent).not.toContain("Private scoped review");
  expect(container.textContent).not.toContain("Retry same approval");
});

it("requires a fresh current read after a definitive conflict before allowing another save", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValue(problem(409));
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  expect(container.textContent).toContain("changed before approval");
  expect(button("Approve lesson video").disabled).toBe(true);
  await click(button("Refresh lesson"));
  expect(container.querySelector("fieldset")?.disabled).toBe(false);
  expect(container.querySelector('input:not([type="radio"])')).toBeNull();
});

it("does not treat unchanged current state as proof that an uncertain save failed", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValue(
    new Error("unknown"),
  );
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  await click(button("Check current lesson"));
  expect(container.textContent).toContain(
    "still shows its previous video state",
  );
  expect(button("Retry same approval")).toBeDefined();
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
});

it("shows changed canonical state but keeps the old command until its historical receipt is confirmed", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValue(
    new Error("unknown"),
  );
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  vi.mocked(api.loadStudioActivityVideo).mockResolvedValue({
    ...emptyCurrent,
    binding: {
      binding_id: otherId,
      asset_id: otherId,
      version_id: otherId,
      label: "Current canonical source",
      state: "approved",
    },
  });
  await click(button("Check current lesson"));
  expect(container.textContent).toContain("current lesson video has changed");
  expect(container.textContent).toContain("Current canonical source");
  expect(container.textContent).not.toContain("Video approved for this lesson");
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
  const first = vi.mocked(api.saveStudioActivityVideo).mock.calls[0][0];
  vi.mocked(api.saveStudioActivityVideo).mockResolvedValue({
    ...receipt,
    state: "superseded",
    replayed: true,
  });
  await click(button("Retry same approval"));
  expect(vi.mocked(api.saveStudioActivityVideo).mock.calls[1][0]).toMatchObject(
    { selection: first.selection, idempotencyKey: first.idempotencyKey },
  );
  expect(container.textContent).toContain("that binding has since changed");
  expect(button("Refresh lesson")).toBeDefined();
});

it("retains an ambiguous command across same-context unmount and re-entry", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new Error("unknown"),
  );
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  const first = vi.mocked(api.saveStudioActivityVideo).mock.calls[0][0];
  await act(async () => root.unmount());
  root = createRoot(container);
  await mount();
  await click(button("Retry same approval"));
  expect(vi.mocked(api.saveStudioActivityVideo).mock.calls[1][0]).toMatchObject(
    { selection: first.selection, idempotencyKey: first.idempotencyKey },
  );
});

it("can retry a retained approval when the lesson loads but the optional library refresh fails", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new Error("unknown"),
  );
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  await act(async () => root.unmount());
  root = createRoot(container);
  vi.mocked(api.loadStudioVideos).mockRejectedValue(
    new Error("library offline"),
  );
  await mount();
  await click(button("Retry same approval"));
  expect(api.saveStudioActivityVideo).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain("Video approved for this lesson");
});

it("ignores a previous activity's late read when props change without an external key", async () => {
  const old = deferred<api.StudioActivityVideo>();
  vi.mocked(api.loadStudioActivityVideo).mockImplementation((input) =>
    input.activityId === activityId
      ? old.promise
      : Promise.resolve({ ...emptyCurrent, activity_id: otherId }),
  );
  await mount();
  await mount({ activityId: otherId });
  await act(async () =>
    old.resolve({
      ...emptyCurrent,
      binding: {
        binding_id: bindingId,
        asset_id: assetId,
        version_id: versionId,
        label: "Old private lesson",
        state: "approved",
      },
    }),
  );
  expect(container.textContent).not.toContain("Old private lesson");
  expect(container.textContent).toContain("Discovery lesson.mp4");
});

it("never applies an old save result to a changed tenant/session context", async () => {
  const old = deferred<api.StudioVideoReceipt>();
  vi.mocked(api.saveStudioActivityVideo).mockReturnValue(old.promise);
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  await mount({ recoveryContext: "different-person:tenant:session" });
  await act(async () => old.resolve(receipt));
  expect(container.textContent).not.toContain("Video approved for this lesson");
  expect(container.textContent).toContain(
    "No video approved for this lesson yet",
  );
  expect(container.querySelector("fieldset")?.disabled).toBe(false);
});

it("disables duplicate submissions while the original request is in flight", async () => {
  const pending = deferred<api.StudioVideoReceipt>();
  vi.mocked(api.saveStudioActivityVideo).mockReturnValue(pending.promise);
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  expect(button("Confirming approval…").disabled).toBe(true);
  expect(button("Check current lesson").disabled).toBe(true);
  expect(api.saveStudioActivityVideo).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve(receipt));
});

it("signals unresolved saves to the editor and protects browser unload until receipt confirmation", async () => {
  const onPendingChange = vi.fn();
  vi.mocked(api.saveStudioActivityVideo).mockRejectedValueOnce(
    new Error("unknown"),
  );
  await mount({ onPendingChange });
  expect(onPendingChange).toHaveBeenLastCalledWith(false);
  await selectAndApprove();
  await click(button("Approve lesson video"));
  expect(onPendingChange).toHaveBeenLastCalledWith(true);
  const blockedUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(blockedUnload);
  expect(blockedUnload.defaultPrevented).toBe(true);
  await click(button("Retry same approval"));
  expect(onPendingChange).toHaveBeenLastCalledWith(false);
  const clearUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(clearUnload);
  expect(clearUnload.defaultPrevented).toBe(false);
});

it("does not present a superseded replay receipt as the current approved source", async () => {
  vi.mocked(api.saveStudioActivityVideo).mockResolvedValue({
    ...receipt,
    state: "superseded",
    replayed: true,
  });
  await mount();
  await selectAndApprove();
  await click(button("Approve lesson video"));
  expect(container.textContent).toContain("that binding has since changed");
  expect(container.textContent).not.toContain("Video approved for this lesson");
  expect(button("Refresh lesson")).toBeDefined();
});
