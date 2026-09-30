import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RecentCallItem } from "./recent-call-item";
import { readCallFacts, saveCallFact } from "../call-facts";
import { readSpeakerProfiles, saveSpeakerProfiles } from "../speaker-profiles";

vi.mock("next/link", () => ({
  default: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} />
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const call = {
  id: "4f0c2a77-1b53-4c55-8d11-9f3a2b6e7c10",
  name: "Fictional call",
  date: "Sep 29, 2026",
};
const href = `/analysis/calls/${call.id}`;
let root: Root;
let host: HTMLDivElement;
const onChange = vi.fn();
let navigate: ReturnType<typeof vi.spyOn>;

beforeEach(async () => {
  localStorage.clear();
  window.history.replaceState(null, "", href);
  navigate = vi.spyOn(window.location, "replace").mockImplementation(() => {});
  onChange.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(<RecentCallItem call={call} href={href} onChange={onChange} />),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function click(label: string) {
  const button = Array.from(host.querySelectorAll("button")).find(
    (item) =>
      item.textContent === label || item.getAttribute("aria-label") === label,
  )!;
  await act(async () => button.click());
}

async function confirmDelete() {
  await click("More options for Fictional call");
  await click("Delete…");
  expect(navigate).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
  await click("Delete");
}

function seedCallFacts() {
  saveCallFact(call.id, {
    kind: "value",
    id: "industry",
    value: "Carpentry",
  });
  saveSpeakerProfiles(call.id, {
    buyer: { name: "Fictional Buyer", role: "prospect", icon: null },
  });
}

it.each(["deleting", "deleted"])(
  "leaves the active report only after the server confirms %s",
  async (state) => {
    seedCallFacts();
    const fetcher = vi.fn(async () => Response.json({ state }));
    vi.stubGlobal("fetch", fetcher);
    await confirmDelete();
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining(`/submissions/${call.id}`),
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(onChange).toHaveBeenCalledExactlyOnceWith(null);
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/analysis/calls");
    expect(readCallFacts(call.id)).toEqual({
      confirmed: {},
      values: {},
      numberLabels: {},
    });
    expect(readSpeakerProfiles(call.id)).toEqual({});
  },
);

it.each([403, 500, 200])(
  "keeps an unconfirmed deletion on screen (%s)",
  async (status) => {
    seedCallFacts();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ state: "ready" }, { status })),
    );
    await confirmDelete();
    expect(navigate).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      "Couldn’t delete this call. Try again.",
    );
    expect(readCallFacts(call.id).values.industry).toBe("Carpentry");
    expect(readSpeakerProfiles(call.id).buyer.name).toBe("Fictional Buyer");
  },
);

it("keeps a different open report when another recent call is deleted", async () => {
  window.history.replaceState(
    null,
    "",
    "/analysis/calls/eaed7960-d4d0-4675-bd34-5b6a7d9c598d",
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ state: "deleted" })),
  );
  await confirmDelete();
  expect(onChange).toHaveBeenCalledExactlyOnceWith(null);
  expect(navigate).not.toHaveBeenCalled();
});

it("opens Rename from its button without navigating the call link", async () => {
  expect(host.querySelector("a")?.title).toBe(call.name);
  await click("More options for Fictional call");
  await click("Rename");
  const input = host.querySelector<HTMLInputElement>(
    '[aria-label="Call name"]',
  );
  expect(input?.value).toBe(call.name);
  expect(document.activeElement).toBe(input);
  expect(navigate).not.toHaveBeenCalled();
});
