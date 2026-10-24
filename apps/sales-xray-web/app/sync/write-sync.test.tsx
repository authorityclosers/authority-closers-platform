// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notices: [] as Array<Record<string, unknown>>,
  dismissed: [] as string[],
}));
vi.mock("../notice-center", () => ({
  notify: (notice: Record<string, unknown>) => mocks.notices.push(notice),
  dismissNotice: (id: string) => mocks.dismissed.push(id),
}));
vi.mock("../workspace-access", () => ({
  useWorkspaceAccess: () => ({
    status: "ready",
    authenticated: true,
    context: { personId: "p-asha", sessionId: "s1", tenantId: "t-homes" },
  }),
}));

const { resetWrites, sendWrite, setWriteIdentity, unsentWrites } = await import(
  "./write-queue"
);
const { WriteSync, WAITING_NOTICE } = await import("./write-sync");

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const LEAD = "11111111-1111-4111-8111-111111111111";
const DISPOSE = `/v1/lead-desk/leads/${LEAD}/dispose`;
const body = (command: string) => ({
  method: "POST",
  body: JSON.stringify({
    command_id: command,
    connected: true,
    remark: "Wants a site visit",
  }),
});
const answer = (code: number) => new Response("{}", { status: code });

let root: Root;
let host: HTMLDivElement;
const settle = async () => {
  for (let i = 0; i < 8; i++) await act(async () => await Promise.resolve());
};
const titles = () => mocks.notices.map((notice) => notice.title);

beforeEach(() => {
  resetWrites();
  mocks.notices.length = 0;
  mocks.dismissed.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetWrites();
  vi.unstubAllGlobals();
});

it("shows what waits, sends it at the start, then says all changes are saved", async () => {
  setWriteIdentity("p-asha:t-homes");
  const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("offline"));
  vi.stubGlobal("fetch", fetchMock);
  await sendWrite(DISPOSE, body("c-1"));
  setWriteIdentity(null);
  // The next start: still not answering, then it is.
  fetchMock
    .mockReset()
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValue(answer(200));
  await act(async () => root.render(<WriteSync />));
  await settle();
  expect(titles()).toContain("1 change not sent yet");
  const card = mocks.notices.find((notice) => notice.id === WAITING_NOTICE) as {
    action: { label: string; run: () => void };
    message: string;
  };
  expect(card.message).toContain("Kept on this phone");
  await act(async () => card.action.run());
  await settle();
  expect(unsentWrites()).toEqual([]);
  expect(mocks.dismissed).toContain(WAITING_NOTICE);
  expect(titles()).toContain("All changes saved");
});

it("shows a change the server refused, with the words typed and the way back to the lead", async () => {
  setWriteIdentity("p-asha:t-homes");
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValue(answer(409)),
  );
  await sendWrite(DISPOSE, body("c-1"));
  await act(async () => root.render(<WriteSync />));
  await settle();
  // Sent again at the start; refused: kept for a look, not forced.
  const refused = mocks.notices.find(
    (notice) => notice.id === "writes-check-c-1",
  ) as {
    title: string;
    message: string;
    action: { label: string };
    tone: string;
  };
  expect(refused.title).toBe("A call result wasn't saved");
  expect(refused.tone).toBe("error");
  expect(refused.message).toContain(
    "The lead changed before this could be sent.",
  );
  expect(refused.message).toContain("Wants a site visit");
  expect(refused.action.label).toBe("Open lead");
});
