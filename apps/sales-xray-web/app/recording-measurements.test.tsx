import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { measurementFixture } from "../tests/measurement-fixture";
import { RecordingMeasurements } from "./recording-measurements";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
async function expand() {
  await act(async () => {
    const details = container.querySelector("details")!;
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
}
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("saved recording sound view", () => {
  it("loads only on expansion, renders saved figures and switches plots", async () => {
    const fetcher = vi.fn(
      async () => new Response(JSON.stringify(measurementFixture())),
    );
    vi.stubGlobal("fetch", fetcher);
    await act(async () =>
      root.render(
        <RecordingMeasurements
          recordingId="recording-1"
          sourceSha256={"ab".repeat(32)}
        />,
      ),
    );
    expect(fetcher).not.toHaveBeenCalled();
    await expand();
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/conversation/recordings/recording-1/measurements",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
    expect(container.textContent).toContain("-19.3 dBFS");
    expect(container.textContent).toContain("40.0% of windows");
    const pitch = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Pitch estimate",
    )!;
    await act(async () => pitch.click());
    expect(
      container
        .querySelector('input[type="range"]')
        ?.getAttribute("aria-label"),
    ).toContain("pitch estimate");
    expect(container.querySelector("output")?.textContent).toContain(
      "190.0 Hz",
    );
    expect(
      container.querySelector("svg[role=img] path[d*='M36']"),
    ).toBeTruthy();
    for (const [language, label] of [
      ["mr", "रेकॉर्डिंगचा आवाज"],
      ["hi", "रिकॉर्डिंग की आवाज़"],
      ["en-hi-mixed", "Sound of the recording · रिकॉर्डिंग की आवाज़"],
    ] as const) {
      await act(async () =>
        root.render(
          <RecordingMeasurements
            recordingId="recording-1"
            sourceSha256={"ab".repeat(32)}
            language={language}
          />,
        ),
      );
      expect(container.querySelector("summary")?.textContent).toContain(label);
      expect(container.querySelector("output")?.textContent).toContain(
        "190.0 Hz",
      );
      expect(fetcher).toHaveBeenCalledTimes(1);
    }
  });
  it("shows unavailable for missing or mismatched data and retries only a read", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 409 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(measurementFixture())),
      );
    vi.stubGlobal("fetch", fetcher);
    await act(async () =>
      root.render(
        <RecordingMeasurements
          recordingId="recording-1"
          sourceSha256={"ab".repeat(32)}
        />,
      ),
    );
    await expand();
    expect(container.textContent).toContain("unavailable for this call");
    expect(container.textContent).not.toContain("0.0 dBFS");
    await act(async () => container.querySelector("button")!.click());
    expect(container.textContent).toContain("-19.3 dBFS");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("does not render the last call's values after selecting a different recording", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(measurementFixture()))),
    );
    await act(async () =>
      root.render(
        <RecordingMeasurements
          recordingId="recording-1"
          sourceSha256={"ab".repeat(32)}
        />,
      ),
    );
    await expand();
    expect(container.textContent).toContain("-19.3 dBFS");
    await act(async () =>
      root.render(
        <RecordingMeasurements
          recordingId="recording-2"
          sourceSha256={"ab".repeat(32)}
        />,
      ),
    );
    expect(container.textContent).not.toContain("-19.3 dBFS");
    expect(container.textContent).toContain("unavailable for this call");
  });
});
