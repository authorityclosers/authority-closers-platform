// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AnalysisWave, useMeasuredWave } from "./analysis-wave";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const id = "00000000-0000-4000-8000-000000000500";
const envelope = {
  schema: "ac.sales-xray.waveform/1",
  kind: "rms_envelope",
  duration_ms: 60_000,
  points: Array.from({ length: 60 }, (_, index) => ({
    start_ms: index * 1000,
    level: index % 2 ? 0.9 : 0.1,
  })),
};

let root: Root;
let host: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

function Probe({ stage, played }: { stage: string; played: number }) {
  const measured = useMeasuredWave(id, stage);
  return <AnalysisWave envelope={measured} played={played} state="working" />;
}
const settle = () => act(async () => new Promise((r) => setTimeout(r, 0)));

it("draws the motif until the server has measured the call, then the call itself", async () => {
  fetchMock.mockResolvedValueOnce(new Response("{}", { status: 404 }));
  await act(async () => root.render(<Probe stage="C1" played={0} />));
  await settle();
  const wave = () => host.querySelector('[role="img"]') as HTMLElement;
  expect(wave().getAttribute("aria-label")).toBe("Your call");
  expect(wave().hasAttribute("data-measured")).toBe(false);
  // Asked again at the next stage; now measured.
  fetchMock.mockResolvedValueOnce(Response.json(envelope));
  await act(async () => root.render(<Probe stage="C2" played={1 / 3} />));
  await settle();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[1][0]).toBe(
    `/v1/conversation/acquisition/submissions/${id}/waveform`,
  );
  expect(wave().hasAttribute("data-measured")).toBe(true);
  expect(wave().getAttribute("aria-label")).toBe(
    "Your call's sound level over its length",
  );
  // A third of the bars are teal: one of three steps finished.
  const bars = [...wave().querySelectorAll("i")];
  expect(bars.filter((bar) => bar.hasAttribute("data-played"))).toHaveLength(
    32,
  );
  // Never asked again once measured.
  await act(async () => root.render(<Probe stage="C4" played={2 / 3} />));
  await settle();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("shows how much of the file has arrived while it is sent", async () => {
  await act(async () =>
    root.render(
      <AnalysisWave
        envelope={null}
        arrived={0.4}
        played={0}
        state="arriving"
      />,
    ),
  );
  const wave = host.querySelector('[role="img"]') as HTMLElement;
  expect(wave.getAttribute("aria-label")).toBe("Uploading your call, 40% sent");
  const bars = [...wave.querySelectorAll("i")];
  expect(bars.filter((bar) => bar.hasAttribute("data-pending")).length).toBe(
    58,
  );
});
