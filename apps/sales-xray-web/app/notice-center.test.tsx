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
  NoticeCenter,
  NoticeDock,
  notify,
} from "./notice-center";
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
