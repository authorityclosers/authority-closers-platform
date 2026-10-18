import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  CallsReport,
  callsCsv,
  dayValue,
  idleLine,
  splitIdle,
} from "./calls-report";
import type { CallReport } from "./leads-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const REPORT: CallReport = {
  start: "2026-10-17",
  end: "2026-10-18",
  sellers: [
    {
      person_id: "p1",
      name: 'Asha "AK" Kulkarni, Pune',
      days: [
        {
          day: "2026-10-17",
          calls: 12,
          connected: 7,
          talk_seconds: 1830,
          missed: 1,
        },
        {
          day: "2026-10-18",
          calls: 0,
          connected: 0,
          talk_seconds: 0,
          missed: 0,
        },
      ],
      calls: 12,
      connected: 7,
      talk_seconds: 1830,
      missed: 1,
    },
  ],
};

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("makes a CSV with one row per seller per day", () => {
  expect(callsCsv(REPORT)).toBe(
    "Seller,Date,Calls,Connected,Talk minutes,Missed calls\n" +
      '"Asha ""AK"" Kulkarni, Pune",2026-10-17,12,7,31,1\n' +
      '"Asha ""AK"" Kulkarni, Pune",2026-10-18,0,0,0,0\n',
  );
  expect(dayValue(new Date(2026, 9, 8))).toBe("2026-10-08");
});

it("reads the last seven days and shows a column per day", async () => {
  const fetchMock = vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify(REPORT)),
  );
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => root.render(<CallsReport />));
  const url = new URL(String(fetchMock.mock.calls[0][0]), "https://x");
  expect(url.pathname).toMatch(/\/reports\/calls$/);
  const start = new Date(`${url.searchParams.get("start")}T00:00:00`);
  const end = new Date(`${url.searchParams.get("end")}T00:00:00`);
  expect(Math.round((end.getTime() - start.getTime()) / 86_400_000)).toBe(6);
  const table = host.querySelector('table[aria-label="Calls by seller"]')!;
  expect(table.querySelectorAll("thead th")).toHaveLength(7);
  expect(table.textContent).toContain("Asha");
  expect(table.textContent).toContain("12");
  expect(host.textContent).toContain("CSV");
});

it("names sellers without calls on one line instead of empty rows", () => {
  const idle = (name: string) => ({
    ...REPORT.sellers[0],
    person_id: name,
    name,
    calls: 0,
    connected: 0,
    talk_seconds: 0,
    missed: 0,
  });
  const report = {
    ...REPORT,
    sellers: [
      REPORT.sellers[0],
      ...["A", "B", "C", "D", "E", "F", "G", "H"].map(idle),
    ],
  };
  const { active, idle: none } = splitIdle(report);
  expect(active).toHaveLength(1);
  expect(idleLine(none.map((seller) => seller.name))).toBe(
    "A, B, C, D, E, F and 2 more",
  );
  // A header, every seller on every day, and the closing newline.
  expect(callsCsv(report).trimEnd().split(/\r?\n/)).toHaveLength(1 + 9 * 2);
});
