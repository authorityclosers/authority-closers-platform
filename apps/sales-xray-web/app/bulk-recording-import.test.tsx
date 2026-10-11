import { webcrypto } from "node:crypto";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BulkRecordingImport } from "./bulk-recording-import";
import type { ImportBatch } from "./bulk-import-runner";
import type { ImportSelection } from "./bulk-import-files";

const id = "11111111-1111-4111-8111-111111111111";
const member = "22222222-2222-4222-8222-222222222222";
const tenant = "33333333-3333-4333-8333-333333333333";
const selection: ImportSelection = {
  manifest: {
    files: [
      {
        relative_path: "Rep/one.wav",
        source_sha256: "a".repeat(64),
        source_bytes: 3,
      },
    ],
  },
  files: new Map(),
  skipped: 0,
};
const preview = {
  tenantId: tenant,
  manifestSha: "b".repeat(64),
  folders: [
    {
      folder: "Rep",
      proposedPersonId: member,
      count: 1,
      bytes: 3,
      state: "suggested",
    },
  ],
  members: [{ personId: member, name: "स्वामिनी" }],
};
const fixture: ImportBatch = {
  id,
  tenantId: tenant,
  manifestSha: "b".repeat(64),
  policySha: "c".repeat(64),
  expiresAt: "2030-01-01T00:00:00Z",
  terminalState: "done",
  items: [
    {
      index: 0,
      sha: "a".repeat(64),
      bytes: 3,
      personId: member,
      uploadId: id,
      submissionId: id,
      state: "done",
      stage: "C6",
      minuteState: "delivered",
      retryAvailable: false,
      runState: "done",
    },
  ],
};
const policy = {
  policy_sha256: "c".repeat(64),
  title: "Upload terms",
  description: "Approved fixture terms",
  maximum_file_bytes: 32 * 1024 ** 2,
  maximum_call_seconds: 3600,
  retention_days: 30,
};
const operations = vi.hoisted(() => ({
  confirm: vi.fn(),
  refresh: vi.fn(),
  advance: vi.fn(),
  retry: vi.fn(),
}));
vi.mock("./bulk-import-preview", () => ({
  BulkImportPreview: ({
    onPreview,
  }: {
    onPreview: (s: ImportSelection, p: unknown) => void;
  }) => (
    <button onClick={() => onPreview(selection, preview)}>
      Choose fixture folder
    </button>
  ),
}));
vi.mock("./bulk-import-runner", () => ({
  confirmImport: operations.confirm,
  refreshImport: operations.refresh,
  advanceImport: operations.advance,
  retryImportItem: operations.retry,
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  vi.clearAllMocks();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  operations.confirm.mockResolvedValue({ data: fixture, error: null });
  operations.refresh.mockResolvedValue({ data: fixture, error: null });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const button = (text: string) =>
  Array.from(host.querySelectorAll("button")).find(
    (item) => item.textContent === text,
  )!;

it("requires the exact rights confirmation before creating a batch", async () => {
  await act(async () => root.render(<BulkRecordingImport policy={policy} />));
  await act(async () => button("Choose fixture folder").click());
  expect(host.textContent).toContain("स्वामिनी");
  expect(button("Confirm batch").disabled).toBe(true);
  expect(operations.confirm).not.toHaveBeenCalled();
  await act(async () =>
    (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click(),
  );
  expect(button("Confirm batch").disabled).toBe(false);
  await act(async () => button("Confirm batch").click());
  expect(operations.confirm).toHaveBeenCalledOnce();
  expect(operations.confirm.mock.calls[0][0]).toMatchObject({
    folders: { Rep: member },
    policySha: policy.policy_sha256,
  });
  expect(host.textContent).toContain("Done");
  expect(operations.advance).not.toHaveBeenCalled();
});

it("restored failed calls expose truthful retry and never resume processing on load", async () => {
  const failed: ImportBatch = {
    ...fixture,
    terminalState: "failed",
    items: [
      {
        ...fixture.items[0]!,
        state: "failed",
        runState: "failed",
        retryAvailable: true,
      },
    ],
  };
  await act(async () =>
    root.render(<BulkRecordingImport policy={policy} initialBatch={failed} />),
  );
  expect(host.textContent).toContain("Failed");
  expect(button("Try again").disabled).toBe(true);
  expect(operations.retry).not.toHaveBeenCalled();
  expect(operations.advance).not.toHaveBeenCalled();
  operations.retry.mockResolvedValue({
    data: null,
    error: "Another batch recording is still processing.",
  });
  await act(async () =>
    (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click(),
  );
  await act(async () => button("Try again").click());
  expect(operations.retry).toHaveBeenCalledOnce();
  expect(host.querySelector('[role="status"]')?.textContent).toContain(
    "still processing",
  );
});

it("folder re-selection releases a cancelled retry and ignores its late result", async () => {
  const failed: ImportBatch = {
    ...fixture,
    terminalState: "failed",
    items: [
      {
        ...fixture.items[0]!,
        state: "failed",
        runState: "failed",
        retryAvailable: true,
      },
    ],
  };
  type Result = { data: null; error: string | null };
  let finishFirst!: (result: Result) => void;
  let finishSecond!: (result: Result) => void;
  operations.retry
    .mockReturnValueOnce(
      new Promise<Result>((resolve) => (finishFirst = resolve)),
    )
    .mockReturnValueOnce(
      new Promise<Result>((resolve) => (finishSecond = resolve)),
    );
  await act(async () =>
    root.render(<BulkRecordingImport policy={policy} initialBatch={failed} />),
  );
  const consent = () =>
    (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click();
  await act(async () => consent());
  await act(async () => button("Try again").click());
  expect(button("Try again").disabled).toBe(true);
  const first = operations.retry.mock.calls[0]!;
  await act(async () => button("Choose fixture folder").click());
  expect((first[3] as AbortSignal).aborted).toBe(true);
  await act(async () => consent());
  expect(button("Try again").disabled).toBe(false);
  await act(async () => button("Try again").click());
  expect(operations.retry).toHaveBeenCalledTimes(2);
  expect(operations.retry.mock.calls[1]![2]).toBe(first[2]);
  await act(async () => finishFirst({ data: null, error: "Stale refusal" }));
  expect(button("Try again").disabled).toBe(true);
  expect(host.textContent).not.toContain("Stale refusal");
  await act(async () => finishSecond({ data: null, error: "Current refusal" }));
  expect(button("Try again").disabled).toBe(false);
  expect(host.querySelector('[role="status"]')?.textContent).toContain(
    "Current refusal",
  );
});

it("reuses the retry command when its canonical read-back is unavailable", async () => {
  const failed: ImportBatch = {
    ...fixture,
    terminalState: "failed",
    items: [
      {
        ...fixture.items[0]!,
        state: "failed",
        runState: "failed",
        retryAvailable: true,
      },
    ],
  };
  operations.retry.mockResolvedValue({ data: null, error: null });
  operations.refresh
    .mockResolvedValueOnce({ data: null, error: "Progress is unavailable" })
    .mockResolvedValueOnce({ data: fixture, error: null });
  await act(async () =>
    root.render(<BulkRecordingImport policy={policy} initialBatch={failed} />),
  );
  await act(async () =>
    (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click(),
  );
  await act(async () => button("Try again").click());
  expect(host.textContent).toContain("Progress is unavailable");
  expect(button("Try again").disabled).toBe(false);
  await act(async () => button("Try again").click());
  expect(operations.retry).toHaveBeenCalledTimes(2);
  expect(operations.retry.mock.calls[1]![2]).toBe(
    operations.retry.mock.calls[0]![2],
  );
  expect(host.textContent).toContain("Done");
});
