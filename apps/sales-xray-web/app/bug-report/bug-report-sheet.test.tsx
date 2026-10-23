import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.fn();
vi.mock("../notice-center", () => ({
  notify: (...args: unknown[]) => notify(...args),
}));
const captureScreen = vi.fn<() => Promise<Blob | null>>();
vi.mock("./capture", () => ({ captureScreen: () => captureScreen() }));
vi.mock("./device", () => ({
  reportContext: async () => ({
    app: { channel: "web", release: "abc123" },
    device: { os: "Android 14", viewport: "390x844" },
  }),
}));
const phone = { app: false };
const askScreenshot = vi.fn<() => Promise<Blob | null>>(async () => null);
vi.mock("../leads/native-phone", () => ({
  inPhoneApp: () => phone.app,
  askScreenshot: () => askScreenshot(),
}));
const keep = vi.fn(async () => false);
vi.mock("./outbox", () => ({
  keepNow: (kind: string, id: string, body: unknown) =>
    keep(...([{ id, kind, body }] as unknown as [])),
  flush: async () => 0,
}));

import { useRegisteredCommands } from "../ui/command-registry";
import { resetBackCloseForTests } from "../ui/back-close";
import { BugReportHost, privateScreen } from "./bug-report-sheet";
import { openBugReport } from "./open";
import { clearRecentErrors, recordError } from "./recent-errors";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;

/** The command bar's list, drawn as buttons. */
function Commands() {
  const { commands } = useRegisteredCommands();
  return (
    <>
      {commands.map((command) => (
        <button
          key={command.id}
          type="button"
          data-command={command.id}
          onClick={command.run}
        >
          {command.label}
        </button>
      ))}
    </>
  );
}

const pause = (ms: number) =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });

beforeEach(async () => {
  notify.mockReset();
  keep.mockReset();
  keep.mockResolvedValue(false);
  phone.app = false;
  askScreenshot.mockReset();
  askScreenshot.mockResolvedValue(null);
  captureScreen.mockReset();
  clearRecentErrors();
  if (!URL.createObjectURL) {
    Object.assign(URL, {
      createObjectURL: () => "blob:preview",
      revokeObjectURL: () => {},
    });
  }
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <>
        <BugReportHost />
        <Commands />
      </>,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function type(text: string) {
  const area = document.querySelector("textarea")!;
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )!.set!;
  setter.call(area, text);
  area.dispatchEvent(new Event("input", { bubbles: true }));
}

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );
  if (!found) throw new Error(`no button ${label}`);
  return found;
}

async function submit() {
  await act(async () => {
    document
      .querySelector("dialog form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await pause(20);
}

it("is offered in the command bar and opens from anywhere", async () => {
  const offered = document.querySelector<HTMLButtonElement>(
    '[data-command="bug-report:open"]',
  );
  expect(offered?.textContent).toBe("Report a problem");
  captureScreen.mockResolvedValue(null);
  await act(async () => offered!.click());
  const dialog = document.querySelector("dialog")!;
  expect(dialog.open).toBe(true);
  expect(dialog.textContent).toContain("What went wrong?");
  expect(button("Send report").disabled).toBe(true);
});

it("sends words, the screen, device, recent errors and the picture, then thanks", async () => {
  window.history.replaceState(null, "", "/leads?lead=8f0e&token=secret#x");
  const picture = new Blob([new Uint8Array([1, 2, 3])], { type: "image/webp" });
  captureScreen.mockResolvedValue(picture);
  recordError({
    kind: "http",
    status: 500,
    method: "POST",
    path: "/v1/lead-desk/x",
  });
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify({ bug_id: "b-1", screenshot: "kept" }), {
      status: 201,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () => openBugReport());
  await pause(450);
  expect(captureScreen).toHaveBeenCalledTimes(1);
  expect(document.querySelector("dialog img")?.getAttribute("alt")).toContain(
    "Picture of the screen",
  );
  await act(async () => type("Tapped Call and nothing happened."));
  await act(async () => button("This stops my work").click());
  expect(button("This stops my work").getAttribute("aria-pressed")).toBe(
    "true",
  );
  await submit();

  expect(fetcher).toHaveBeenCalledTimes(1);
  const [path, init] = fetcher.mock.calls[0] as [string, RequestInit];
  expect(path).toBe("/v1/bug-reports");
  expect(init.method).toBe("POST");
  const body = JSON.parse(String(init.body));
  expect(body).toMatchObject({
    words: "Tapped Call and nothing happened.",
    blocks_work: true,
    route: "/leads?lead=8f0e&token=",
    context: { app: { channel: "web", release: "abc123" } },
    client_errors: [
      { kind: "http", status: 500, method: "POST", path: "/v1/lead-desk/x" },
    ],
    screenshot: { content_type: "image/webp", data: "AQID", source: "auto" },
  });
  expect(body.command_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(body.voice).toBeNull();
  // The sheet stays to say what happens next.
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Sent. We'll tell you when it's fixed.",
  );
  expect(notify).not.toHaveBeenCalled();
  await act(async () => button("Done").click());
  await pause(600);
  expect(document.querySelector("dialog")?.open).toBe(false);
});

it("with no connection, keeps the report on the phone and says it will go later", async () => {
  captureScreen.mockResolvedValue(null);
  keep.mockResolvedValue(true);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  await act(async () => openBugReport());
  await pause(450);
  await act(async () => type("Leads list is blank"));
  await submit();
  expect(keep).toHaveBeenCalledWith(
    expect.objectContaining({
      kind: "bug",
      body: expect.objectContaining({ words: "Leads list is blank" }),
    }),
  );
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Saved on this phone.",
  );
  expect(notify).not.toHaveBeenCalled();
});

it("keeps everything when sending fails and offers Send again in a corner card", async () => {
  captureScreen.mockResolvedValue(null);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "That's a lot of reports in an hour." }),
        {
          status: 429,
          headers: { "content-type": "application/json" },
        },
      ),
    ),
  );
  await act(async () =>
    openBugReport({ title: "Couldn't save the note", reference: "req-77aa" }),
  );
  await pause(450);
  expect(document.querySelector("dialog")?.textContent).toContain(
    "About: Couldn't save the note",
  );
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Couldn't take one here",
  );
  await act(async () => type("The note vanished"));
  await submit();
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "error",
      title: "Your report didn't go",
      message: "That's a lot of reports in an hour.",
      noReport: true,
    }),
  );
  expect(document.querySelector("dialog")?.open).toBe(true);
  expect(document.querySelector("textarea")?.value).toBe("The note vanished");
  const body = JSON.parse(
    String((vi.mocked(fetch).mock.calls[0] as [string, RequestInit])[1].body),
  );
  expect(body.words).toBe(
    "The note vanished\n\n(About: Couldn't save the note, ref req-77aa)",
  );
  expect(body.screenshot).toBeNull();
});

it("in the phone app, uses the phone's own picture of the screen, taken before the sheet opens", async () => {
  phone.app = true;
  const shot = new Blob([new Uint8Array([9, 9, 9])], { type: "image/jpeg" });
  askScreenshot.mockResolvedValue(shot);
  await act(async () => openBugReport());
  // The sheet waits for the phone's picture, so the picture is of the screen, not the sheet.
  expect(document.querySelector("dialog")?.open ?? false).toBe(false);
  await pause(400); // the phone answers and the sheet opens
  await pause(60); // the sheet shows the phone's picture
  expect(askScreenshot).toHaveBeenCalledTimes(1);
  expect(captureScreen).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")?.open).toBe(true);
  expect(document.querySelector("dialog img")?.getAttribute("alt")).toContain(
    "Picture of the screen",
  );
});

it("in the phone app, falls back to copying the page when the phone takes no picture", async () => {
  phone.app = true;
  askScreenshot.mockResolvedValue(null);
  captureScreen.mockResolvedValue(
    new Blob([new Uint8Array([1])], { type: "image/webp" }),
  );
  await act(async () => openBugReport());
  await pause(400); // the phone answers nothing and the sheet opens
  await pause(450); // the page is copied instead
  expect(askScreenshot).toHaveBeenCalledTimes(1);
  expect(captureScreen).toHaveBeenCalledTimes(1);
  expect(document.querySelector("dialog img")).not.toBeNull();
});

it("takes no picture of screens that can show calls or messages", async () => {
  expect(privateScreen("/analysis/calls/2b1f")).toBe(true);
  expect(privateScreen("/chats")).toBe(true);
  expect(privateScreen("/leads")).toBe(false);
  expect(privateScreen("/review")).toBe(true);
  expect(privateScreen("/review/figures")).toBe(true);
  expect(privateScreen("/review-fixture/bug-report")).toBe(false);
  window.history.replaceState(null, "", "/analysis/calls/2b1f");
  await act(async () => openBugReport());
  await pause(450);
  expect(captureScreen).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")?.textContent).toContain(
    "can show call details or messages",
  );
});
