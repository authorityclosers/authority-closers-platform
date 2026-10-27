import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  pick: vi.fn(),
  read: vi.fn(),
  preview: vi.fn(),
}));

vi.mock("./google-picker", async (original) => ({
  ...(await original<typeof import("./google-picker")>()),
  pickGoogleSheet: calls.pick,
}));
vi.mock("./google-files-client", async (original) => ({
  ...(await original<typeof import("./google-files-client")>()),
  readGoogleFiles: calls.read,
  previewGoogleSheet: calls.preview,
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));
vi.mock("./use-pipelines", () => ({
  usePipelines: () => null,
  several: () => false,
  forgetPipelines: () => undefined,
}));

import { resetBackCloseForTests } from "../ui/back-close";
import { ImportDialog } from "./capture-dialogs";
import { GoogleFilesError, type GoogleFiles } from "./google-files-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Import from a Google Sheet (Lead OS, 27 Oct 2026): the Sheet someone picks
// in Google's Picker is read into the same preview a file gets. Made-up
// people only.
let root: Root;
let host: HTMLDivElement;

const files = (over: Partial<GoogleFiles> = {}): GoogleFiles => ({
  configured: true,
  picker: true,
  connected: true,
  email: "owner@fictional.example",
  connected_by: "Priya Example",
  folder_url: null,
  copy: null,
  ...over,
});

beforeEach(() => {
  calls.pick.mockReset();
  calls.read.mockReset();
  calls.preview.mockReset();
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  // The dialog's other reads have nothing to say here; never the network.
  vi.stubGlobal("fetch", async () =>
    Response.json({ detail: "Not here" }, { status: 404 }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
});

const settle = async () =>
  act(async () => {
    for (let index = 0; index < 8; index += 1) await Promise.resolve();
  });

const mount = async (google: boolean) => {
  await act(async () =>
    root.render(
      <ImportDialog
        open
        canManage
        google={google}
        onClose={() => undefined}
        onDone={() => undefined}
      />,
    ),
  );
  await settle();
};

it("opens the Picker when it arrived for a Google Sheet, and previews the Sheet picked", async () => {
  calls.read.mockResolvedValue(files());
  calls.pick.mockResolvedValue("sheet-1");
  calls.preview.mockResolvedValue({
    file_name: "Leads from the expo",
    headers: ["Name", "Phone"],
    rows: [
      { Name: "Asha Example", Phone: "98760 72001" },
      { Name: "Ravi Sample", Phone: "98760 72002" },
    ],
    total_rows: 2,
    truncated: false,
    mapping: { name: "Name", phone: "Phone" },
    with_phone: 2,
    repeats_in_file: 0,
    importable: 2,
  });
  await mount(true);
  expect(calls.pick).toHaveBeenCalledOnce();
  expect(calls.preview).toHaveBeenCalledWith("sheet-1");
  expect(
    [...document.querySelectorAll("button")].some(
      (button) => button.textContent === "Import 2 leads",
    ),
  ).toBe(true);
});

it("offers the Picker beside the file when Google is connected", async () => {
  calls.read.mockResolvedValue(files());
  calls.pick.mockResolvedValue(null);
  await mount(false);
  expect(calls.pick).not.toHaveBeenCalled();
  const button = [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.endsWith("Pick a Google Sheet"),
  );
  expect(button).toBeDefined();
  await act(async () => button!.click());
  await settle();
  // Closed without picking: nothing is read, nothing is said.
  expect(calls.pick).toHaveBeenCalledOnce();
  expect(calls.preview).not.toHaveBeenCalled();
});

it("says where to connect Google when the Picker finds it gone", async () => {
  calls.read.mockResolvedValue(files());
  calls.pick.mockRejectedValue(
    new GoogleFilesError("Connect Google first.", 409),
  );
  await mount(false);
  const pickButton = () =>
    [...document.querySelectorAll("button")].find((item) =>
      item.textContent?.endsWith("Pick a Google Sheet"),
    );
  await act(async () => pickButton()!.click());
  await settle();
  expect(document.body.textContent).toContain(
    "Connect Google Sheets and Drive first: Settings → Connected apps.",
  );
  expect(
    [...document.querySelectorAll("a")].some((link) =>
      link.textContent?.includes("Connected apps"),
    ),
  ).toBe(true);
  expect(pickButton()).toBeUndefined();
  expect(calls.preview).not.toHaveBeenCalled();
});

it("says to connect Google first when it isn't", async () => {
  calls.read.mockResolvedValue(files({ connected: false }));
  await mount(true);
  expect(calls.pick).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain(
    "Connect Google Sheets and Drive first: Settings → Connected apps.",
  );
  expect(
    [...document.querySelectorAll("button")].some((button) =>
      button.textContent?.endsWith("Pick a Google Sheet"),
    ),
  ).toBe(false);
});
