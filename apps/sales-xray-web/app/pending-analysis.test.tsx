// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { PendingAnalysisProvider, usePendingAnalysis } from "./pending-analysis";

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
      <PendingAnalysisProvider>{showProbe && <Probe />}</PendingAnalysisProvider>,
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

it("binds once to the confirmed account and clears on account or workspace change", async () => {
  await render(true);
  await act(async () => observed.current?.selectFile(new File(["x"], "synthetic.wav")));
  await act(async () =>
    observed.current?.bindContext({ personId: "person-a", sessionId: "session-a", tenantId: "tenant-a" }),
  );
  expect(observed.current?.selection?.file.name).toBe("synthetic.wav");
  await act(async () =>
    observed.current?.bindContext({ personId: "person-a", sessionId: "session-a", tenantId: "tenant-a" }),
  );
  expect(revoked).not.toHaveBeenCalled();
  await act(async () =>
    observed.current?.bindContext({ personId: "person-b", sessionId: "session-b", tenantId: "tenant-b" }),
  );
  expect(observed.current?.selection).toBeNull();
  expect(observed.current?.accountChanged).toBe(true);
  expect(revoked).toHaveBeenCalledExactlyOnceWith("blob:synthetic-file");
});
