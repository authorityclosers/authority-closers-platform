import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import { ReportRawData } from "./report-raw-data";
import type { SalesReport, Transcript } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const report = fixture.report as SalesReport;
const transcript: Transcript = {
  ...(fixture.transcript as Transcript),
  duration_ms: 300_000,
  segments: [
    {
      id: "b1",
      speaker_id: "rep",
      start_ms: 0,
      end_ms: 6_000,
      text: "कितने साल से चल रहा है business? और staff कितने हैं?",
    },
    {
      id: "b2",
      speaker_id: "buyer",
      start_ms: 6_500,
      end_ms: 12_000,
      text: "15 बरस से, turnover 1 CR है।",
    },
    {
      id: "b3",
      speaker_id: "rep",
      start_ms: 60_000,
      end_ms: 70_000,
      text: "इसका price category के हिसाब से है।",
    },
  ],
};

let root: Root;
let host: HTMLDivElement;
let onSeek: ReturnType<typeof vi.fn<(ms: number) => void>>;

beforeEach(async () => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  onSeek = vi.fn();
  await act(async () =>
    root.render(
      <ReportRawData
        callId="6c1e2f3a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
        transcript={transcript}
        report={report}
        durationMs={transcript.duration_ms}
        runId="9f8e7d6c-0000-4000-8000-000000000000"
        onSeek={onSeek}
      />,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

function section(title: string) {
  return Array.from(host.querySelectorAll("section")).find((element) =>
    element.querySelector("h3")?.textContent?.startsWith(title),
  )!;
}

it("lists the real questions, numbers and price talk from the call", () => {
  const questions = section("Questions asked");
  expect(questions.querySelector("h3")?.textContent).toBe("Questions asked2");
  expect(questions.textContent).toContain("staff कितने हैं?");
  const numbers = section("Numbers heard").textContent ?? "";
  expect(numbers).toContain("1 CR");
  expect(numbers).toContain("15 बरस");
  expect(section("Price or budget talk").textContent).toContain("price");
  expect(section("How this report was made").textContent).toContain("9f8e7d6c");
});

it("plays a row from its time and filters rows by search", async () => {
  const play = section("Questions asked").querySelector("button")!;
  await act(async () => play.click());
  expect(onSeek).toHaveBeenCalledWith(0);

  const search = host.querySelector<HTMLInputElement>(
    'input[aria-label="Search the raw data"]',
  )!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(search, "staff");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(section("Questions asked").querySelector("h3")?.textContent).toBe(
    "Questions asked1",
  );
  expect(section("Numbers heard").textContent).toContain("No numbers");
});

it("exports the data as JSON and CSV files", async () => {
  const created: Blob[] = [];
  const createObjectURL = vi.fn((blob: Blob) => {
    created.push(blob);
    return "blob:raw";
  });
  const revokeObjectURL = vi.fn();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const buttons = Array.from(host.querySelectorAll("button"));
  await act(async () => buttons.find((b) => b.textContent === "JSON")!.click());
  await act(async () => buttons.find((b) => b.textContent === "CSV")!.click());
  expect(click).toHaveBeenCalledTimes(2);
  const read = (blob: Blob) =>
    new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
  const json = JSON.parse(await read(created[0]));
  expect(json.questions).toHaveLength(2);
  expect(json.source.run_id).toBe("9f8e7d6c-0000-4000-8000-000000000000");
  expect(await read(created[1])).toContain("question,00:00");
  click.mockRestore();
});
