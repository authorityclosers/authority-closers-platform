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
  list: async () => [],
  keepSending: (send: () => Promise<number>) => {
    void send();
    return () => {};
  },
}));

import { useRegisteredCommands } from "../ui/command-registry";
import { resetBackCloseForTests } from "../ui/back-close";
import {
  BugReportHost,
  KEY_SEND_STORE,
  forgetDraftForTests,
  privateScreen,
} from "./bug-report-sheet";
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
  forgetDraftForTests();
  window.localStorage.removeItem(KEY_SEND_STORE);
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
  // A fresh answer each time: the reporter reads its access too.
  const fetcher = vi.fn<typeof fetch>().mockImplementation(
    async () =>
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

  // The reporter also asks again whether the advanced one is open to you
  // when it opens (advanced-access.ts); one report went.
  const sent = fetcher.mock.calls.filter(
    ([path]) => path === "/v1/bug-reports",
  );
  expect(sent).toHaveLength(1);
  const [path, init] = sent[0] as [string, RequestInit];
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

it("keeps everything when sending fails and offers Try again in a corner card", async () => {
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
      action: expect.objectContaining({ label: "Try again" }),
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

it.each(["429", "network"] as const)(
  "retains words, picture, voice and command id after %s and retries the current draft",
  async (failure) => {
    captureScreen.mockResolvedValue(
      new Blob([new Uint8Array([1, 2, 3])], { type: "image/webp" }),
    );
    const mediaDevices = Object.getOwnPropertyDescriptor(
      navigator,
      "mediaDevices",
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({ getTracks: () => [{ stop: vi.fn() }] }),
      },
    });
    vi.stubGlobal(
      "MediaRecorder",
      class {
        static isTypeSupported = () => true;
        state = "inactive";
        mimeType = "audio/webm";
        ondataavailable: ((event: { data: Blob }) => void) | null = null;
        onstop: (() => void) | null = null;
        start() {
          this.state = "recording";
        }
        stop() {
          this.state = "inactive";
          this.ondataavailable?.({
            data: new Blob([new Uint8Array([4, 5, 6])], {
              type: this.mimeType,
            }),
          });
          this.onstop?.();
        }
      },
    );
    const fetcher = vi.fn<typeof fetch>();
    if (failure === "429") {
      fetcher.mockResolvedValueOnce(
        new Response(
          JSON.stringify({ detail: "That's a lot of reports in an hour." }),
          {
            status: 429,
            headers: {
              "content-type": "application/json",
              "Retry-After": "60",
            },
          },
        ),
      );
    } else {
      fetcher.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    }
    fetcher.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          bug_id: "b-retried",
          screenshot: "kept",
          voice: "kept",
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    try {
      await act(async () => openBugReport());
      await pause(450);
      await act(async () => type("The note vanished"));
      await act(async () => button("This stops my work").click());
      await act(async () => button("Add a voice note").click());
      await act(async () => button("Stop").click());
      expect(document.querySelector("dialog audio")).not.toBeNull();
      await submit();

      expect(document.querySelector("dialog")?.open).toBe(true);
      expect(document.querySelector("textarea")?.value).toBe(
        "The note vanished",
      );
      expect(document.querySelector("dialog img")).not.toBeNull();
      expect(document.querySelector("dialog audio")).not.toBeNull();
      expect(button("This stops my work").getAttribute("aria-pressed")).toBe(
        "true",
      );
      expect(button("Try again").disabled).toBe(false);
      const first = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
      expect(first.screenshot).toEqual({
        content_type: "image/webp",
        data: "AQID",
        source: "auto",
      });
      expect(first.voice).toEqual({
        content_type: "audio/webm",
        data: "BAUG",
        seconds: 1,
      });
      if (failure === "network") {
        // If local storage is unavailable, all attachments still stay in the sheet.
        expect(keep).toHaveBeenCalledWith(
          expect.objectContaining({ body: first }),
        );
      } else {
        expect(keep).not.toHaveBeenCalled();
      }

      await act(async () => type("The note vanished after saving"));
      if (failure === "429") {
        // The corner card must submit current state, not the failed send's closure.
        const notice = notify.mock.calls.find(
          ([item]) => item.id === "bug-report-failed",
        )![0];
        expect(notice.action.label).toBe("Try again");
        await act(async () => notice.action.run());
      } else {
        await act(async () => button("Try again").click());
      }
      await pause(20);
      expect(fetcher).toHaveBeenCalledTimes(2);
      const retried = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
      expect(retried).toEqual({
        ...first,
        words: "The note vanished after saving",
      });
      expect(document.querySelector("dialog")?.textContent).toContain(
        "Sent. We'll tell you when it's fixed.",
      );
    } finally {
      if (mediaDevices)
        Object.defineProperty(navigator, "mediaDevices", mediaDevices);
      else Reflect.deleteProperty(navigator, "mediaDevices");
    }
  },
);

// Bug 106 (29 Oct 2026): a cancelled demo came back unseen and new typing
// landed mid-text ("TutoriTutorial demo, please ignoreal demo, please ignore").
const DEMO = "Tutorial demo, please ignore";

const created = (body: Record<string, unknown>) =>
  vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status: 201,
      headers: { "content-type": "application/json" },
    }),
  );

it("a send while the picture is still being taken waits for it, and it goes along", async () => {
  // Persona QA, 31 Oct 2026: quick sends went without their picture, saying "Sent".
  let finish: (blob: Blob | null) => void = () => undefined;
  captureScreen.mockReturnValue(
    new Promise<Blob | null>((resolve) => {
      finish = resolve;
    }),
  );
  const fetcher = created({ bug_id: "b-3", screenshot: "kept" });
  vi.stubGlobal("fetch", fetcher);
  await opened();
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Taking a picture of this screen",
  );
  await act(async () => type("The list went blank after a filter."));
  await submit();
  expect(fetcher).not.toHaveBeenCalled();
  expect(button("Sending…").disabled).toBe(true);
  await act(async () =>
    finish(new Blob([new Uint8Array([7, 7])], { type: "image/webp" })),
  );
  await pause(20);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  expect(body.screenshot).toMatchObject({
    content_type: "image/webp",
    source: "auto",
  });
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Sent. We'll tell you when it's fixed.",
  );
});

it("says so when a report goes without its picture, and not when it was left out", async () => {
  captureScreen.mockResolvedValue(null);
  vi.stubGlobal("fetch", created({ bug_id: "b-4" }));
  await opened();
  await act(async () => type("Nothing happens on Save."));
  await submit();
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Sent without a picture.",
  );
  expect(document.querySelector("dialog")?.textContent).not.toContain(
    "Sent. We'll",
  );
  await act(async () => button("Done").click());
  await pause(600);

  // Left out on purpose: a plain "Sent".
  captureScreen.mockResolvedValue(
    new Blob([new Uint8Array([5])], { type: "image/webp" }),
  );
  vi.stubGlobal("fetch", created({ bug_id: "b-5" }));
  await opened();
  await act(async () => type("Nothing happens on Save, again."));
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>(
        'dialog button[aria-label="Leave the picture out"]',
      )!
      .click(),
  );
  await submit();
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Sent. We'll tell you when it's fixed.",
  );
});

async function opened() {
  await act(async () => openBugReport());
  await pause(450);
}

async function closedWithX() {
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>('dialog button[aria-label="Close"]')!
      .click(),
  );
  await pause(600);
  expect(document.querySelector("dialog")?.open).toBe(false);
}

/** The app frame mounts again (a reload of the shell, not of the page). */
async function remounted() {
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<BugReportHost />));
}

function expectNoDraft() {
  expect(document.querySelector("textarea")?.value).toBe("");
  expect(document.querySelector("dialog")?.textContent).not.toContain(
    "Draft restored",
  );
}

it("Cancel asks before discarding what was written, and Discard forgets it for good", async () => {
  captureScreen.mockResolvedValue(null);
  await opened();
  await act(async () => type(DEMO));
  await act(async () => button("Cancel").click());
  expect(document.querySelector("dialog")?.open).toBe(true);
  expect(document.querySelector("dialog footer")?.textContent).toContain(
    "Discard this report?",
  );
  await act(async () => button("Keep editing").click());
  expect(document.querySelector("textarea")?.value).toBe(DEMO);
  expect(button("Send report").disabled).toBe(false);

  await act(async () => button("Cancel").click());
  await act(async () => button("Discard").click());
  await pause(600);
  expect(document.querySelector("dialog")?.open).toBe(false);
  await opened();
  expectNoDraft();
  await closedWithX();
  await remounted();
  await opened();
  expectNoDraft();
});

it("Cancel with nothing written closes at once and forgets the chosen chip", async () => {
  captureScreen.mockResolvedValue(null);
  await opened();
  await act(async () => button("This stops my work").click());
  await act(async () => button("Cancel").click());
  await pause(600);
  expect(document.querySelector("dialog")?.open).toBe(false);
  await opened();
  expect(button("This stops my work").getAttribute("aria-pressed")).toBe(
    "false",
  );
});

it("a draft kept by closing comes back saying so, with the cursor at its end, and Clear empties it", async () => {
  captureScreen.mockResolvedValue(null);
  await opened();
  await act(async () => type(DEMO));
  await closedWithX();

  await opened();
  const area = document.querySelector("textarea")!;
  expect(area.value).toBe(DEMO);
  const restored = document.querySelector('dialog [role="status"]');
  expect(restored?.textContent).toContain("Draft restored");
  expect(document.activeElement).toBe(area);
  expect([area.selectionStart, area.selectionEnd]).toEqual([
    DEMO.length,
    DEMO.length,
  ]);
  // The first tap lands mid-text: the cursor still goes to the end.
  area.setSelectionRange(6, 6);
  await act(async () => area.click());
  expect([area.selectionStart, area.selectionEnd]).toEqual([
    DEMO.length,
    DEMO.length,
  ]);
  // After that, a tap puts the cursor where the person chose.
  area.setSelectionRange(6, 6);
  await act(async () => area.click());
  expect(area.selectionStart).toBe(6);

  await act(async () => button("Clear").click());
  expectNoDraft();
  expect(document.activeElement).toBe(document.querySelector("textarea"));
  await closedWithX();
  await opened();
  expectNoDraft();
});

it("a draft comes back after the app frame mounts again, saying so", async () => {
  captureScreen.mockResolvedValue(null);
  await opened();
  await act(async () => type(DEMO));
  await closedWithX();
  await remounted();
  await opened();
  expect(document.querySelector("textarea")?.value).toBe(DEMO);
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Draft restored",
  );
});

it("a sent report leaves no draft behind", async () => {
  captureScreen.mockResolvedValue(null);
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ bug_id: "b-2" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  await opened();
  await act(async () => type(DEMO));
  await submit();
  // No picture could be taken, and the sheet says so.
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Sent without a picture.",
  );
  await act(async () => button("Done").click());
  await pause(600);
  await opened();
  expectNoDraft();
  await closedWithX();
  await remounted();
  await opened();
  expectNoDraft();
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

it("opens over a menu even when the phone screenshot bridge never answers", async () => {
  phone.app = true;
  const menu = document.createElement("div");
  menu.setAttribute("role", "menu");
  menu.textContent = "Lead actions";
  document.body.append(menu);
  let finish: (value: Blob | null) => void = () => {};
  askScreenshot.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  captureScreen.mockResolvedValue(null);
  try {
    await act(async () => openBugReport());
    await pause(600);
    expect(document.querySelector("dialog[open]")?.textContent).toContain(
      "What went wrong?",
    );
    await act(async () => button("Cancel").click());
    await act(async () =>
      finish(new Blob(["late picture"], { type: "image/jpeg" })),
    );
    await pause(450);
    expect(document.querySelector("dialog[open]")).toBeNull();
    expect(menu.textContent).toBe("Lead actions");
  } finally {
    menu.remove();
  }
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

// Owner, 31 Oct 2026: "ctrl + enter and enter to submit ... with only one time
// asking confirmation ... once a tick box is ticked that never ask this again".
function answering() {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(
    async () =>
      new Response(JSON.stringify({ bug_id: "b-keys" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

/** Enter in the words; true when the keyboard keeps it (a new line). */
async function pressEnter(keys: KeyboardEventInit = {}): Promise<boolean> {
  let kept = true;
  await act(async () => {
    kept = document.querySelector("textarea")!.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Enter",
        bubbles: true,
        cancelable: true,
        ...keys,
      }),
    );
  });
  await pause(20);
  return kept;
}

function asked(): boolean {
  return (
    document
      .querySelector("dialog footer")
      ?.textContent?.includes("Send this report?") ?? false
  );
}

function tickBox(): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(
    'dialog footer input[type="checkbox"]',
  )!;
}

function sentWords(fetcher: ReturnType<typeof answering>, call: number) {
  return JSON.parse(String(fetcher.mock.calls[call][1]?.body)).words;
}

async function sendAsked() {
  await act(async () => button("Send").click());
  await pause(20);
}

async function doneAndOpenedAgain() {
  await act(async () => button("Done").click());
  await pause(600);
  await opened();
}

it("Enter asks once before sending, and asks again next time without the tick", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  await act(async () => type("Save does nothing"));
  expect(await pressEnter()).toBe(false);
  expect(asked()).toBe(true);
  expect(fetcher).not.toHaveBeenCalled();
  expect(document.activeElement).toBe(button("Send"));
  expect(tickBox().closest("label")?.textContent).toBe("Don't ask again");
  expect(tickBox().checked).toBe(false);

  await act(async () => button("Keep editing").click());
  expect(asked()).toBe(false);
  expect(document.activeElement).toBe(document.querySelector("textarea"));
  expect(fetcher).not.toHaveBeenCalled();

  await pressEnter();
  expect(asked()).toBe(true);
  await sendAsked();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(sentWords(fetcher, 0)).toBe("Save does nothing");
  // No picture could be taken here, and the sheet says so.
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Sent without a picture.",
  );
  expect(window.localStorage.getItem(KEY_SEND_STORE)).toBeNull();

  // Not ticked: the next keyboard send asks again.
  await doneAndOpenedAgain();
  await act(async () => type("Still broken"));
  await pressEnter({ ctrlKey: true });
  expect(asked()).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("after Don't ask again, Enter and Ctrl or Cmd+Enter send at once, also after the app mounts again", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  await act(async () => type("First report"));
  await pressEnter({ ctrlKey: true });
  expect(asked()).toBe(true);
  await act(async () => tickBox().click());
  expect(tickBox().checked).toBe(true);
  await sendAsked();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(window.localStorage.getItem(KEY_SEND_STORE)).not.toBeNull();

  await act(async () => button("Done").click());
  await pause(600);
  await remounted();
  await opened();
  await act(async () => type("Second report"));
  expect(await pressEnter()).toBe(false);
  expect(asked()).toBe(false);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(sentWords(fetcher, 1)).toBe("Second report");

  await doneAndOpenedAgain();
  await act(async () => type("Third report"));
  await pressEnter({ metaKey: true });
  expect(asked()).toBe(false);
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(sentWords(fetcher, 2)).toBe("Third report");
});

it("Keep editing with the tick still asks next time", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  await act(async () => type("Filter resets"));
  await pressEnter();
  await act(async () => tickBox().click());
  await act(async () => button("Keep editing").click());
  expect(window.localStorage.getItem(KEY_SEND_STORE)).toBeNull();
  await pressEnter();
  expect(asked()).toBe(true);
  expect(tickBox().checked).toBe(false);
  expect(fetcher).not.toHaveBeenCalled();
});

it("Shift+Enter is a new line, never a send", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  await act(async () => type("Steps:"));
  expect(await pressEnter({ shiftKey: true })).toBe(true);
  expect(asked()).toBe(false);
  expect(fetcher).not.toHaveBeenCalled();
  // The keyboard adds the line; Enter then sends the words as written.
  await act(async () => type("Steps:\n1. Open Leads"));
  await pressEnter();
  await sendAsked();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(sentWords(fetcher, 0)).toBe("Steps:\n1. Open Leads");
});

it("Enter that picks a word while typing Hindi or Marathi does not send", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  await act(async () => type("सेव नहीं हुआ"));
  expect(await pressEnter({ isComposing: true })).toBe(true);
  expect(await pressEnter({ ctrlKey: true, isComposing: true })).toBe(true);
  // Safari ends the word first, then sends Enter as key 229.
  expect(await pressEnter({ keyCode: 229 })).toBe(true);
  expect(asked()).toBe(false);
  expect(fetcher).not.toHaveBeenCalled();
});

it("never sends an empty report from the keyboard", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  await pressEnter();
  await pressEnter({ ctrlKey: true });
  await act(async () => type("   \n "));
  await pressEnter();
  await pressEnter({ ctrlKey: true });
  expect(asked()).toBe(false);
  expect(fetcher).not.toHaveBeenCalled();
  expect(button("Send report").disabled).toBe(true);
});

it("on a touch screen Enter stays a new line, and Ctrl+Enter still sends", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  const real = window.matchMedia.bind(window);
  vi.stubGlobal("matchMedia", (query: string) =>
    query === "(pointer: fine)"
      ? {
          matches: false,
          media: query,
          onchange: null,
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
          dispatchEvent: () => false,
        }
      : real(query),
  );
  await act(async () => type("Calls tab is empty"));
  expect(await pressEnter()).toBe(true);
  expect(asked()).toBe(false);
  expect(await pressEnter({ ctrlKey: true })).toBe(false);
  expect(asked()).toBe(true);
  await sendAsked();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("asks every time when this device can keep nothing", async () => {
  captureScreen.mockResolvedValue(null);
  const fetcher = answering();
  await opened();
  const blocked = () => {
    throw new DOMException("The operation is insecure.", "SecurityError");
  };
  vi.stubGlobal("localStorage", {
    getItem: blocked,
    setItem: blocked,
    removeItem: blocked,
    clear: blocked,
    key: blocked,
    length: 0,
  });
  await act(async () => type("Report one"));
  await pressEnter();
  await act(async () => tickBox().click());
  await sendAsked();
  expect(fetcher).toHaveBeenCalledTimes(1);

  await doneAndOpenedAgain();
  await act(async () => type("Report two"));
  await pressEnter();
  expect(asked()).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
