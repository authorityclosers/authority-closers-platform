import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("./acquisition-client", async (original) => ({
  ...(await original<typeof import("./acquisition-client")>()),
  acquisition: vi.fn(),
}));
import { acquisition, AcquisitionError } from "./acquisition-client";
import { useCallInsights } from "./calls-insights";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const a = "11111111-1111-4111-8111-111111111111";
const b = "22222222-2222-4222-8222-222222222222";
let root: Root;
let host: HTMLDivElement;
let latest: ReturnType<typeof useCallInsights>;
let reads: {
  path: string;
  signal: AbortSignal;
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
}[];

function Harness({
  ids,
  enabled = true,
}: {
  ids: string[];
  enabled?: boolean;
}) {
  latest = useCallInsights(ids, enabled);
  return null;
}
const render = (ids: string[], enabled = true, key = "workspace") =>
  act(async () =>
    root.render(<Harness key={key} ids={ids} enabled={enabled} />),
  );
const flush = () =>
  act(async () => {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  });
const resolve = (batch: typeof reads, verdict: string) =>
  act(async () => {
    for (const read of batch)
      read.resolve(read.path.endsWith("/report") ? { verdict } : null);
  });

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  reads = [];
  vi.mocked(acquisition).mockImplementation(
    (path, init) =>
      new Promise((resolve, reject) =>
        reads.push({
          path,
          signal: init!.signal as AbortSignal,
          resolve,
          reject,
        }),
      ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.mocked(acquisition).mockReset();
});

it.each([{ ids: [a] }, { ids: [b, a] }])(
  "reschedules retained calls after filtering or sorting pending reads (%j)",
  async ({ ids }) => {
    await render([a, b]);
    const stale = [...reads];
    await render(ids);
    expect(stale.every((read) => read.signal.aborted)).toBe(true);
    const replacement = reads.slice(4);
    expect(replacement).toHaveLength(ids.length * 2);
    await resolve(replacement, "Current report");
    await resolve(stale, "Stale report");
    await flush();
    for (const id of ids)
      expect(latest.insightOf(id)?.assessment).toBe("Current report");
  },
);

it("limits loading to three calls and drains the queue", async () => {
  const ids = [
    a,
    b,
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
  ];
  await render(ids);
  expect(reads).toHaveLength(6);
  await resolve(reads.slice(0, 2), "First report");
  await flush();
  expect(reads).toHaveLength(8);
  await resolve(reads.slice(2), "Remaining reports");
  await flush();
  for (const id of ids) expect(latest.statusOf(id)).toBe("ready");
});

it("exposes failed reads and retries after service recovery", async () => {
  await render([a]);
  await act(async () =>
    reads.forEach((read) => read.reject(new Error("offline"))),
  );
  await flush();
  expect(latest.statusOf(a)).toBe("error");
  expect(latest.insightOf(a)).toBeNull();
  expect(reads).toHaveLength(2); // No uncontrolled retry loop.
  await act(async () => latest.retry());
  expect(latest.statusOf(a)).toBe("loading");
  expect(reads).toHaveLength(4);
  await resolve(reads.slice(2), "Recovered report");
  await flush();
  expect(latest.statusOf(a)).toBe("ready");
  expect(latest.insightOf(a)?.assessment).toBe("Recovered report");
});

it("retains partial report content but allows the failed measurement read to recover", async () => {
  await render([a]);
  await act(async () => {
    reads[0].reject(new Error("offline"));
    reads[1].resolve({ verdict: "Available report" });
  });
  await flush();
  expect(latest.statusOf(a)).toBe("error");
  expect(latest.insightOf(a)?.assessment).toBe("Available report");
  await render([]);
  await render([a]);
  expect(reads).toHaveLength(4);
  await resolve(reads.slice(2), "Recovered");
  await flush();
  expect(latest.statusOf(a)).toBe("ready");
});

it("distinguishes successful absence from a read failure", async () => {
  await render([a]);
  await act(async () =>
    reads.forEach((read) => read.reject(new AcquisitionError(404))),
  );
  await flush();
  expect(latest.statusOf(a)).toBe("unavailable");
  expect(latest.insightOf(a)).toBeNull();
});

it("does not reuse successful reads across workspace/session remounts", async () => {
  await render([a]);
  await resolve([...reads], "First workspace");
  await flush();
  await render([a], true, "other-workspace");
  expect(latest.insightOf(a)).toBeNull();
  expect(reads).toHaveLength(4);
  await resolve(reads.slice(2), "Other workspace");
  await flush();
  expect(latest.insightOf(a)?.assessment).toBe("Other workspace");
});
