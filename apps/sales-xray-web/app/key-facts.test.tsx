import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import { readCallFacts } from "./call-facts";
import { KeyFacts } from "./key-facts";
import type { SalesReport, Transcript } from "./report-contract";
import { saveSpeakerProfiles } from "./speaker-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL = "5b7a0d2e-8c4f-4a61-9d3e-2f1b0c9a8e77";
const report = {
  ...(fixture.report as SalesReport),
  summary: "A carpentry business owner in Ahmedabad asked about growth.",
};
const transcript: Transcript = {
  ...(fixture.transcript as Transcript),
  duration_ms: 1_440_000,
  segments: [
    {
      id: "a1",
      speaker_id: "rep",
      start_ms: 0,
      end_ms: 9_000,
      text: "नमस्ते, मुझे 10 15 minute का time लगेगा।",
    },
    {
      id: "a2",
      speaker_id: "buyer",
      start_ms: 9_500,
      end_ms: 14_000,
      text: "10 minute तक चलेगा।",
    },
    {
      id: "a3",
      speaker_id: "buyer",
      start_ms: 240_000,
      end_ms: 250_000,
      text: "हां turnover ₹1 CR होता है yearly.",
    },
    {
      id: "a4",
      speaker_id: "rep",
      start_ms: 1_300_000,
      end_ms: 1_320_000,
      text: "इसका price अलग अलग category का है।",
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
  await render();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
});

async function render(source: Transcript = transcript) {
  await act(async () =>
    root.render(
      <KeyFacts
        callId={CALL}
        transcript={source}
        report={report}
        durationMs={transcript.duration_ms}
        onSeek={onSeek}
      />,
    ),
  );
}

function row(label: string) {
  return Array.from(host.querySelectorAll("div")).find(
    (element) => element.firstElementChild?.textContent === label,
  )!;
}

it("shows only what the call really said, with a play button for each", async () => {
  expect(row("Time asked for").textContent).toContain("Up to 15 min");
  expect(row("Time asked for").textContent).toContain("call took 24 min");
  expect(row("Price or budget").textContent).toContain("no amount said");
  expect(row("Industry").textContent).toContain("Not found");
  const play = row("Time asked for").querySelector("button")!;
  await act(async () => play.click());
  expect(onSeek).toHaveBeenCalledWith(0);
});

it("does not infer industry from report prose and saves a user choice", async () => {
  expect(row("Industry").textContent).toContain("Not found");
  expect(
    Array.from(row("Industry").querySelectorAll("button")).some(
      (button) => button.textContent === "Yes",
    ),
  ).toBe(false);
  await act(async () =>
    Array.from(row("Industry").querySelectorAll("button"))[0].click(),
  );
  const select = row("Industry").querySelector<HTMLSelectElement>(
    'select[aria-label="Industry"]',
  )!;
  await act(async () => {
    select.value = "Carpentry & building";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(readCallFacts(CALL).values.industry).toBe("Carpentry & building");
  expect(readCallFacts(CALL).confirmed.industry).toBe(true);
  expect(row("Industry").textContent).toContain("Confirmed");
});

it("does not infer or offer to confirm industry from prospect statements", async () => {
  await act(async () => {
    saveSpeakerProfiles(CALL, {
      rep: { name: "Fictional Rep", role: "salesperson", icon: null },
      buyer: { name: "Fictional Buyer", role: "prospect", icon: null },
    });
  });

  const statements = [
    "If I run a carpentry business, I will need new tools.",
    "I have a carpentry business plan.",
    "मेरा carpentry का business nahi hai.",
  ];
  for (const text of statements) {
    await render({
      ...transcript,
      segments: [
        {
          id: "seller",
          speaker_id: "rep",
          start_ms: 0,
          end_ms: 500,
          text: "Hello.",
        },
        {
          id: "prospect",
          speaker_id: "buyer",
          start_ms: 500,
          end_ms: 1_000,
          text,
        },
      ],
    });
    expect(row("Industry").textContent).toContain("Not found");
    expect(row("Industry").textContent).not.toContain("Carpentry & building");
    expect(
      [...row("Industry").querySelectorAll("button")].some(
        (button) => button.textContent === "Yes",
      ),
    ).toBe(false);
    expect(readCallFacts(CALL).values.industry).toBeFalsy();
    expect(readCallFacts(CALL).confirmed.industry).not.toBe(true);
  }
});

it("lets the person say what a heard number means", async () => {
  // A chip opens a small panel of choices instead of a dropdown.
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('button[aria-label^="What is"]')!
      .click(),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>('[role="group"] button')]
      .find((button) => button.textContent === "Yearly sales")!
      .click(),
  );
  expect(readCallFacts(CALL).numberLabels["a3:0"]).toBe("Yearly sales");
});

it("names the people once the call map has them", async () => {
  expect(row("Who is on the call").textContent).toContain("Not named yet");
  await act(async () => {
    saveSpeakerProfiles(CALL, {
      rep: { name: "Manas", role: "salesperson", icon: null },
      buyer: { name: "Nandlal ji", role: "prospect", icon: null },
    });
  });
  expect(row("Who is on the call").textContent).toContain(
    "Manas (salesperson) · Nandlal ji (prospect)",
  );
});

it("shows saved speaker names before a role is selected", async () => {
  await act(async () => {
    saveSpeakerProfiles(CALL, {
      buyer: { name: "Fictional Buyer", role: null, icon: null },
    });
  });
  expect(row("Who is on the call").textContent).toContain("Fictional Buyer");
  expect(row("Who is on the call").textContent).not.toContain("prospect");
});
