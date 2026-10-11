import { webcrypto } from "node:crypto";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BulkImportPreview } from "./bulk-import-preview";
import { importManifestDigest } from "./bulk-import-files";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const file = (path = "Team/स्वामिनी/call") =>
  ({
    name: "call",
    webkitRelativePath: path,
    size: 3,
    arrayBuffer: vi.fn(async () => new TextEncoder().encode("abc").buffer),
  }) as unknown as File;
async function choose(files: File[]) {
  const input = host.querySelector("input")!;
  Object.defineProperty(input, "files", { configurable: true, value: files });
  await act(async () => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
const wait = async (check: () => void) => {
  await vi.waitFor(async () => {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    check();
  });
};

it("selects a directory without inventing an imported call", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<BulkImportPreview />));
  expect(host.querySelector("input")?.hasAttribute("webkitdirectory")).toBe(
    true,
  );
  expect(host.textContent).toContain("Recordings stay on your device");
  expect(host.querySelector("[aria-busy]")?.getAttribute("aria-busy")).toBe(
    "false",
  );
  expect(fetcher).not.toHaveBeenCalled();
});

it("real file hashes feed one preview and display a proposed Devanagari member", async () => {
  const fetcher = vi.fn(async (_url: string, options: RequestInit) => {
    const manifest = JSON.parse(String(options.body));
    return Response.json({
      tenant_id: "00000000-0000-4000-8000-000000000001",
      manifest_sha256: await importManifestDigest(manifest),
      requires_confirmation: true,
      total_files: 1,
      total_bytes: 3,
      members: [
        {
          person_id: "00000000-0000-4000-8000-000000000002",
          display_name: "स्वामिनी",
        },
      ],
      folders: [
        {
          folder: "स्वामिनी",
          proposed_person_id: "00000000-0000-4000-8000-000000000002",
          match_state: "suggested",
          file_count: 1,
          source_bytes: 3,
        },
      ],
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const onPreview = vi.fn();
  await act(async () =>
    root.render(<BulkImportPreview onPreview={onPreview} />),
  );
  await choose([file()]);
  await wait(() => expect(onPreview).toHaveBeenCalledOnce());
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0][0]).toBe(
    "/v1/conversation/acquisition/imports/preview",
  );
  expect(host.textContent).toContain("स्वामिनी");
  expect(host.textContent).toContain("Needs confirmation");
  expect(host.textContent).not.toContain("Done");
  expect(host.querySelector("[aria-busy]")?.getAttribute("aria-busy")).toBe(
    "false",
  );
});

it("a missing endpoint or malformed response clears the skeleton with an unavailable card", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({})),
  );
  await act(async () => root.render(<BulkImportPreview />));
  await choose([file()]);
  await wait(() =>
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      "unavailable",
    ),
  );
  expect(host.querySelector("[aria-busy]")?.getAttribute("aria-busy")).toBe(
    "false",
  );
  expect(host.querySelector("table")).toBeNull();
});

it("cancel stops a stalled file read and a later completion cannot replace the screen", async () => {
  const pending = file();
  let finish!: (bytes: ArrayBuffer) => void;
  vi.mocked(pending.arrayBuffer).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(<BulkImportPreview />));
  await choose([pending]);
  const cancel = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Cancel",
  )!;
  await act(async () => cancel.click());
  await act(async () => finish(new TextEncoder().encode("abc").buffer));
  expect(host.querySelector("[aria-busy]")?.getAttribute("aria-busy")).toBe(
    "false",
  );
  expect(fetcher).not.toHaveBeenCalled();
  expect(host.querySelector("table")).toBeNull();
});
