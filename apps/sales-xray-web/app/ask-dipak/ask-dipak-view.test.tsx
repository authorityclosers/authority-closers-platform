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
  DRAFTS,
  REAL_SITUATIONS,
  featuredById,
  featuredQuestions,
  questionById,
  questionLabel,
} from "./library";
import {
  KEEP,
  LESSON_PATH,
  loadLesson,
  primeLessons,
  resetLessons,
} from "./lessons";
import { paragraphs } from "./lesson-screen";
import { PROGRESS_PATH, loadProgress, resetProgress } from "./progress";
import { LESSONS, SELLER_LESSONS, servedLesson } from "./test-lessons";

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

/** Dipak's answer waits for a pick (report 228 note); tests that read it open it. */
async function openAnswer() {
  const peek = button(COPY.gatePeek);
  if (peek) await click(peek);
}

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
  // The home's Continue card reads the last lesson opened on this device.
  window.localStorage.removeItem("sales-xray:ask-dipak:last-lesson");
  resetProgress();
  // Dipak's lessons as already served this visit (lessons.ts); the tests under
  // "Lessons from the API" start without them.
  resetLessons();
  primeLessons(SELLER_LESSONS);
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

  it("is the Coach's desk: Dipak's monogram (no generated face), Continue, search, situations, topics (owner's pick H-A, 17 Nov 2026)", async () => {
    await show();
    expect(
      host.querySelector('[role="img"][aria-label="Dipak Vishwakarma"]')
        ?.textContent,
    ).toBe("DV");
    // Dipak's face is never a picture: the only pictures on his desk are the
    // kit's Ask Dipak lockup and the kit's fictional Aman and Rohit (brand
    // order, 19 Nov 2026).
    expect(
      host.querySelector(
        'img:not([src^="/brand/"]):not([src^="/media/ask-dipak/characters/"])',
      ),
    ).toBeNull();
    // The strong card at the top carries Continue (owner, 17 Nov 2026).
    expect(host.querySelector("section a[data-continue]")).not.toBeNull();
    // No active mission (the coaching API isn't served here): no strip.
    expect(host.querySelector("[data-mission-strip]")).toBeNull();
    // Three situations and four topics, each with its drawing.
    expect(host.querySelectorAll("svg[data-art]")).toHaveLength(7);
    // No emoji after his hello: Mukta has none (an empty box, 17 Nov 2026).
    expect(COPY.hello).not.toMatch(/\p{Extended_Pictographic}/u);
  });

  it("tells the three real situations apart, each its own colour and drawing (Dipak's report 226)", async () => {
    await show();
    const cards = REAL_SITUATIONS.map((id) =>
      host.querySelector(`a[href="/ask-dipak?lesson=${id}"]`),
    );
    const looks = cards.map((card) =>
      Array.from(card?.classList ?? []).join(" "),
    );
    expect(new Set(looks).size).toBe(3);
    for (const card of cards) {
      expect(card?.querySelector("svg[data-art]")).not.toBeNull();
      expect(card?.textContent).toContain(COPY.parts);
    }
  });

  it("numbers a topic's questions, each its own card (Dipak's report 227)", async () => {
    await show("/ask-dipak?topic=talk");
    const rows = Array.from(
      host.querySelectorAll<HTMLAnchorElement>('a[href^="/ask-dipak?lesson="]'),
    );
    const questions = featuredQuestions(featuredById("talk")!);
    expect(rows).toHaveLength(questions.length);
    rows.forEach((row, index) => {
      expect(row.firstElementChild?.textContent).toBe(String(index + 1));
      expect(row.textContent).toContain(questionLabel(questions[index]));
    });
  });

  it("offers Continue for the lesson just opened", async () => {
    await show("/ask-dipak?lesson=OB03");
    await openAnswer();
    await click(crumb());
    expect(view()).toBe("home");
    expect(host.querySelector("a[data-continue]")?.getAttribute("href")).toBe(
      "/ask-dipak?lesson=OB03",
    );
  });

  it("keeps the greeting short: Dipak's intro lines fold until asked for (owner, 16 Nov 2026)", async () => {
    await show();
    const toggle = host.querySelector<HTMLButtonElement>(
      "button[aria-expanded]",
    );
    const more = host.querySelector(
      `[id="${toggle?.getAttribute("aria-controls")}"]`,
    );
    expect(toggle?.textContent).toBe(COPY.introMore);
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(more?.getAttribute("aria-hidden")).toBe("true");
    expect(more?.hasAttribute("inert")).toBe(true);
    for (const line of COPY.intro) expect(more?.textContent).toContain(line);
    await click(toggle);
    expect(toggle?.textContent).toBe(COPY.introLess);
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    expect(more?.getAttribute("aria-hidden")).toBe("false");
    expect(more?.hasAttribute("inert")).toBe(false);
  });

  it("opens Saved lessons from the greeting's corner", async () => {
    await show();
    await click(button(COPY.savedLessons));
    expect(view()).toBe("saved");
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
    // His docs' wording of the question (16 Nov 2026).
    [
      "DM02",
      "What if the customer says they need to ask their wife, husband or partner?",
    ],
    ["OB03", "What should I say when a customer says, 'I'll think about it'?"],
  ])(
    "shows the real situation %s and opens its own lesson",
    async (id, title) => {
      await show();
      const entry = link(`/ask-dipak?lesson=${id}`);
      expect(entry?.textContent).toContain(COPY.parts);
      expect(questionById(id)?.title).toBe(title);
      await click(entry);
      await openAnswer();
      expect(view()).toBe("lesson");
      expect(heading()).toBe(questionLabel(questionById(id)!));
      for (const beat of paragraphs(LESSONS[id].quick))
        expect(text()).toContain(beat);
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
    // Each with its own drawing (owner's pick, 17 Nov 2026).
    cards.forEach((card, index) =>
      expect(card.querySelector("svg")?.getAttribute("data-art")).toBe(
        CATEGORIES[index].id,
      ),
    );
  });

  it("opens a category's own questions, and only those", async () => {
    await show("/ask-dipak?view=topics");
    await click(link("/ask-dipak?category=06"));
    expect(view()).toBe("category");
    expect(heading()).toBe("Qualification & Decision Process");
    expect(text()).toContain(COPY.categorySub);
    // Its cover: number, line and the real lesson count.
    const cover = host.querySelector("[data-cover]")?.textContent ?? "";
    expect(cover).toContain("06");
    expect(cover).toContain(COPY.lessonCount(CATEGORIES[5].questions.length));
    expect(
      host.querySelector('[data-cover] svg[data-art="06"]'),
    ).not.toBeNull();
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
    "shows lesson %s whole, in Dipak's order, without his coaching note or report lock",
    async (id) => {
      await show(`/ask-dipak?lesson=${id}`);
      await openAnswer();
      const lesson = LESSONS[id];
      expect(heading()).toBe(questionLabel(questionById(id)!));
      const sections = Array.from(
        host.querySelectorAll("h3"),
        (h) => h.textContent,
      );
      // The question first, then his answer (Dipak's report 228, 16 Nov 2026).
      expect(sections).toEqual([
        COPY.turn,
        COPY.shift,
        COPY.quick,
        COPY.cue,
        COPY.mission,
        COPY.related,
      ]);
      // His before/after lines first, word for word, under his labels.
      const mindset = host.querySelector("[data-mindset]")?.textContent ?? "";
      expect(mindset).toContain(COPY.before);
      expect(mindset).toContain(lesson.before);
      expect(mindset).toContain(COPY.after);
      expect(mindset).toContain(lesson.after);
      // His quick answer, one beat per paragraph, in order and whole.
      expect(
        Array.from(
          host.querySelectorAll('[data-part="quick"] li p'),
          (p) => p.textContent,
        ),
      ).toEqual(paragraphs(lesson.quick));
      for (const line of paragraphs(lesson.scenario))
        expect(text()).toContain(line);
      // The track shows every part, the first one current.
      const steps = host.querySelectorAll("ol[aria-label] > li");
      expect(steps).toHaveLength(7);
      expect(steps[0].getAttribute("aria-current")).toBe("step");
      expect(text()).toContain(lesson.cue);
      expect(text()).toContain(lesson.mission);
      const options = host.querySelectorAll("button[aria-pressed]");
      // Three options, the bookmark and the mission's commit.
      expect(options).toHaveLength(5);
      expect(text()).not.toContain((coach.notes as Record<string, string>)[id]);
      // The report and coaching consistency lock is for reports, not sellers.
      for (const line of lesson.lock ?? []) expect(text()).not.toContain(line);
      expect(host.querySelector("[data-draft]")).toBeNull();
    },
  );

  it("selects one option at a time, each with its own feedback", async () => {
    await show("/ask-dipak?lesson=PB03");
    await openAnswer();
    const lesson = LESSONS.PB03;
    const option = (index: number) =>
      host.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")[
        index + 1
      ];
    expect(host.querySelector('[role="status"]')).toBeNull();
    expect(text()).toContain(COPY.pickHint);
    const seen = new Set<number>();
    for (const index of [0, 1, 2, 1]) {
      await click(option(index));
      seen.add(index);
      const pressed = Array.from(
        host.querySelectorAll("button[aria-pressed='true']"),
        (item) => item.textContent,
      );
      expect(pressed).toEqual([`${"ABC"[index]}. ${lesson.options[index][0]}`]);
      const status = host.querySelector('[role="status"]');
      const feedback = status?.textContent;
      expect(feedback).toContain(COPY.feedback);
      // Right under the option picked, in the same card.
      expect(status?.previousElementSibling?.getAttribute("aria-pressed")).toBe(
        "true",
      );
      // Dipak's word, one paragraph per line of his, then his small example.
      const lines = lesson.options[index][1].split("\n");
      expect(
        Array.from(
          status?.querySelectorAll("p[class*='feedbackLine']") ?? [],
          (p) => p.textContent,
        ),
      ).toEqual(lines);
      expect(lines.at(-1)).toMatch(/छोटा example:/);
      // His takeaway with his label ("Better सोच").
      expect(status?.querySelector("[data-takeaway]")?.textContent).toBe(
        `${lesson.options[index][3]}: ${lesson.options[index][2]}`,
      );
      // Until all three are seen, it offers the others; then says so.
      if (seen.size === 3) expect(feedback).toContain(COPY.allSeen);
      else expect(feedback).toContain(COPY.compare);
      for (const other of [0, 1, 2].filter((item) => item !== index))
        expect(feedback).not.toContain(lesson.options[other][1].split("\n")[0]);
    }
  });

  it("opens and closes the Deep lesson", async () => {
    await show("/ask-dipak?lesson=DM02");
    await openAnswer();
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
    await openAnswer();
    expect(text()).toContain(COPY.missionTodo);
    await click(button(COPY.markMission));
    expect(writes).toEqual([
      { id: "NX02", body: { item: "mission", on: true } },
    ]);
    expect(server.missions).toEqual(["NX02"]);
    expect(button(COPY.undoMission)?.getAttribute("aria-pressed")).toBe("true");
    expect(text()).toContain(COPY.missionOn);
    await click(button(COPY.undoMission));
    expect(server.missions).toEqual([]);
    expect(text()).toContain(COPY.missionTodo);
  });

  it("takes a mission back if the account couldn't save it", async () => {
    await show("/ask-dipak?lesson=NX02");
    await openAnswer();
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
    await openAnswer();
    const related = LESSONS.PB03.next;
    expect(
      related.every((id) => link(`/ask-dipak?lesson=${id}`) !== null),
    ).toBe(true);
    await click(link(`/ask-dipak?lesson=${related[0]}`));
    expect(heading()).toBe(questionLabel(questionById(related[0])!));
  });

  it("shows the questions that were drafts as Dipak's own lessons, their missions markable", async () => {
    await show("/ask-dipak?lesson=PB05");
    await openAnswer();
    expect(heading()).toBe(questionById("PB05")?.title);
    expect(DRAFTS.PB05).toBeUndefined();
    expect(host.querySelector("[data-draft]")).toBeNull();
    for (const beat of paragraphs(LESSONS.PB05.quick))
      expect(text()).toContain(beat);
    expect(text()).toContain(LESSONS.PB05.mission);
    expect(text()).not.toContain(COPY.draftMission);
    expect(button(COPY.markMission)).not.toBeUndefined();
  });
});

describe("Saved lessons", () => {
  it("saves a lesson, lights the bookmark, lists it and removes it again", async () => {
    await show("/ask-dipak?lesson=RP01");
    await openAnswer();
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
    await openAnswer();
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
    await openAnswer();
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
    await openAnswer();
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
    await openAnswer();
    expect(heading()).toBe(questionById("NEW-035")?.title);
    expect(text()).toContain(LESSONS["NEW-035"].mission);
  });
});

it("never writes an unknown lesson's progress", async () => {
  await show("/ask-dipak?lesson=ZZ99");
  await openAnswer();
  expect(text()).toContain(COPY.notFound);
  expect(host.querySelectorAll("button[aria-pressed]")).toHaveLength(0);
  expect(crumb()?.textContent).toContain(COPY.title);
});

describe("Lessons from the API (16 Nov 2026: served from the database)", () => {
  function serveLessons(answer: (id: string) => Response | Promise<Response>) {
    const asked: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith(`${LESSON_PATH}/`)) {
          const id = decodeURIComponent(url.slice(LESSON_PATH.length + 1));
          asked.push(id);
          return answer(id);
        }
        return new Response(JSON.stringify({ saved: [], missions: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );
    return asked;
  }
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  beforeEach(() => {
    resetLessons();
    window.localStorage.clear();
  });

  it("loads a lesson when it is opened, once, with his before/after and labels", async () => {
    const asked = serveLessons((id) => json(servedLesson(id)));
    await show("/ask-dipak?lesson=RP01");
    await act(async () => {
      await loadLesson("RP01");
    });
    await openAnswer();
    expect(asked).toEqual(["RP01"]);
    const lesson = LESSONS.RP01;
    for (const beat of paragraphs(lesson.quick)) expect(text()).toContain(beat);
    expect(text()).toContain(lesson.before);
    await click(
      host.querySelectorAll<HTMLButtonElement>("button[aria-pressed]")[1],
    );
    // RP01's own label for the takeaway.
    expect(host.querySelector("[data-takeaway]")?.textContent).toBe(
      `याद रखने वाली बात: ${lesson.options[0][2]}`,
    );
    for (const line of lesson.lock) expect(text()).not.toContain(line);
    // Kept on the phone for next time.
    expect(
      window.localStorage.getItem("sales-xray:ask-dipak:lesson:RP01"),
    ).toContain(lesson.cue);
  });

  it("shows his heading above the before/after lines where he wrote one", async () => {
    serveLessons((id) => json(servedLesson(id)));
    await show("/ask-dipak?lesson=CF01");
    await act(async () => {
      await loadLesson("CF01");
    });
    await openAnswer();
    expect(LESSONS.CF01.shift).toBe("इस answer से कौन-सी सोच बदलनी है:");
    // The question comes first (report 228); his heading opens the answer.
    expect(
      Array.from(host.querySelectorAll("h3"), (h) => h.textContent).slice(0, 2),
    ).toEqual([COPY.turn, COPY.shift]);
    expect(host.querySelector("[data-mindset]")?.textContent).toContain(
      LESSONS.CF01.after,
    );
  });

  it("says it is loading, then offers a retry when the lesson can't be reached", async () => {
    let down = true;
    serveLessons((id) =>
      down ? new Response("{}", { status: 503 }) : json(servedLesson(id)),
    );
    await show("/ask-dipak?lesson=DM02");
    await act(async () => {
      await loadLesson("DM02");
    });
    await openAnswer();
    expect(
      host.querySelector('[data-lesson-state="failed"]')?.textContent,
    ).toContain(COPY.loadFailed);
    down = false;
    await click(button(COPY.retry));
    await act(async () => {
      await loadLesson("DM02");
    });
    await openAnswer();
    expect(host.querySelector("[data-lesson-state]")).toBeNull();
    for (const beat of paragraphs(LESSONS.DM02.quick))
      expect(text()).toContain(beat);
  });

  it("opens a lesson kept on the phone without a connection", async () => {
    serveLessons((id) => json(servedLesson(id)));
    await show("/ask-dipak?lesson=OB03");
    await act(async () => {
      await loadLesson("OB03");
    });
    await openAnswer();
    await act(async () => root.unmount());
    host.remove();
    // A new visit, offline.
    resetLessons();
    serveLessons(() => Promise.reject(new TypeError("offline")));
    await show("/ask-dipak?lesson=OB03");
    await act(async () => {
      await loadLesson("OB03");
    });
    await openAnswer();
    for (const beat of paragraphs(LESSONS.OB03.quick))
      expect(text()).toContain(beat);
    expect(host.querySelector("[data-lesson-state]")).toBeNull();
  });

  it("keeps only the last few lessons on the phone", async () => {
    serveLessons((id) => json(servedLesson(id)));
    const ids = Object.keys(LESSONS).slice(0, KEEP + 3);
    for (const id of ids) await loadLesson(id);
    const kept = ids.filter((id) =>
      window.localStorage.getItem(`sales-xray:ask-dipak:lesson:${id}`),
    );
    expect(kept).toEqual(ids.slice(3));
    await show();
  });
});

describe("Dipak's answer waits for a pick (report 228 note, 18 Nov 2026)", () => {
  it("folds his answer until an option is picked, and opens it on a pick", async () => {
    await show("/ask-dipak?lesson=OB03");
    expect(host.querySelector("[data-answer-gate]")).not.toBeNull();
    for (const beat of paragraphs(LESSONS.OB03.quick))
      expect(text()).not.toContain(beat);
    expect(host.querySelector('[data-part="quick"]')).toBeNull();
    await click(host.querySelector('button[data-letter="B"]'));
    expect(host.querySelector("[data-answer-gate]")).toBeNull();
    for (const beat of paragraphs(LESSONS.OB03.quick))
      expect(text()).toContain(beat);
  });

  it("opens his answer without a pick when asked", async () => {
    await show("/ask-dipak?lesson=OB03");
    await click(button(COPY.gatePeek));
    expect(host.querySelector("[data-answer-gate]")).toBeNull();
    expect(host.querySelector('[data-part="quick"]')).not.toBeNull();
  });
});

describe("My learning: Progress | Saved (study S6, 18 Nov 2026)", () => {
  it("counts what the account keeps per topic, with no score", async () => {
    server.saved.push("OB03");
    server.missions.push("NX02");
    await show("/ask-dipak?view=saved");
    expect(heading()).toBe(COPY.learningTitle);
    expect(text()).toContain(`${COPY.paneSaved} (1)`);
    await click(
      Array.from(host.querySelectorAll('[role="tab"]')).find(
        (tab) => tab.textContent === COPY.paneProgress,
      ),
    );
    expect(host.querySelectorAll("[data-topic-line]")).toHaveLength(10);
    expect(text()).toContain(COPY.statSaved);
    expect(text()).not.toMatch(/%|streak|score/i);
  });
});
