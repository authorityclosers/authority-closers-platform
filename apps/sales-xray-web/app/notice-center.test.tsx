import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import {
  dismissNotice,
  InCorner,
  NoticeCenter,
  NoticeDock,
  notify,
  useNoticeShown,
} from "./notice-center";
import { SCREEN_SETTLED_EVENT } from "./shell/screen-transition";
import { clearAlert, raiseAlert } from "./ui/alerts";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
beforeEach(async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<NoticeCenter />));
});
afterEach(async () => {
  await act(async () => {
    dismissNotice("fictional");
    root.unmount();
  });
  host.remove();
  window.sessionStorage.clear();
});
const close = () =>
  host.querySelector<HTMLButtonElement>('[aria-label="Dismiss"]')!;
it("retains the card until permanent dismissal is acknowledged", async () => {
  let resolve!: () => void;
  const onDismiss = vi.fn(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      }),
  );
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      onDismiss,
    }),
  );
  await act(async () => close().click());
  expect(onDismiss).toHaveBeenCalledTimes(1);
  expect(close().disabled).toBe(true);
  expect(host.textContent).toContain("Fictional update");
  await act(async () => resolve());
  expect(host.textContent).not.toContain("Fictional update");
});
it("dismisses from a worded button the same way as the X", async () => {
  const onDismiss = vi.fn(async () => {});
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      dismissLabel: "Later",
      onDismiss,
    }),
  );
  const later = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Later",
  )!;
  await act(async () => later.click());
  expect(onDismiss).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain("Fictional update");
});
it("keeps a failed acknowledgement actionable and retries", async () => {
  const onDismiss = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(undefined);
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      onDismiss,
    }),
  );
  await act(async () => close().click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Try again",
  );
  expect(close().disabled).toBe(false);
  await act(async () => close().click());
  expect(onDismiss).toHaveBeenCalledTimes(2);
  expect(host.textContent).not.toContain("Fictional update");
});
it("preserves ordinary notice actions and avoids removing a permanent card on navigation", async () => {
  const run = vi.fn();
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional update",
      timeout: 0,
      onDismiss: async () => {},
      action: { label: "Open", run },
    }),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(run).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Fictional update");
  await act(async () =>
    notify({
      id: "fictional",
      tone: "error",
      title: "Ordinary notice",
      action: { label: "Retry", run },
    }),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(host.textContent).not.toContain("Ordinary notice");
});
it("shows at most two cards, the older ones under +N more", async () => {
  // Owner via the orchestrator, 31 Oct 2026: at most two show, in one corner.
  const ids = ["first", "second", "third", "fourth"];
  try {
    for (const id of ids)
      await act(async () =>
        notify({ id, tone: "info", title: `Fictional ${id} update` }),
      );
    const titles = () =>
      ids.filter((id) => host.textContent?.includes(`Fictional ${id} update`));
    expect(titles()).toEqual(["third", "fourth"]);
    const more = () =>
      [...host.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
        /^\+\d+ more$|^Show fewer$/.test(button.textContent ?? ""),
      );
    expect(more()?.textContent).toBe("+2 more");
    await act(async () => more()!.click());
    expect(titles()).toEqual(ids);
    expect(more()?.textContent).toBe("Show fewer");
    await act(async () => more()!.click());
    expect(titles()).toEqual(["third", "fourth"]);
    await act(async () => {
      dismissNotice("first");
      dismissNotice("second");
    });
    expect(more()).toBeUndefined();
  } finally {
    await act(async () => ids.forEach((id) => dismissNotice(id)));
  }
});
it("folds a seen card to a one-line pill, and a tap opens it again", async () => {
  // Owner via the orchestrator, 31 Oct 2026: a corner card may never cover content.
  vi.useFakeTimers();
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "error",
        title: "Fictional sync paused",
        message: "Fictional steps to fix it.",
      }),
    );
    expect(host.textContent).toContain("Fictional steps to fix it.");
    await act(async () => vi.advanceTimersByTime(8000));
    const pill = () =>
      host.querySelector<HTMLButtonElement>('button[aria-expanded="false"]');
    expect(pill()?.textContent).toBe("Fictional sync paused");
    expect(host.textContent).not.toContain("Fictional steps to fix it.");
    await act(async () => pill()!.click());
    expect(host.textContent).toContain("Fictional steps to fix it.");
    // Opened by a tap, it holds focus, so it stays open while it's read.
    expect(document.activeElement?.getAttribute("role")).toBe("alert");
    await act(async () => vi.advanceTimersByTime(8000));
    expect(host.textContent).toContain("Fictional steps to fix it.");
  } finally {
    vi.useRealTimers();
  }
});
it("brings a card seen this visit back folded, until it is closed", async () => {
  vi.useFakeTimers();
  const card = {
    id: "fictional",
    tone: "info",
    title: "Fictional calls have no recording",
    message: "Fictional steps.",
    onDismiss: async () => {},
  } as const;
  try {
    await act(async () => notify(card));
    await act(async () => vi.advanceTimersByTime(8000));
    // Away and back (Home to Leads and back): it returns as the pill.
    await act(async () => dismissNotice("fictional"));
    await act(async () => notify(card));
    expect(host.textContent).not.toContain("Fictional steps.");
    // A new title is new news: it opens.
    await act(async () =>
      notify({ ...card, title: "More fictional calls have no recording" }),
    );
    expect(host.textContent).toContain("Fictional steps.");
    await act(async () => vi.advanceTimersByTime(8000));
    await act(async () => close().click());
    expect(host.textContent).not.toContain("recording");
    // Closed, it is forgotten: the next one opens.
    await act(async () =>
      notify({ ...card, title: "More fictional calls have no recording" }),
    );
    expect(host.textContent).toContain("Fictional steps.");
    // Its owner may say it was seen already (once a day, say): it arrives folded.
    await act(async () => dismissNotice("fictional"));
    await act(async () =>
      notify({ ...card, title: "Fresh fictional news", folded: true }),
    );
    expect(host.textContent).toContain("Fresh fictional news");
    expect(host.textContent).not.toContain("Fictional steps.");
  } finally {
    vi.useRealTimers();
  }
});
it("shows a slim card as the pill, whose tap opens the rest", async () => {
  // The recording card's slim line is the stack's pill, like every card
  // (orchestrator, 31 Oct 2026: the fold comes from the stack, for all alike).
  const run = vi.fn();
  await act(async () =>
    notify({
      id: "fictional",
      tone: "info",
      title: "Fictional line",
      message: "Fictional rest.",
      action: { label: "Details", run },
      slim: true,
      onDismiss: async () => {},
    }),
  );
  const pill = host.querySelector<HTMLButtonElement>(
    'button[aria-expanded="false"]',
  )!;
  expect(pill.textContent).toBe("Fictional line");
  expect(host.textContent).not.toContain("Fictional rest.");
  await act(async () => pill.click());
  expect(host.textContent).toContain("Fictional rest.");
  expect(run).not.toHaveBeenCalled();
  await act(async () => close().click());
  expect(host.textContent).not.toContain("Fictional line");
});
it("shows a work alert as a corner card that folds like every card", async () => {
  // One notification system (owner via the orchestrator, 31 Oct 2026): no
  // banner over the top of the page; work rides at the top of the stack.
  vi.useFakeTimers();
  try {
    await act(async () =>
      raiseAlert({
        id: "fictional-work",
        level: "normal",
        emphasis: "urgent",
        title: "Fictional follow-up in 40 min",
        message: "Fictional steps.",
        action: { label: "Open", href: "/leads" },
        timeout: 600_000,
      }),
    );
    const card = host.querySelector('[aria-live="polite"] [role="status"]');
    expect(card?.getAttribute("data-tone")).toBe("due");
    expect(card?.querySelector('a[href="/leads"]')?.textContent).toBe("Open");
    await act(async () => vi.advanceTimersByTime(8000));
    expect(host.textContent).not.toContain("Fictional steps.");
    expect(
      host.querySelector('button[aria-expanded="false"]')?.textContent,
    ).toBe("Fictional follow-up in 40 min");
    await act(async () => close().click());
    expect(host.textContent).not.toContain("Fictional follow-up");
  } finally {
    await act(async () => clearAlert("fictional-work"));
    vi.useRealTimers();
  }
});
it("puts a new card at the top, so the cards already there stay put", async () => {
  // Orchestrator, 1 Nov 2026: a card joining below lifted the others, a
  // layout shift. Older cards wait under "+N more", below the newest.
  const ids = ["older", "newer", "newest"];
  try {
    for (const id of ids)
      await act(async () =>
        notify({
          id,
          tone: "info",
          title: `Fictional ${id} card`,
          timeout: 0,
        }),
      );
    const order = () =>
      [...host.querySelectorAll('[aria-live="polite"] > *')].map(
        (node) => node.textContent ?? "",
      );
    expect(order()[0]).toContain("Fictional newest card");
    expect(order()[1]).toContain("Fictional newer card");
    expect(order()[2]).toBe("+1 more");
  } finally {
    await act(async () => ids.forEach((id) => dismissNotice(id)));
  }
});

it("lifts each card into its row by translate, so one coming or going moves no other card", async () => {
  // QA robot 69792ae8 (Home at 363, the Home studio's diagnosis, 8 Nov 2026):
  // "Couldn't load" coming and going shifted the stack's cards, 0.12 in all.
  // Each card keeps its place in the layout, the stack's base line; only its
  // translate lifts it, and a card that comes or goes changes no other's.
  const tall = vi
    .spyOn(HTMLElement.prototype, "offsetHeight", "get")
    .mockImplementation(function (this: HTMLElement) {
      const inStack =
        this.parentElement?.getAttribute("aria-live") === "polite";
      return inStack && this.textContent ? 64 : 0;
    });
  const card = (title: string) =>
    [...host.querySelectorAll<HTMLElement>('[aria-live="polite"] > *')].find(
      (node) => node.textContent?.includes(title),
    );
  try {
    await act(async () =>
      notify({
        id: "steady",
        tone: "info",
        title: "Fictional steady card",
        timeout: 0,
      }),
    );
    expect(card("Fictional steady card")?.style.translate).toBe("0 -64px");
    await act(async () =>
      notify({
        id: "glitch",
        tone: "error",
        title: "Fictional couldn't load",
        timeout: 0,
      }),
    );
    // The new card above it, 10 px apart; the steady card holds its row.
    expect(card("Fictional couldn't load")?.style.translate).toBe("0 -138px");
    expect(card("Fictional steady card")?.style.translate).toBe("0 -64px");
    await act(async () => dismissNotice("glitch"));
    expect(card("Fictional couldn't load")).toBeUndefined();
    expect(card("Fictional steady card")?.style.translate).toBe("0 -64px");
  } finally {
    tall.mockRestore();
    await act(async () =>
      ["steady", "glitch"].forEach((id) => dismissNotice(id)),
    );
  }
});

// Competitor teardown 12 (1 Nov 2026): a new enquiry is a one-line pill with
// its Call now in it, never a sheet over the list; the X is "Later".
it("keeps a new enquiry's Call now in its one-line pill", async () => {
  const call = vi.fn();
  const later = vi.fn(async () => {});
  await act(async () =>
    notify({
      id: "fictional",
      tone: "lead",
      title: "New enquiry · Asha Fictional · Meta",
      action: { label: "Call now", run: call, icon: "none" },
      dismissLabel: "Later",
      onDismiss: later,
      pillAction: true,
      folded: true,
      timeout: 0,
    }),
  );
  const pill = host.querySelector<HTMLButtonElement>(
    '[aria-expanded="false"]',
  )!;
  expect(pill.textContent).toBe("New enquiry · Asha Fictional · Meta");
  const now = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Call now",
  )!;
  await act(async () => now.click());
  expect(call).toHaveBeenCalledTimes(1);
  // It stays until the page or the person closes it.
  expect(host.textContent).toContain("New enquiry · Asha Fictional");
  await act(async () => close().click());
  expect(later).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain("New enquiry");
});
it("on a phone page with a dock, new leads and work are one line in it; problems keep the corner", async () => {
  // Competitor teardown 12; the orchestrator, 1 Nov 2026: "Varun Chauhan is
  // your lead now" covered the second row's Open on Follow-ups at 360 px.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const page = document.createElement("div");
  document.body.append(page);
  const pageRoot = createRoot(page);
  try {
    await act(async () => pageRoot.render(<NoticeDock />));
    await act(async () => {
      notify({
        id: "fictional",
        tone: "lead",
        title: "New enquiry · Asha Fictional · Meta",
        action: { label: "Call now", run: () => {}, icon: "none" },
        pillAction: true,
        folded: true,
        timeout: 0,
      });
      notify({
        id: "fictional-problem",
        tone: "error",
        title: "Leads didn't load",
      });
      raiseAlert({
        id: "fictional-work",
        level: "normal",
        title: "Varun Fictional is your lead now",
        message: "New from your website form.",
        action: { label: "Open lead", href: "/leads" },
        timeout: 600_000,
      });
    });
    const docked = page.querySelector("[data-notice-dock]")!;
    // One line each, with its action, and the work alert's words only on a tap.
    expect(docked.textContent).toContain("New enquiry · Asha Fictional · Meta");
    expect(docked.textContent).toContain("Call now");
    expect(docked.textContent).toContain("Varun Fictional is your lead now");
    expect(docked.textContent).toContain("Open lead");
    expect(docked.textContent).not.toContain("New from your website form.");
    expect(docked.textContent).not.toContain("Leads didn't load");
    // The corner keeps the app's problem, and only that.
    expect(host.textContent).toContain("Leads didn't load");
    expect(host.textContent).not.toContain("Asha Fictional");
    expect(host.textContent).not.toContain("Varun Fictional");
    // Without the dock (a computer, or another page) they go back to the corner.
    await act(async () => pageRoot.unmount());
    expect(host.textContent).toContain("New enquiry · Asha Fictional · Meta");
    expect(host.textContent).toContain("Varun Fictional is your lead now");
  } finally {
    await act(async () => {
      clearAlert("fictional-work");
      dismissNotice("fictional-problem");
    });
    page.remove();
    vi.unstubAllGlobals();
  }
});
it("keeps a line in the dock until it is used or closed, so the page never jumps", async () => {
  // QA robot a4e9034c, 1 Nov 2026: "Fictional is your lead now" went by itself
  // after 8 s and lifted Leads by its height, a layout shift of 0.1 per load.
  vi.useFakeTimers();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const page = document.createElement("div");
  document.body.append(page);
  const pageRoot = createRoot(page);
  try {
    await act(async () => pageRoot.render(<NoticeDock />));
    await act(async () =>
      raiseAlert({
        id: "fictional-work",
        level: "normal",
        title: "Varun Fictional is your lead now",
        action: { label: "Open lead", href: "/leads" },
        timeout: 8_000,
      }),
    );
    const docked = page.querySelector("[data-notice-dock]")!;
    expect(docked.textContent).toContain("Varun Fictional is your lead now");
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(docked.textContent).toContain("Varun Fictional is your lead now");
    // Its X still takes it away.
    await act(async () =>
      docked
        .querySelector<HTMLButtonElement>('[aria-label="Dismiss"]')!
        .click(),
    );
    expect(docked.textContent).not.toContain("Varun Fictional");
    // In the corner (a computer, or another page) it still goes by itself.
    await act(async () => pageRoot.unmount());
    await act(async () =>
      raiseAlert({
        id: "fictional-work",
        level: "normal",
        title: "Varun Fictional is your lead now",
        timeout: 8_000,
      }),
    );
    expect(host.textContent).toContain("Varun Fictional is your lead now");
    await act(async () => vi.advanceTimersByTime(10_000));
    expect(host.textContent).not.toContain("Varun Fictional");
  } finally {
    await act(async () => clearAlert("fictional-work"));
    page.remove();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

it("puts a line that arrives over a drawn page in the corner, never pushing the page down", async () => {
  // QA robot 4b12c389, 3 Nov 2026: "QA Robot 2 is your lead now" came 4 to 8 s
  // into Leads Analytics and dropped it 52 px. Over a loading outline (Leads
  // raises its lines with the answer that draws the page) a line still docks,
  // and a line waiting when the dock is drawn docks from its first frame.
  vi.useFakeTimers();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const drawn = document.createElement("section");
  drawn.textContent = "Leads Analytics";
  const outline = document.createElement("div");
  outline.setAttribute("aria-busy", "true");
  document.body.append(drawn, outline);
  let under: Element = drawn;
  Object.defineProperty(document, "elementFromPoint", {
    configurable: true,
    value: () => under,
  });
  const page = document.createElement("div");
  document.body.append(page);
  const pageRoot = createRoot(page);
  const line = (id: string) =>
    raiseAlert({
      id,
      level: "normal",
      title: "QA Fictional is your lead now",
      action: { label: "Open lead", href: "/leads" },
    });
  const dock = () => page.querySelector<HTMLElement>("[data-notice-dock]")!;
  try {
    await act(async () => pageRoot.render(<NoticeDock />));
    // Over the drawn page: the corner, the page stays put.
    await act(async () => line("fictional-late"));
    expect(dock().textContent).toBe("");
    expect(host.textContent).toContain("QA Fictional is your lead now");
    // In the corner it goes by itself like every card ("Yes, let it fade",
    // the owner, 8 Nov 2026); Open lead works while it shows.
    expect(
      [...host.querySelectorAll("a, button")].some((node) =>
        /Open lead/.test(node.textContent ?? ""),
      ),
    ).toBe(true);
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(host.textContent).not.toContain("QA Fictional is your lead now");
    await act(async () => clearAlert("fictional-late"));
    // Over a loading outline: it lands with the page, in the dock.
    under = outline;
    await act(async () => line("fictional-with-page"));
    expect(dock().textContent).toContain("QA Fictional is your lead now");
    await act(async () => clearAlert("fictional-with-page"));
    // Waiting when the dock is drawn: the dock, even over a drawn page.
    await act(async () => pageRoot.unmount());
    under = drawn;
    await act(async () => line("fictional-waiting"));
    const next = createRoot(page);
    await act(async () => next.render(<NoticeDock />));
    expect(dock().textContent).toContain("QA Fictional is your lead now");
    await act(async () => next.unmount());
  } finally {
    await act(async () => clearAlert("fictional-waiting"));
    delete (document as { elementFromPoint?: unknown }).elementFromPoint;
    drawn.remove();
    outline.remove();
    page.remove();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

it("docks a line that comes while the next page is still its outline", async () => {
  // QA robot, 9 Nov 2026: Leads tapped from Home, "… is your lead now" was
  // drawn under the outline at the foot of the screen, then sat at the top.
  // The dock is above the outline now; what lies under it is the outline's
  // own top, not marked busy, and the page beside it is standing in.
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const top = document.createElement("header");
  top.textContent = "Leads";
  document.body.append(top);
  Object.defineProperty(document, "elementFromPoint", {
    configurable: true,
    value: () => top,
  });
  const page = document.createElement("div");
  document.body.append(page);
  const pageRoot = createRoot(page);
  const dock = () => page.querySelector<HTMLElement>("[data-notice-dock]")!;
  try {
    await act(async () =>
      pageRoot.render(
        <>
          <NoticeDock />
          <div data-page-slot="" data-standing-in="" />
        </>,
      ),
    );
    await act(async () =>
      raiseAlert({
        id: "fictional-coming",
        level: "normal",
        title: "QA Fictional is your lead now",
        action: { label: "Open lead", href: "/leads" },
      }),
    );
    expect(dock().textContent).toContain("QA Fictional is your lead now");
    await act(async () => pageRoot.unmount());
  } finally {
    await act(async () => clearAlert("fictional-coming"));
    delete (document as { elementFromPoint?: unknown }).elementFromPoint;
    top.remove();
    page.remove();
    vi.unstubAllGlobals();
  }
});

it("keeps the dock's room while a sheet holds its lines, so the page never jumps", async () => {
  // QA robot 95abddab and 77641e07, 3 Nov 2026: "… is your lead now" left the
  // page's dock for the lead sheet, and the page rose 52 px, then dropped back
  // as the sheet closed.
  vi.useFakeTimers();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  const measure = vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: Element) {
      const height = this.parentElement?.hasAttribute("data-notice-dock")
        ? 42
        : 0;
      return rect({ left: 0, top: 0, right: 360, bottom: height });
    });
  const matches = Element.prototype.matches;
  const modal = vi
    .spyOn(Element.prototype, "matches")
    .mockImplementation(function (this: Element, selector: string) {
      if (selector === ":modal")
        return (
          this.hasAttribute("data-fixture-sheet") && this.hasAttribute("open")
        );
      return matches.call(this, selector);
    });
  Object.defineProperty(document, "elementsFromPoint", {
    configurable: true,
    value: () => [],
  });
  const page = document.createElement("div");
  document.body.append(page);
  const pageRoot = createRoot(page);
  const sheet = document.createElement("dialog");
  sheet.setAttribute("data-fixture-sheet", "");
  document.body.append(sheet);
  try {
    await act(async () => pageRoot.render(<NoticeDock />));
    await act(async () =>
      notify({
        id: "fictional",
        tone: "lead",
        title: "Fictional Asha is your lead now",
      }),
    );
    const dock = page.querySelector<HTMLElement>("[data-notice-dock]")!;
    expect(dock.textContent).toContain("Fictional Asha is your lead now");
    expect(dock.hasAttribute("data-held")).toBe(false);
    // A sheet opens: the line goes with it, and the dock keeps its room.
    await act(async () => sheet.setAttribute("open", ""));
    await frames();
    expect(dock.textContent).toBe("");
    expect(dock.hasAttribute("data-held")).toBe(true);
    expect(dock.style.getPropertyValue("--sx-dock-held")).toBe("42px");
    // It closes: the line is back in its room, and nothing is held.
    await act(async () => sheet.removeAttribute("open"));
    await frames();
    expect(dock.textContent).toContain("Fictional Asha is your lead now");
    expect(dock.hasAttribute("data-held")).toBe(false);
    expect(dock.style.getPropertyValue("--sx-dock-held")).toBe("");
  } finally {
    await act(async () => pageRoot.unmount());
    sheet.remove();
    page.remove();
    measure.mockRestore();
    modal.mockRestore();
    delete (document as { elementsFromPoint?: unknown }).elementsFromPoint;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});
it("lifts over a bar that reaches its place as the screen's motion ends", async () => {
  // Redmi QA on the owner's production build, 13 Nov 2026: "Finish setting
  // up", raised on Home, sat over Leads' Call Next Lead. Leads slid in; while
  // it moved, its fixed Call band wasn't under the corner yet, and its arrival
  // moved no element, so nothing measured the stack again.
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  const band = document.createElement("div");
  band.style.position = "fixed";
  band.style.bottom = "66px";
  const call = document.createElement("button");
  call.type = "button";
  call.textContent = "Call Next Lead";
  band.append(call);
  document.body.append(band);
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "info",
        title: "Fictional finish setting up",
        timeout: 0,
      }),
    );
    await frames();
    // The screen still moving: the band isn't under the corner yet.
    expect(liftOf()).toBe("");
    // Its motion ends with the band in place, 138 px up. Nothing in the page
    // changed, yet the stack measures again and stands 8 px above it.
    boxes.set(band, {
      left: 0,
      top: view() - 138,
      right: 384,
      bottom: view() - 66,
    });
    boxes.set(call, {
      left: 16,
      top: view() - 130,
      right: 368,
      bottom: view() - 74,
    });
    await act(async () =>
      window.dispatchEvent(new Event(SCREEN_SETTLED_EVENT)),
    );
    await frames();
    expect(liftOf()).toBe("146px");
  } finally {
    restore();
    band.remove();
    vi.useRealTimers();
  }
});

it("keeps a short-lived card's Undo in its folded pill", async () => {
  // Phone personas ph2-36 (1 Nov 2026): the after-call card folded, its Undo
  // vanished, and a second tap opened the lead underneath.
  vi.useFakeTimers();
  try {
    const undo = vi.fn();
    await act(async () =>
      notify({
        id: "fictional",
        tone: "success",
        title: "Moved to Interested",
        message: "Asha Fictional",
        action: { label: "Undo", run: undo, icon: "none" },
        timeout: 10_000,
      }),
    );
    await act(async () => vi.advanceTimersByTime(8000));
    expect(host.textContent).not.toContain("Asha Fictional");
    expect(
      host.querySelector('button[aria-expanded="false"]')?.textContent,
    ).toBe("Moved to Interested");
    const back = [...host.querySelectorAll("button")].find(
      (button) => button.textContent === "Undo",
    );
    expect(back).toBeDefined();
    await act(async () => back!.click());
    expect(undo).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});
it("puts a page's own card in the corner stack, beside the cards notify() raises", async () => {
  // The test robot, a5ceb915, 60244251 and 7ead7db2 (1 Nov 2026): New
  // analysis's error card floated on its own, so the first-call guide sat on
  // its buttons and the card sat on Report a problem.
  const page = document.createElement("div");
  document.body.append(page);
  const pageRoot = createRoot(page);
  try {
    await act(async () => {
      notify({
        id: "fictional-problem",
        tone: "error",
        title: "Leads didn't load",
      });
      pageRoot.render(
        <InCorner>
          <div role="alert">That didn&apos;t go through</div>
        </InCorner>,
      );
    });
    const own = host.querySelector("[data-corner-own]")!;
    expect(own.textContent).toBe("That didn't go through");
    expect(own.parentElement!.textContent).toContain("Leads didn't load");
    expect(page.textContent).toBe("");
    // Without a notice centre it stays where the page put it.
    await act(async () => root.unmount());
    expect(page.textContent).toBe("That didn't go through");
  } finally {
    await act(async () => {
      pageRoot.unmount();
      dismissNotice("fictional-problem");
    });
    page.remove();
    root = createRoot(host);
  }
});

// ----- bars under the corner (orchestrator, 3 Nov 2026, for v1.37) -----------------------

type Box = { left: number; top: number; right: number; bottom: number };
const rect = (box: Box) =>
  ({
    ...box,
    x: box.left,
    y: box.top,
    width: box.right - box.left,
    height: box.bottom - box.top,
    toJSON: () => box,
  }) as unknown as DOMRect;
const view = () => window.innerHeight;
const cornerStack = () =>
  document.querySelector<HTMLElement>("[data-corner-own]")?.parentElement ??
  null;
const liftOf = () =>
  cornerStack()?.style.getPropertyValue("--sx-stack-lift") ?? "";
const frames = () => act(async () => vi.advanceTimersByTime(40));

/**
 * A phone's window in fictional numbers: the corner stack at its own place
 * sits 86 px up and 12 px from the sides, 64 px tall with a card open and
 * 40 px as a pill; every other box is the test's. A hit test finds what is
 * drawn at a point, the stack first, and the sheet under test is the modal.
 */
function phone(boxes: Map<Element, Box>) {
  const measure = vi
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: Element) {
      const stack = cornerStack();
      if (this !== stack || !stack) return rect(boxes.get(this) ?? ZERO);
      const lift =
        parseFloat(stack.style.getPropertyValue("--sx-stack-lift")) || 0;
      const bottom = view() - Math.max(86, lift);
      const height = stack.querySelector('[role="status"], [role="alert"]')
        ? 64
        : stack.textContent
          ? 40
          : 0;
      return rect({ left: 12, top: bottom - height, right: 372, bottom });
    });
  const depth = (node: Element) => {
    let count = 0;
    for (let at: Element | null = node; at; at = at.parentElement) count += 1;
    return count;
  };
  const drawn = (node: Element, x: number, y: number) => {
    const box = node.getBoundingClientRect();
    return (
      box.height > 0 &&
      x >= box.left &&
      x < box.right &&
      y >= box.top &&
      y < box.bottom
    );
  };
  Object.defineProperty(document, "elementsFromPoint", {
    configurable: true,
    value: (x: number, y: number) => {
      const stack = cornerStack();
      const under = [...boxes.keys()]
        .filter((node) => node.isConnected && drawn(node, x, y))
        .sort((a, b) => depth(b) - depth(a));
      return stack && drawn(stack, x, y) ? [stack, ...under] : under;
    },
  });
  const matches = Element.prototype.matches;
  const modal = vi
    .spyOn(Element.prototype, "matches")
    .mockImplementation(function (this: Element, selector: string) {
      if (selector === ":modal")
        return (
          this.hasAttribute("data-fixture-sheet") && this.hasAttribute("open")
        );
      return matches.call(this, selector);
    });
  return () => {
    measure.mockRestore();
    modal.mockRestore();
    delete (document as { elementsFromPoint?: unknown }).elementsFromPoint;
    document.documentElement.style.removeProperty("--sx-corner-h");
  };
}
const ZERO: Box = { left: 0, top: 0, right: 0, bottom: 0 };

/**
 * The lead sheet on a phone, in fictional sizes: a kit sheet whose panel ends
 * 86 px up, above the tab bar, with its body (data-sheet-body).
 */
function leadSheet(boxes: Map<Element, Box>) {
  const sheet = document.createElement("dialog");
  sheet.setAttribute("data-fixture-sheet", "");
  const panel = document.createElement("div");
  const body = document.createElement("div");
  body.setAttribute("data-sheet-body", "");
  panel.append(body);
  sheet.append(panel);
  document.body.append(sheet);
  boxes.set(body, { left: 0, top: 60, right: 384, bottom: view() - 86 });
  return { sheet, panel, body };
}

/**
 * The after-call question's Save & Close, in a row held at the body's bottom
 * (leads.module.css, .outcome .saveRow): 72 px tall, its top 158 px up.
 */
function saveBar(boxes: Map<Element, Box>, body: HTMLElement) {
  const row = document.createElement("div");
  row.style.position = "sticky";
  row.style.bottom = "0";
  const save = document.createElement("button");
  save.type = "button";
  save.textContent = "Save & Close";
  row.append(save);
  body.append(row);
  boxes.set(row, {
    left: 0,
    top: view() - 158,
    right: 384,
    bottom: view() - 86,
  });
  boxes.set(save, {
    left: 16,
    top: view() - 148,
    right: 368,
    bottom: view() - 96,
  });
}

it("lifts a card above the lead sheet's Save & Close bar and folds it to its pill", async () => {
  // Orchestrator, 3 Nov 2026: "… is your lead now" covered the lead sheet's
  // Save bar. A corner card never covers a control (owner's rule).
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  const { sheet, body } = leadSheet(boxes);
  saveBar(boxes, body);
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "lead",
        title: "Fictional Asha is your lead now",
      }),
    );
    await act(async () => sheet.setAttribute("open", ""));
    await frames();
    expect(cornerStack()?.parentElement).toBe(sheet);
    // 8 px above the bar's measured top, 158 px up.
    expect(liftOf()).toBe("166px");
    expect(
      sheet.querySelector('button[aria-expanded="false"]')?.textContent,
    ).toBe("Fictional Asha is your lead now");
    expect(sheet.querySelector('[role="status"]')).toBeNull();
    // A tap opens the pill, and the card stays open above Save & Close.
    await act(async () =>
      sheet
        .querySelector<HTMLButtonElement>('button[aria-expanded="false"]')!
        .click(),
    );
    await frames();
    expect(sheet.querySelector('[role="status"]')).not.toBeNull();
    expect(liftOf()).toBe("166px");
    // Scrolled on, the row moves up with the end of its question: the stack
    // goes back to its place.
    const row = sheet.querySelector("[data-sheet-body] > div")!;
    boxes.set(row, {
      left: 0,
      top: view() - 330,
      right: 384,
      bottom: view() - 258,
    });
    boxes.set(row.firstElementChild!, {
      left: 16,
      top: view() - 320,
      right: 368,
      bottom: view() - 268,
    });
    await act(async () => body.dispatchEvent(new Event("scroll")));
    await frames();
    expect(liftOf()).toBe("");
  } finally {
    await act(async () => sheet.remove());
    await frames();
    restore();
    vi.useRealTimers();
  }
});

it("shows one card in an open sheet, the newest; the rest come back when it closes", async () => {
  // Orchestrator, 8 Nov 2026: at 363 "… is your lead now", "Saved on this
  // phone" and "1 change not sent yet" piled over the lead sheet's actions.
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  const { sheet } = leadSheet(boxes);
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "lead",
        title: "Fictional Asha is your lead now",
      }),
    );
    await act(async () =>
      notify({ id: "fictional-older", tone: "info", title: "Fictional older" }),
    );
    await act(async () =>
      notify({
        id: "fictional-newest",
        tone: "info",
        title: "1 change not sent yet",
      }),
    );
    await act(async () => sheet.setAttribute("open", ""));
    await frames();
    expect(cornerStack()?.parentElement).toBe(sheet);
    expect(sheet.textContent).toContain("1 change not sent yet");
    expect(sheet.textContent).not.toContain("Fictional older");
    expect(sheet.textContent).not.toContain("is your lead now");
    expect(sheet.textContent).not.toContain("more");
    // Closed, the page's stack holds them again: the newest two, one under +1.
    await act(async () => sheet.removeAttribute("open"));
    await frames();
    const page = cornerStack()?.textContent ?? "";
    expect(cornerStack()?.parentElement).not.toBe(sheet);
    expect(page).toContain("1 change not sent yet");
    expect(page).toContain("Fictional older");
    expect(page).toContain("+1 more");
  } finally {
    await act(async () => {
      dismissNotice("fictional-older");
      dismissNotice("fictional-newest");
    });
    await act(async () => sheet.remove());
    await frames();
    restore();
    vi.useRealTimers();
  }
});

it("keeps a card above the lead's Call bar, then above Save & Close once Log a call opens", async () => {
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  const { sheet, panel, body } = leadSheet(boxes);
  // The lead's Call bar, in the kit sheet's footer (data-sheet-footer).
  const footer = document.createElement("footer");
  footer.setAttribute("data-sheet-footer", "");
  const call = document.createElement("button");
  call.type = "button";
  call.textContent = "Call Asha";
  footer.append(call);
  panel.append(footer);
  boxes.set(body, { left: 0, top: 60, right: 384, bottom: view() - 154 });
  boxes.set(footer, {
    left: 0,
    top: view() - 154,
    right: 384,
    bottom: view() - 86,
  });
  boxes.set(call, {
    left: 16,
    top: view() - 142,
    right: 368,
    bottom: view() - 98,
  });
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "error",
        title: "Fictional sync paused",
        message: "Fictional steps to fix it.",
      }),
    );
    await act(async () => sheet.setAttribute("open", ""));
    await frames();
    expect(liftOf()).toBe("162px");
    expect(
      sheet.querySelector('button[aria-expanded="false"]')?.textContent,
    ).toBe("Fictional sync paused");
    // Log a call: the question opens, the footer goes and Save & Close is
    // held at the body's bottom instead.
    await act(async () => {
      footer.remove();
      boxes.set(body, { left: 0, top: 60, right: 384, bottom: view() - 86 });
      saveBar(boxes, body);
    });
    await frames();
    expect(liftOf()).toBe("166px");
    expect(sheet.textContent).not.toContain("Fictional steps to fix it.");
  } finally {
    await act(async () => sheet.remove());
    await frames();
    restore();
    vi.useRealTimers();
  }
});

it("stays at its place over the tab bar, and rises by the bar's measured top when large text makes it taller", async () => {
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  // The phone's tab bar: fixed 8 px up, 70 px tall at the usual text size.
  const tabs = document.createElement("nav");
  tabs.style.position = "fixed";
  tabs.style.bottom = "8px";
  const leads = document.createElement("a");
  leads.href = "/leads";
  leads.textContent = "Leads";
  tabs.append(leads);
  document.body.append(tabs);
  const tall = (height: number) => {
    boxes.set(tabs, {
      left: 12,
      top: view() - 8 - height,
      right: 372,
      bottom: view() - 8,
    });
    boxes.set(leads, {
      left: 12,
      top: view() - 8 - height,
      right: 132,
      bottom: view() - 8,
    });
  };
  tall(70);
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "error",
        title: "Fictional sync paused",
        message: "Fictional steps to fix it.",
      }),
    );
    await frames();
    expect(liftOf()).toBe("");
    expect(host.textContent).toContain("Fictional steps to fix it.");
    tall(104);
    await act(async () => window.dispatchEvent(new Event("resize")));
    // 8 px above the bar's measured top, 112 px up.
    expect(liftOf()).toBe("120px");
    expect(
      host.querySelector('button[aria-expanded="false"]')?.textContent,
    ).toBe("Fictional sync paused");
  } finally {
    restore();
    tabs.remove();
    vi.useRealTimers();
  }
});

it("never takes the first-call guide for a bar: the guide rises above the stack, the stack stays", async () => {
  // Seller Home, robot 8c687b6a (3 Nov 2026): on New analysis at 1440 the
  // stack lifted over the guide, the guide over the stack, and back again.
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  const guide = document.createElement("div");
  guide.setAttribute("data-guide-card", "");
  guide.style.position = "fixed";
  guide.style.bottom = "24px";
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "Next";
  guide.append(next);
  document.body.append(guide);
  for (const node of [guide, next])
    boxes.set(node, {
      left: 12,
      top: view() - 304,
      right: 372,
      bottom: view() - 24,
    });
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "error",
        title: "Fictional minutes used up",
        message: "Fictional steps to fix it.",
      }),
    );
    await frames();
    expect(liftOf()).toBe("");
  } finally {
    restore();
    guide.remove();
    vi.useRealTimers();
  }
});

it("on a page, folds a card that would cover a bar to its pill; opened by a tap it rises above the bar", async () => {
  // Dev, 1440 px, 3 Nov 2026: the lead beside the list ends above the corner,
  // so its Call bar is under a card but not under the pill.
  vi.useFakeTimers();
  const boxes = new Map<Element, Box>();
  const restore = phone(boxes);
  const dock = document.createElement("div");
  dock.style.position = "sticky";
  dock.style.bottom = "0";
  const call = document.createElement("button");
  call.type = "button";
  call.textContent = "Call Asha";
  dock.append(call);
  document.body.append(dock);
  boxes.set(dock, {
    left: 12,
    top: view() - 180,
    right: 372,
    bottom: view() - 128,
  });
  boxes.set(call, {
    left: 24,
    top: view() - 172,
    right: 360,
    bottom: view() - 136,
  });
  try {
    await act(async () =>
      notify({
        id: "fictional",
        tone: "error",
        title: "Fictional sync paused",
        message: "Fictional steps to fix it.",
      }),
    );
    await frames();
    await frames();
    expect(liftOf()).toBe("");
    const pill = host.querySelector<HTMLButtonElement>(
      'button[aria-expanded="false"]',
    );
    expect(pill?.textContent).toBe("Fictional sync paused");
    await act(async () => pill!.click());
    await frames();
    await frames();
    expect(host.textContent).toContain("Fictional steps to fix it.");
    // 8 px above the bar's measured top, 180 px up.
    expect(liftOf()).toBe("188px");
  } finally {
    restore();
    dock.remove();
    vi.useRealTimers();
  }
});

it("gives the card's chips secondary text, never muted", () => {
  // The QA robot, 8 Nov 2026 (6d86266c): muted on the dark card was 4.15:1.
  const css = readFileSync(
    join(process.cwd(), "app/notice-center.module.css"),
    "utf8",
  );
  // The chips' own rule, after the one they share with the card's action.
  const chip =
    [...css.matchAll(/\n\.reference \{([^}]*)\}/g)]
      .map((rule) => rule[1])
      .find((rule) => rule.includes("border-color: transparent")) ?? "";
  expect(chip).toContain("color: var(--lx-ink-3);");
  expect(chip).not.toContain("--lx-muted");
});

it("says whether a card is up, so one setup card waits for another", async () => {
  // Redmi QA on production (10 Nov 2026): two setup cards stacked on Home.
  const seen: boolean[] = [];
  function Probe() {
    seen.push(useNoticeShown("capture-setup"));
    return null;
  }
  await act(async () => root.render(<Probe />));
  await act(async () =>
    notify({
      id: "capture-setup",
      tone: "info",
      title: "Recording isn't set up",
    }),
  );
  await act(async () => dismissNotice("capture-setup"));
  expect(seen[0]).toBe(false);
  expect(seen).toContain(true);
  expect(seen.at(-1)).toBe(false);
});
