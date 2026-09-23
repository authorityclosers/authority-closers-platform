// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  PendingAnalysisProvider,
  usePendingAnalysis,
} from "./pending-analysis";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const observed: { current: ReturnType<typeof usePendingAnalysis> } = {
  current: null,
};
const revoked = vi.fn();

function Probe() {
  const pending = usePendingAnalysis();
  useEffect(() => {
    observed.current = pending;
  }, [pending]);
  return <p>{pending?.selection?.file.name ?? "No selected file"}</p>;
}

async function render(showProbe: boolean) {
  await act(async () =>
    root.render(
      <PendingAnalysisProvider>
        {showProbe && <Probe />}
      </PendingAnalysisProvider>,
    ),
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "intent-1") });
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:synthetic-file"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: revoked,
  });
  revoked.mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("keeps the exact File and intent through child unmount and remount", async () => {
  const file = new File([new Uint8Array([1, 2, 3])], "synthetic.wav", {
    type: "audio/wav",
  });
  await render(true);
  await act(async () => observed.current?.selectFile(file));
  const intent = observed.current?.selection?.intentId;
  expect(observed.current?.selection?.file).toBe(file);
  await render(false);
  await render(true);
  expect(observed.current?.selection?.file).toBe(file);
  expect(observed.current?.selection?.intentId).toBe(intent);
  expect(revoked).not.toHaveBeenCalled();
});

it("stages distinct File objects in order and preserves the active selection through unrelated edits", async () => {
  let id = 0;
  vi.stubGlobal("crypto", { randomUUID: () => `intent-${++id}` });
  let url = 0;
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => `blob:staged-${++url}`),
  });
  const first = new File(["one"], "same-name.wav");
  const second = new File(["two"], "same-name.wav");
  const third = new File(["three"], "third.wav");
  await render(true);
  await act(async () => observed.current?.addFiles([first, second, first]));
  expect(observed.current?.stagedFiles).toEqual([first, second]);
  expect(observed.current?.stagedFiles[0]).toBe(first);
  expect(observed.current?.stagedFiles[1]).toBe(second);
  const original = observed.current?.selection;
  expect(original?.file).toBe(first);
  expect(original?.intentId).toBe("intent-1");
  await act(async () => observed.current?.selectFile(first));
  expect(observed.current?.selection).toBe(original);
  expect(revoked).not.toHaveBeenCalled();
  await act(async () => observed.current?.addFiles([third]));
  await act(async () => observed.current?.removeFile(second));
  expect(observed.current?.stagedFiles).toEqual([first, third]);
  expect(observed.current?.selection).toBe(original);
  expect(revoked).not.toHaveBeenCalled();

  await act(async () => observed.current?.selectFile(third));
  expect(observed.current?.selection?.file).toBe(third);
  expect(observed.current?.selection?.intentId).toBe("intent-2");
  expect(revoked).toHaveBeenCalledExactlyOnceWith("blob:staged-1");
  await act(async () => observed.current?.removeFile(third));
  expect(observed.current?.selection?.file).toBe(first);
  expect(observed.current?.selection?.intentId).toBe("intent-3");
  expect(revoked).toHaveBeenCalledTimes(2);
  await act(async () => observed.current?.clearFiles());
  expect(observed.current?.stagedFiles).toEqual([]);
  expect(observed.current?.selection).toBeNull();
  expect(revoked).toHaveBeenCalledTimes(3);
  await act(async () => observed.current?.addFiles([first]));
  await act(async () => observed.current?.clearFile());
  expect(observed.current?.stagedFiles).toEqual([]);
});

it("binds once to the confirmed account and clears on account or workspace change", async () => {
  await render(true);
  const file = new File(["x"], "synthetic.wav");
  const queued = new File(["y"], "queued.wav");
  await act(async () => observed.current?.addFiles([file, queued]));
  await act(async () =>
    observed.current?.bindContext({
      personId: "person-a",
      sessionId: "session-a",
      tenantId: "tenant-a",
    }),
  );
  expect(observed.current?.selection?.file.name).toBe("synthetic.wav");
  await act(async () =>
    observed.current?.bindContext({
      personId: "person-a",
      sessionId: "session-a",
      tenantId: "tenant-a",
    }),
  );
  expect(revoked).not.toHaveBeenCalled();
  await act(async () =>
    observed.current?.bindContext({
      personId: "person-b",
      sessionId: "session-b",
      tenantId: "tenant-b",
    }),
  );
  expect(observed.current?.selection).toBeNull();
  expect(observed.current?.stagedFiles).toEqual([]);
  expect(observed.current?.accountChanged).toBe(true);
  expect(revoked).toHaveBeenCalledExactlyOnceWith("blob:synthetic-file");
});

it("keeps guest files for the first authenticated account and clears on a different chooser identity", async () => {
  const first = new File(["one"], "first.wav");
  const second = new File(["two"], "second.wav");
  await render(true);
  await act(async () => observed.current?.addFiles([first, second]));
  const selection = observed.current?.selection;
  await act(async () =>
    observed.current?.observeAccount({
      personId: "person-a",
      sessionId: "session-a",
    }),
  );
  expect(observed.current?.stagedFiles).toEqual([first, second]);
  expect(observed.current?.selection).toBe(selection);
  await act(async () =>
    observed.current?.observeAccount({
      personId: "person-b",
      sessionId: "session-b",
    }),
  );
  expect(observed.current?.stagedFiles).toEqual([]);
  expect(observed.current?.selection).toBeNull();
  expect(observed.current?.accountChanged).toBe(true);
  expect(revoked).toHaveBeenCalledExactlyOnceWith("blob:synthetic-file");
});
