// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { dispose, LeadsError } from "../leads/leads-client";
import {
  confirmLogOutWithUnsent,
  replayWrites,
  resetWrites,
  sendWrite,
  loadWriteMirror,
  retryStorage,
  setWriteMirror,
  writesMirrored,
  type QueuedWrite,
  type WriteMirror,
  setWriteIdentity,
  unsentWrites,
  writesNow,
  writeLabel,
} from "./write-queue";

const LEAD = "11111111-1111-4111-8111-111111111111";
const DISPOSE = `/v1/lead-desk/leads/${LEAD}/dispose`;
const ME = "p-asha:t-homes";

const ok = (body: unknown = {}) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
const status = (code: number) =>
  new Response(JSON.stringify({ detail: "No." }), {
    status: code,
    headers: { "content-type": "application/json" },
  });
const post = (command: string, remark = "Wants a site visit") => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    command_id: command,
    expected_revision: 3,
    connected: true,
    remark,
  }),
});
const sentBodies = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(
    ([, init]) =>
      JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>,
  );

beforeEach(() => {
  resetWrites();
  setWriteIdentity(ME);
});
afterEach(() => {
  resetWrites();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("keeps a call result through a lost connection and sends it again with its command id", async () => {
  const fetchMock = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(ok());
  vi.stubGlobal("fetch", fetchMock);
  expect(await sendWrite(DISPOSE, post("c-1"))).toEqual({
    kind: "kept",
    onDevice: true,
  });
  expect(unsentWrites()).toHaveLength(1);
  expect(unsentWrites()[0]).toMatchObject({
    label: "A call result",
    lead: LEAD,
  });
  // Kept on the device itself, not only in memory.
  expect(window.localStorage.getItem("sx-writes:v1")).toContain("c-1");

  await replayWrites({ force: true });
  expect(unsentWrites()).toEqual([]);
  expect(sentBodies(fetchMock).map((body) => body.command_id)).toEqual([
    "c-1",
    "c-1",
  ]);
});

it("keeps it on a busy server or a lapsed sign-in, not on a refusal", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(status(503))
      .mockResolvedValueOnce(status(401))
      .mockResolvedValueOnce(status(422)),
  );
  expect((await sendWrite(DISPOSE, post("c-1"))).kind).toBe("kept");
  expect(
    (await sendWrite(`/v1/lead-desk/leads/${LEAD}/notes`, post("c-2"))).kind,
  ).toBe("kept");
  expect(
    (await sendWrite(`/v1/lead-desk/leads/${LEAD}/follow-up`, post("c-3")))
      .kind,
  ).toBe("refused");
  expect(unsentWrites().map((item) => item.id)).toEqual(["c-1", "c-2"]);
});

it("doesn't make a second change when the same one is saved again while it waits", async () => {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
  vi.stubGlobal("fetch", fetchMock);
  await sendWrite(DISPOSE, post("c-1"));
  await sendWrite(DISPOSE, post("c-2"));
  expect(unsentWrites().map((item) => item.id)).toEqual(["c-1"]);
  expect(sentBodies(fetchMock).map((body) => body.command_id)).toEqual([
    "c-1",
    "c-1",
  ]);
  // A different change is its own.
  await sendWrite(DISPOSE, post("c-3", "Call back Monday"));
  expect(unsentWrites().map((item) => item.id)).toEqual(["c-1", "c-3"]);
});

it("holds a change the server refuses when sent again, never forcing it", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(status(409)),
  );
  await sendWrite(DISPOSE, post("c-1"));
  await replayWrites({ force: true });
  expect(unsentWrites()).toEqual([
    expect.objectContaining({ id: "c-1", state: "check", status: 409 }),
  ]);
});

it("sends again oldest first, and stops at the first that doesn't arrive", async () => {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetchMock);
  await sendWrite(DISPOSE, post("c-1"));
  await sendWrite(`/v1/lead-desk/leads/${LEAD}/notes`, post("c-2"));
  fetchMock.mockReset();
  fetchMock
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValue(ok());
  await replayWrites({ force: true });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(unsentWrites()).toHaveLength(2);
  await replayWrites({ force: true });
  expect(
    sentBodies(fetchMock)
      .slice(1)
      .map((body) => body.command_id),
  ).toEqual(["c-1", "c-2"]);
  expect(unsentWrites()).toEqual([]);
});

it("waits before sending again unless asked to send now", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetchMock);
  await sendWrite(DISPOSE, post("c-1"));
  fetchMock.mockReset().mockResolvedValue(ok());
  await replayWrites();
  expect(fetchMock).not.toHaveBeenCalled();
  vi.advanceTimersByTime(5_000);
  await replayWrites();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("sends a change only for the person and workspace that made it", async () => {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetchMock);
  await sendWrite(DISPOSE, post("c-1"));
  setWriteIdentity("p-other:t-homes");
  expect(unsentWrites()).toEqual([]);
  fetchMock.mockReset().mockResolvedValue(ok());
  await replayWrites({ force: true });
  expect(fetchMock).not.toHaveBeenCalled();
  setWriteIdentity(ME);
  await replayWrites({ force: true });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("lets settings and other changes fail as before, without keeping them", async () => {
  expect(writeLabel("PUT", "/v1/lead-desk/settings")).toBeNull();
  expect(writeLabel("POST", "/v1/lead-desk/leads/bulk")).toBeNull();
  expect(writeLabel("POST", "/v1/lead-desk/leads")).toBe("A new lead");
  expect(writeLabel("PATCH", `/v1/lead-desk/leads/${LEAD}`)).toBe(
    "A lead's details",
  );
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  await expect(
    sendWrite("/v1/lead-desk/settings", { ...post("c-1"), method: "PUT" }),
  ).rejects.toThrow();
  expect(unsentWrites()).toEqual([]);
  // Signed out: nothing is kept for nobody.
  setWriteIdentity(null);
  await expect(sendWrite(DISPOSE, post("c-2"))).rejects.toThrow();
  setWriteIdentity(ME);
  expect(unsentWrites()).toEqual([]);
});

it("tells the after-call card its result is kept, not lost", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  const failure = await dispose(
    { lead_id: LEAD, revision: 3 },
    { connected: true, remark: "Site visit" },
  ).catch((error: unknown) => error);
  expect(failure).toBeInstanceOf(LeadsError);
  expect((failure as LeadsError).kept).toBe(true);
  expect((failure as LeadsError).message).toContain("kept on this phone");
  expect(unsentWrites()).toEqual([
    expect.objectContaining({ label: "A call result" }),
  ]);
});

it("asks before logging out with changes waiting, and sends them when staying", async () => {
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetchMock);
  expect(confirmLogOutWithUnsent()).toBe(true);
  await sendWrite(DISPOSE, post("c-1"));
  const confirm = vi.fn<(message?: string) => boolean>(() => false);
  vi.stubGlobal("confirm", confirm);
  fetchMock.mockReset().mockResolvedValue(ok());
  expect(confirmLogOutWithUnsent()).toBe(false);
  expect(confirm.mock.calls[0][0]).toContain(
    "1 change isn't on Sales X-Ray yet (a call result)",
  );
  await vi.waitFor(() => expect(unsentWrites()).toEqual([]));
  confirm.mockReturnValue(true);
  fetchMock.mockRejectedValue(new TypeError("offline"));
  await sendWrite(DISPOSE, post("c-2"));
  expect(confirmLogOutWithUnsent()).toBe(true);
  // Logging out keeps it for the next sign-in here.
  expect(unsentWrites()).toHaveLength(1);
});

it("holds a change the phone can't store, says so, and stores it when it can", async () => {
  const full = vi
    .spyOn(window.localStorage, "setItem")
    .mockImplementation(() => {
      throw new DOMException(
        "The quota has been exceeded.",
        "QuotaExceededError",
      );
    });
  const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
  vi.stubGlobal("fetch", fetchMock);
  expect(await sendWrite(DISPOSE, post("c-1"))).toEqual({
    kind: "kept",
    onDevice: false,
  });
  // Not dropped: held while the app runs, and the state says the phone is full.
  expect(unsentWrites().map((item) => item.id)).toEqual(["c-1"]);
  expect(writesNow()).toMatchObject({ waiting: 1, storageFull: true });
  full.mockRestore();
  fetchMock.mockRejectedValue(new TypeError("still offline"));
  await retryStorage();
  expect(window.localStorage.getItem("sx-writes:v1")).toContain("c-1");
  expect(writesNow().storageFull).toBe(false);
});

describe("the IndexedDB copy", () => {
  let disk: QueuedWrite[] | null;
  let previous: WriteMirror;
  const memoryDisk: WriteMirror = {
    read: async () => disk,
    write: async (list) => {
      disk = list;
    },
  };
  beforeEach(() => {
    disk = null;
    previous = setWriteMirror(memoryDisk);
  });
  afterEach(() => {
    setWriteMirror(previous);
  });

  it("keeps a change saved just before the app was swiped away, and sends it once", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchMock);
    await sendWrite(DISPOSE, post("c-1"));
    await writesMirrored();
    // Swiped away before localStorage reached the disk: it starts empty.
    resetWrites();
    setWriteIdentity(ME);
    expect(unsentWrites()).toEqual([]);
    await loadWriteMirror();
    expect(unsentWrites().map((item) => item.id)).toEqual(["c-1"]);
    fetchMock.mockReset().mockResolvedValue(ok());
    await replayWrites({ force: true });
    expect(sentBodies(fetchMock).map((body) => body.command_id)).toEqual([
      "c-1",
    ]);
    expect(unsentWrites()).toEqual([]);
  });

  it("keeps a change in both copies as one change", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await sendWrite(DISPOSE, post("c-1"));
    await writesMirrored();
    await loadWriteMirror();
    expect(unsentWrites().map((item) => item.id)).toEqual(["c-1"]);
  });

  it("carries on with localStorage alone when IndexedDB fails", async () => {
    setWriteMirror({
      read: async () => {
        throw new Error("IndexedDB is blocked");
      },
      write: async () => {
        throw new Error("IndexedDB is blocked");
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    expect(await sendWrite(DISPOSE, post("c-1"))).toEqual({
      kind: "kept",
      onDevice: true,
    });
    await writesMirrored();
    await expect(loadWriteMirror()).resolves.toBeUndefined();
    expect(unsentWrites().map((item) => item.id)).toEqual(["c-1"]);
  });
});
