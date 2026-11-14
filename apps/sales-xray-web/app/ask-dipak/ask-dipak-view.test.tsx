/**
 * Ask Dipak's screens against Dipak's acceptance list (spec section 33): the
 * homepage, the topic library, search, the interactive lessons, saved
 * lessons and the back-navigation flows A-F. The address is the browser's
 * (a small history stands in for the phone's), and the account's progress
 * is a fake server holding fictional state.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const fake = vi.hoisted(() => ({
  listeners: new Set<() => void>(),
  notices: [] as { id: string; tone: string }[],
}));

vi.mock("../notice-center", () => ({
  notify: (notice: { id: string; tone: string }) => fake.notices.push(notice),
}));

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  const subscribe = (listener: () => void) => {
    fake.listeners.add(listener);
    return () => fake.listeners.delete(listener);
  };
  return {
    useSearchParams: () =>
      new URLSearchParams(
        useSyncExternalStore(
          subscribe,
          () => window.location.search,
          () => "",
        ),
      ),
    usePathname: () => window.location.pathname,
  };
});

import coach from "./coach-notes.json";
import { AskDipakView } from "./ask-dipak-view";
import { COPY } from "./copy";
import {
  CATEGORIES,
  CATEGORY_ICONS,
  LESSONS,
  questionById,
  questionLabel,
} from "./library";
import { PROGRESS_PATH, loadProgress, resetProgress } from "./progress";

let host: HTMLDivElement;
let root: Root;
/** The phone's history: one entry per screen, Back pops one. */
let stack: string[];
let server: { saved: string[]; missions: string[]; down: boolean };
let writes: { id: string; body: unknown }[];

const emit = () => fake.listeners.forEach((listener) => listener());

function installHistory(start: string) {
  stack = [start];
  window.history.replaceState(null, "", start);
  const replace = History.prototype.replaceState;
  vi.spyOn(window.history, "pushState").mockImplementation(
    (_state, _title, url) => {
      stack.push(String(url));
      replace.call(window.history, null, "", String(url));
      emit();
    },
  );
  vi.spyOn(window.history, "replaceState").mockImplementation(
    (_state, _title, url) => {
      stack[stack.length - 1] = String(url);
      replace.call(window.history, null, "", String(url));
      emit();
    },
  );
  vi.spyOn(window.history, "back").mockImplementation(() => {
    if (stack.length < 2) return;
    stack.pop();
    replace.call(window.history, null, "", stack[stack.length - 1]);
    emit();
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}

function installServer() {
  server = { saved: [], missions: [], down: false };
  writes = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (server.down) return new Response("{}", { status: 503 });
      if (!url.startsWith(PROGRESS_PATH))
        return new Response("{}", { status: 404 });
      if ((init?.method ?? "GET") === "PUT") {
        const id = decodeURIComponent(url.slice(PROGRESS_PATH.length + 1));
        const body = JSON.parse(String(init?.body)) as {
          item: "saved" | "mission";
          on: boolean;
        };
        writes.push({ id, body });
        const list = body.item === "saved" ? server.saved : server.missions;
        const at = list.indexOf(id);
        if (body.on && at < 0) list.push(id);
        if (!body.on && at >= 0) list.splice(at, 1);
      }
      return new Response(
        JSON.stringify({ saved: server.saved, missions: server.missions }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }),
  );
}

async function show(start = "/ask-dipak") {
  installHistory(start);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<AskDipakView />);
    await loadProgress();
  });
}

const view = () =>
  host.querySelector("[data-ask-view]")?.getAttribute("data-ask-view");
const text = () => host.textContent ?? "";
const heading = () => host.querySelector("h2")?.textContent ?? "";

async function click(element: Element | null | undefined) {
  if (!element) throw new Error("nothing to click");
  await act(async () => {
    (element as HTMLElement).click();
  });
}

const link = (href: string) =>
  host.querySelector<HTMLAnchorElement>(`a[href="${href}"]`);
const button = (label: string) =>
  Array.from(host.querySelectorAll("button")).find(
    (item) =>
      item.getAttribute("aria-label") === label ||
      item.textContent?.trim() === label,
  );

async function type(value: string) {
  const input = host.querySelector<HTMLInputElement>('input[type="search"]');
  if (!input) throw new Error("no search field");
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const rows = () =>
  Array.from(
    host.querySelectorAll<HTMLAnchorElement>('a[href^="/ask-dipak?lesson="]'),
    (row) => row.getAttribute("href")?.split("=")[1],
  );

/** Every inner screen's breadcrumb, at its top. */
const crumb = () => host.querySelector('button[class*="breadcrumb"]');

beforeEach(() => {
  fake.notices.length = 0;
  resetProgress();
  installServer();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("Homepage", () => {
  it("opens Ask Dipak with Dipak's introduction card", async () => {
    await show();
    expect(view()).toBe("home");
    for (const line of [COPY.eyebrow, COPY.hello, ...COPY.intro, COPY.introAsk])
      expect(text()).toContain(line);
  });

  it("opens Search from its search entry", async () => {
    await show();
    await click(link("/ask-dipak?view=search"));
    expect(view()).toBe("search");
    expect(host.querySelector('input[type="search"]')).not.toBeNull();
  });

  it("shows the four featured topics, each opening its question list", async () => {
    await show();
    const cards = Array.from(
      host.querySelectorAll('a[href^="/ask-dipak?topic="]'),
    );
    expect(cards.map((card) => card.textContent)).toEqual([
      "Communication & RapportTrust और listening",
      "Customer को समझनाProblem और impact",
      "Price & ObjectionsPrice और hesitation",
      "Closing & Follow-UpDecision और next steps",
    ]);
    await click(link("/ask-dipak?topic=price"));
    expect(view()).toBe("topic");
    expect(heading()).toBe("Price & Objections");
    expect(rows()).toEqual(CATEGORIES[7].questions.map((q) => q.id));
  });

  it("opens the complete category library from See all", async () => {
    await show();
    await click(link("/ask-dipak?view=topics"));
    expect(view()).toBe("topics");
    expect(heading()).toBe(COPY.allTitle);
    expect(
      host.querySelectorAll('a[href^="/ask-dipak?category="]'),
    ).toHaveLength(10);
  });

  it.each([
    ["PB03", "What should I do when someone says it's too expensive?"],
    ["DM02", "What if they need to ask their wife, husband or partner?"],
    ["OB03", "What if they say 'I'll think about it'?"],
  ])(
    "shows the real situation %s and opens its own lesson",
    async (id, title) => {
      await show();
      const entry = link(`/ask-dipak?lesson=${id}`);
      expect(entry?.textContent).toContain(COPY.parts);
      expect(questionById(id)?.title).toBe(title);
      await click(entry);
      expect(view()).toBe("lesson");
      expect(heading()).toBe(questionLabel(questionById(id)!));
      expect(text()).toContain(LESSONS[id].quick);
    },
  );
});

describe("Topic library", () => {
  it("shows all 10 categories with their source titles and icons", async () => {
    await show("/ask-dipak?view=topics");
    const cards = Array.from(
      host.querySelectorAll('a[href^="/ask-dipak?category="]'),
    );
    expect(
      cards.map((card) => card.querySelector("span + span")?.textContent),
    ).toEqual(CATEGORIES.map((category) => category.name));
    cards.forEach((card, index) =>
      expect(card.querySelector("svg")?.getAttribute("data-icon")).toBe(
        CATEGORY_ICONS[CATEGORIES[index].id],
      ),
    );
  });

  it("opens a category's own questions, and only those", async () => {
    await show("/ask-dipak?view=topics");
    await click(link("/ask-dipak?category=06"));
    expect(view()).toBe("category");
    expect(heading()).toBe("Qualification & Decision Process");
    expect(text()).toContain(COPY.categorySub);
    expect(rows()).toEqual(CATEGORIES[5].questions.map((q) => q.id));
  });
});

describe("Search", () => {
  it("suggests six questions, then updates the results while typing", async () => {
    await show("/ask-dipak?view=search");
    expect(rows()).toEqual(["PB03", "OB03", "DM02", "NX02", "RP01", "CO02"]);
    await type("confident");
    expect(rows()).toContain("CF01");
    await type("confident in sales");
    expect(rows()).toEqual(["CF01"]);
  });

  it("finds a category's questions and the aliases", async () => {
    await show("/ask-dipak?view=search");
    await type("Value Creation");
    expect(rows()).toEqual(CATEGORIES[4].questions.map((q) => q.id));
    await type("expensive");
    expect(rows()[0]).toBe("PB03");
    await type("wife");
    expect(rows()[0]).toBe("DM02");
  });

  it("says so when nothing matches, and keeps the words to edit", async () => {
    await show("/ask-dipak?view=search");
    await type("qwertyuiop");
    expect(rows()).toEqual([]);
    expect(text()).toContain(COPY.noMatch);
    expect(text()).toContain(COPY.noMatchHint);
    expect(
      host.querySelector<HTMLInputElement>('input[type="search"]')?.value,
    ).toBe("qwertyuiop");
    await type("trust");
    expect(rows().length).toBeGreaterThan(0);
  });

  it("opens the chosen result's lesson, and Back keeps the search words", async () => {
    await show();
    await click(link("/ask-dipak?view=search"));
    await type("think");
    await click(link("/ask-dipak?lesson=OB03"));
    expect(heading()).toBe(questionLabel(questionById("OB03")!));
    await click(crumb());
    expect(view()).toBe("search");
    expect(
      host.querySelector<HTMLInputElement>('input[type="search"]')?.value,
    ).toBe("think");
  });
});

describe("Interactive lessons", () => {
  it.each(Object.keys(LESSONS))(
    "shows lesson %s whole, in Dipak's order, without his coaching note",
    async (id) => {
      await show(`/ask-dipak?lesson=${id}`);
      const lesson = LESSONS[id];
      expect(heading()).toBe(questionLabel(questionById(id)!));
      const sections = Array.from(
        host.querySelectorAll("h3"),
        (h) => h.textContent,
      );
      expect(sections).toEqual([
        COPY.quick,
        COPY.turn,
        COPY.cue,
        COPY.mission,
        COPY.related,
      ]);
      expect(text()).toContain(lesson.quick);
      expect(text()).toContain(lesson.scenario);
      expect(text()).toContain(lesson.cue);
      expect(text()).toContain(lesson.mission);
      const options = host.querySelectorAll("button[aria-pressed]");
      // Three options, the bookmark and the mission.
      expect(options).toHaveLength(5);
      expect(text()).not.toContain((coach.notes as Record<string, string>)[id]);
    },
  );

  it("selects one option at a time, each with its own feedback", async () => {
    await show("/ask-dipak?lesson=PB03");
    const lesson = LESSONS.PB03;
    const option = (index: number) =>
      host.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")[
        index + 1
      ];
    expect(host.querySelector('[role="status"]')).toBeNull();
    for (const index of [0, 1, 2, 1]) {
      await click(option(index));
      const pressed = Array.from(
        host.querySelectorAll("button[aria-pressed='true']"),
        (item) => item.textContent,
      );
      expect(pressed).toEqual([`${"ABC"[index]}. ${lesson.options[index][0]}`]);
      const feedback = host.querySelector('[role="status"]')?.textContent;
      expect(feedback).toContain(COPY.feedback);
      expect(feedback).toContain(lesson.options[index][1]);
      expect(feedback).toContain(lesson.options[index][2]);
      expect(feedback).toContain(COPY.compare);
      for (const other of [0, 1, 2].filter((item) => item !== index))
        expect(feedback).not.toContain(lesson.options[other][1]);
    }
  });

  it("opens and closes the Deep lesson", async () => {
    await show("/ask-dipak?lesson=DM02");
    const fold = host.querySelector<HTMLButtonElement>("button[aria-expanded]");
    expect(fold?.textContent).toContain(COPY.deep);
    expect(fold?.getAttribute("aria-expanded")).toBe("false");
    expect(text()).not.toContain(LESSONS.DM02.deep[0]);
    await click(fold);
    expect(fold?.getAttribute("aria-expanded")).toBe("true");
    const shown = document.getElementById(fold!.getAttribute("aria-controls")!);
    expect(
      Array.from(shown?.querySelectorAll("p") ?? [], (p) => p.textContent),
    ).toEqual(LESSONS.DM02.deep);
    await click(fold);
    expect(text()).not.toContain(LESSONS.DM02.deep[0]);
  });

  it("marks the Next-call mission done on the account, and undoes it", async () => {
    await show("/ask-dipak?lesson=NX02");
    expect(text()).toContain(COPY.missionTodo);
    await click(button(COPY.markMission));
    expect(writes).toEqual([
      { id: "NX02", body: { item: "mission", on: true } },
    ]);
    expect(server.missions).toEqual(["NX02"]);
    expect(button(COPY.undoMission)?.getAttribute("aria-pressed")).toBe("true");
    expect(text()).toContain(COPY.missionDone);
    await click(button(COPY.undoMission));
    expect(server.missions).toEqual([]);
    expect(text()).toContain(COPY.missionTodo);
  });

  it("takes a mission back if the account couldn't save it", async () => {
    await show("/ask-dipak?lesson=NX02");
    server.down = true;
    await click(button(COPY.markMission));
    expect(button(COPY.markMission)?.getAttribute("aria-pressed")).toBe(
      "false",
    );
    expect(fake.notices).toEqual([
      expect.objectContaining({ id: "ask-dipak-save", tone: "error" }),
    ]);
  });

  it("opens related lessons from their own records", async () => {
    await show("/ask-dipak?lesson=PB03");
    const related = LESSONS.PB03.next;
    expect(
      related.every((id) => link(`/ask-dipak?lesson=${id}`) !== null),
    ).toBe(true);
    await click(link(`/ask-dipak?lesson=${related[0]}`));
    expect(heading()).toBe(questionLabel(questionById(related[0])!));
  });

  it("says plainly when a question's lesson isn't ready, inventing nothing", async () => {
    await show("/ask-dipak?lesson=PB05");
    expect(heading()).toBe(questionById("PB05")?.title);
    expect(
      host.querySelector('[data-lesson-state="not-ready"]'),
    ).not.toBeNull();
    expect(text()).toContain(COPY.notReady);
    expect(host.querySelectorAll("button[aria-pressed]")).toHaveLength(0);
    expect(text()).not.toContain(COPY.quick);
    expect(text()).not.toContain(COPY.parts);
  });
});

describe("Saved lessons", () => {
  it("saves a lesson, lights the bookmark, lists it and removes it again", async () => {
    await show("/ask-dipak?lesson=RP01");
    const mark = () => button(COPY.save) ?? button(COPY.unsave) ?? null;
    expect(mark()?.getAttribute("aria-pressed")).toBe("false");
    await click(mark());
    expect(server.saved).toEqual(["RP01"]);
    expect(mark()?.getAttribute("aria-label")).toBe(COPY.unsave);
    expect(mark()?.getAttribute("aria-pressed")).toBe("true");
    expect(mark()?.className).toContain("active");

    await click(button(COPY.savedTool));
    expect(view()).toBe("saved");
    expect(rows()).toEqual(["RP01"]);
    await click(link("/ask-dipak?lesson=RP01"));
    await click(mark());
    expect(server.saved).toEqual([]);
    await click(button(COPY.savedTool));
    expect(rows()).toEqual([]);
    expect(text()).toContain(COPY.savedEmpty);
    expect(text()).toContain(COPY.savedEmptyHint);
  });

  it("shows the empty state only once the account has answered", async () => {
    let answer: (response: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            answer = resolve;
          }),
      ),
    );
    installHistory("/ask-dipak?view=saved");
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => {
      root.render(<AskDipakView />);
      void loadProgress();
    });
    expect(text()).not.toContain(COPY.savedEmpty);
    expect(host.querySelector('[aria-busy="true"]')).not.toBeNull();
    await act(async () => {
      answer(
        new Response(JSON.stringify({ saved: [], missions: [] }), {
          status: 200,
        }),
      );
      await loadProgress();
    });
    expect(text()).toContain(COPY.savedEmpty);
  });

  it("keeps saved lessons and missions after the app is opened again", async () => {
    server.saved.push("OB03");
    server.missions.push("OB03");
    await show("/ask-dipak?lesson=OB03");
    expect(button(COPY.unsave)?.getAttribute("aria-pressed")).toBe("true");
    expect(button(COPY.undoMission)?.getAttribute("aria-pressed")).toBe("true");
    await act(async () => root.unmount());
    host.remove();
    vi.restoreAllMocks();
    resetProgress();
    await show("/ask-dipak?view=saved");
    expect(rows()).toEqual(["OB03"]);
  });
});

describe("Navigation (spec Flow F)", () => {
  it("goes back from a lesson to the page it was opened from", async () => {
    await show();
    await click(link("/ask-dipak?view=topics"));
    await click(link("/ask-dipak?category=09"));
    await click(link("/ask-dipak?lesson=NX02"));
    await click(crumb());
    expect(view()).toBe("category");
    expect(heading()).toBe("Closing & Follow-Up");
    await click(crumb());
    expect(view()).toBe("topics");
    await click(crumb());
    expect(view()).toBe("home");
  });

  it("goes back from a related lesson to the lesson before it", async () => {
    await show("/ask-dipak?lesson=PB03");
    await click(link(`/ask-dipak?lesson=${LESSONS.PB03.next[0]}`));
    await click(crumb());
    expect(heading()).toBe(questionLabel(questionById("PB03")!));
    // Nothing behind it in this visit: Back leads to Ask Dipak's home.
    await click(crumb());
    expect(view()).toBe("home");
  });

  it("goes back from a category to the topic library, even when opened directly", async () => {
    await show("/ask-dipak?category=03");
    expect(crumb()?.textContent).toContain(COPY.allTitle);
    await click(crumb());
    expect(view()).toBe("topics");
  });

  it.each([
    ["/ask-dipak?topic=talk", "topic"],
    ["/ask-dipak?view=search", "search"],
    ["/ask-dipak?view=saved", "saved"],
    ["/ask-dipak?view=topics", "topics"],
  ])("goes back from %s to Ask Dipak's home", async (start, kind) => {
    await show(start);
    expect(view()).toBe(kind);
    expect(crumb()?.textContent).toContain(COPY.title);
    await click(crumb());
    expect(view()).toBe("home");
  });

  it("goes back from Search to the home even when opened from a lesson", async () => {
    await show("/ask-dipak?lesson=DM01");
    await click(button(COPY.searchTool));
    expect(view()).toBe("search");
    await click(crumb());
    expect(view()).toBe("home");
  });

  it("follows the phone's own Back through the history", async () => {
    await show();
    await click(link("/ask-dipak?topic=close"));
    await click(link("/ask-dipak?lesson=NX02"));
    await act(async () => window.history.back());
    expect(view()).toBe("topic");
    await act(async () => window.history.back());
    expect(view()).toBe("home");
  });

  it("opens lessons from their stable address", async () => {
    await show("/ask-dipak?lesson=NEW-035");
    expect(heading()).toBe(questionById("NEW-035")?.title);
    expect(text()).toContain(LESSONS["NEW-035"].mission);
  });
});

it("never writes an unknown lesson's progress", async () => {
  await show("/ask-dipak?lesson=ZZ99");
  expect(text()).toContain(COPY.notFound);
  expect(host.querySelectorAll("button[aria-pressed]")).toHaveLength(0);
  expect(crumb()?.textContent).toContain(COPY.title);
});
