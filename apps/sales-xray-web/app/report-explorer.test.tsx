import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportExplorer } from "./report-explorer";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  window.history.replaceState(null, "", "/");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

function Search() {
  const [phrase, setPhrase] = useState("");
  return (
    <button onClick={() => setPhrase("Literal source phrase")}>
      {phrase || "Search"}
    </button>
  );
}
async function render(label = "Explore report", second = "Transcript") {
  await act(async () =>
    root.render(
      <ReportExplorer
        label={label}
        panels={[
          {
            id: "overview",
            label: "Overview",
            content: <p>Observed summary</p>,
          },
          { id: "transcript", label: second, content: <Search /> },
          {
            id: "sound",
            label: "Sound",
            compactLabel: "Audio",
            content: <p>Saved sound</p>,
          },
        ]}
      />,
    ),
  );
}
const tabs = () => [
  ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
];

it("preserves search state and selection through section and language changes", async () => {
  await render();
  await act(async () => tabs()[1].click());
  const search = container.querySelector<HTMLButtonElement>(
    '[role="tabpanel"]:not([hidden]) button',
  )!;
  await act(async () => search.click());
  await act(async () => tabs()[0].click());
  expect(search.isConnected).toBe(true);
  expect(search.closest('[role="tabpanel"]')!.hasAttribute("hidden")).toBe(
    true,
  );
  await act(async () => tabs()[1].click());
  await render("अपनी रिपोर्ट देखें", "पूरी बातचीत");
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
  expect(search.textContent).toBe("Literal source phrase");
  expect(
    container.querySelectorAll('[role="tabpanel"]:not([hidden])'),
  ).toHaveLength(1);
});

it("supports roving keyboard focus, wraparound and labelled panels", async () => {
  await render();
  const press = async (key: string) =>
    act(async () => {
      const selected = tabs().find((tab) => tab.tabIndex === 0)!;
      selected.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true }),
      );
    });
  await press("ArrowLeft");
  expect(document.activeElement).toBe(tabs()[2]);
  await press("ArrowRight");
  expect(document.activeElement).toBe(tabs()[0]);
  await press("End");
  expect(document.activeElement).toBe(tabs()[2]);
  await press("Home");
  expect(document.activeElement).toBe(tabs()[0]);
  for (const tab of tabs()) {
    const panel = document.getElementById(tab.getAttribute("aria-controls")!);
    expect(panel?.getAttribute("aria-labelledby")).toBe(tab.id);
  }
  expect(tabs()[2].getAttribute("aria-label")).toBe("Sound (Audio)");
  expect(tabs()[2].textContent).toContain("Audio");
});

it("falls back to a permitted panel if the selected section is removed", async () => {
  await render();
  await act(async () => tabs()[2].click());
  await act(async () =>
    root.render(
      <ReportExplorer
        label="Allowed report"
        panels={[
          {
            id: "overview",
            label: "Overview",
            content: <p>Allowed summary</p>,
          },
        ]}
      />,
    ),
  );
  expect(tabs()[0].getAttribute("aria-selected")).toBe("true");
  expect(container.textContent).not.toContain("Saved sound");
});

const callId = "c2793fdf-4948-47e4-a4bc-973f2b7720bc";
async function renderBound() {
  await act(async () =>
    root.render(
      <ReportExplorer
        label="Saved report"
        boundCallId={callId}
        panels={[
          { id: "overview", label: "Overview", content: <p>Summary</p> },
          { id: "prospect", label: "Prospect", content: <Search /> },
          {
            id: "moments",
            label: "Moments",
            content: <audio aria-label="Source audio" />,
          },
        ]}
      />,
    ),
  );
}

it("restores a bookmarked section and follows history without remounting panels or reading the API", async () => {
  window.history.replaceState(null, "", `/?call=${callId}&section=prospect`);
  const fetch = vi.spyOn(window, "fetch");
  await renderBound();
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
  const source = container.querySelector("audio")!;
  const search = container.querySelector<HTMLButtonElement>(
    '[role="tabpanel"]:not([hidden]) button',
  )!;
  await act(async () => search.click());
  await act(async () => tabs()[2].click());
  expect(window.location.search).toBe(`?call=${callId}&section=moments`);
  await act(async () => {
    // popstate is the browser's Back/Forward delivery contract.
    window.history.replaceState(null, "", `/?call=${callId}&section=prospect`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
  expect(search.textContent).toBe("Literal source phrase");
  expect(container.querySelector("audio")).toBe(source);
  expect(fetch).not.toHaveBeenCalled();
});

it("replaces the current report entry for clicks and keyboard browsing without stealing focus on history updates", async () => {
  window.history.replaceState(null, "", `/?call=${callId}&section=overview`);
  await renderBound();
  const push = vi.spyOn(window.history, "pushState");
  const replace = vi.spyOn(window.history, "replaceState");
  await act(async () => tabs()[1].click());
  expect(push).not.toHaveBeenCalled();
  expect(replace).toHaveBeenCalledTimes(1);
  await act(async () => tabs()[1].click());
  expect(push).not.toHaveBeenCalled();
  expect(replace).toHaveBeenCalledTimes(1);
  await act(async () => tabs()[2].click());
  expect(replace).toHaveBeenCalledTimes(2);
  await act(async () =>
    tabs()[2].dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
    ),
  );
  expect(push).not.toHaveBeenCalled();
  expect(replace).toHaveBeenCalledTimes(3);
  expect(document.activeElement).toBe(tabs()[0]);
  await act(async () => {
    window.history.replaceState(null, "", `/?call=${callId}&section=prospect`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
  expect(document.activeElement).toBe(tabs()[0]);
});

it("does not use section or stage selectors for another call", async () => {
  window.history.replaceState(
    null,
    "",
    "/?call=7b6443d3-9b2d-4f97-9e70-5e82e54f8738&section=prospect&stage=C2",
  );
  await renderBound();
  expect(tabs()[0].getAttribute("aria-selected")).toBe("true");
  const original = window.location.href;
  await act(async () => tabs()[1].click());
  expect(window.location.href).toBe(original);
  expect(tabs()[0].getAttribute("aria-selected")).toBe("true");
});
