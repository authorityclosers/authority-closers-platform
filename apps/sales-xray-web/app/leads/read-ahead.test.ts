import { afterEach, expect, it, vi } from "vitest";

import {
  addNote,
  likelyNext,
  readLead,
  readLeadAhead,
  readNext,
  readNextAhead,
  setAheadScope,
  type LeadRow,
} from "./leads-client";

const detail = (id: string) => ({
  lead: { lead_id: id, name: "priya shah" },
  events: [],
});

function network() {
  const fetchMock = vi.fn<typeof fetch>(
    async (input) =>
      new Response(
        JSON.stringify(
          String(input).endsWith("/notes")
            ? detail("a")
            : detail(String(input).split("/").pop() ?? ""),
        ),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  setAheadScope(null);
  vi.unstubAllGlobals();
});

it("opens a lead read ahead without asking again, and only once", async () => {
  const fetchMock = network();
  setAheadScope("me");
  readLeadAhead("a");
  readLeadAhead("a");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect((await readLead("a")).lead.lead_id).toBe("a");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  // Taken once: the next opening reads again.
  await readLead("a");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("drops what was read ahead after a write, or for another identity", async () => {
  const fetchMock = network();
  setAheadScope("me");
  readLeadAhead("a");
  await addNote("a", "Asked for a quote");
  await readLead("a");
  expect(fetchMock).toHaveBeenCalledTimes(3);

  readLeadAhead("b");
  setAheadScope("someone else");
  await readLead("b");
  expect(fetchMock).toHaveBeenCalledTimes(5);

  // Without an identity nothing is read ahead.
  setAheadScope(null);
  readLeadAhead("c");
  expect(fetchMock).toHaveBeenCalledTimes(5);
});

it("starts calling on the first lead read ahead, for the same pipeline only", async () => {
  const fetchMock = network();
  setAheadScope("me");
  readNextAhead("rentals");
  expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
    "/v1/lead-desk/next?pipeline=rentals",
  );
  await readNext(undefined, undefined, "rentals");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  // Another pipeline (or all of them) reads for itself.
  readNextAhead("rentals");
  await readNext();
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("a cancelled opening never takes the answer read ahead", async () => {
  network();
  setAheadScope("me");
  readLeadAhead("a");
  const controller = new AbortController();
  const read = readLead("a", controller.signal);
  controller.abort();
  await expect(read).rejects.toMatchObject({ name: "AbortError" });
});

it("reads ahead call backs, then overdue, then due now, never later today", () => {
  const row = (id: string, overrides: Partial<LeadRow> = {}) =>
    ({ lead_id: id, why_kind: "due", overdue: false, ...overrides }) as LeadRow;
  expect(
    likelyNext({
      call_back: [row("cb")],
      queue: [
        row("later", { why_kind: "later" }),
        row("now"),
        row("cb"),
        row("late", { overdue: true }),
        row("now2"),
      ],
    }),
  ).toEqual(["cb", "late", "now"]);
  expect(likelyNext({ queue: [row("later", { why_kind: "later" })] })).toEqual(
    [],
  );
});
