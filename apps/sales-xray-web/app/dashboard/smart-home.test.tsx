import { Layers } from "lucide-react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  DayTimeline,
  DoneRing,
  DoneToday,
  SmartCounter,
  TaskMarks,
  TodayList,
  TodayRow,
  clockTime,
  listTime,
} from "./smart-home";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const draw = (node: ReactNode) => act(async () => root.render(node));

// The owner's pick (10 Nov 2026): H5's tile, words first for a screen reader.
it("draws a tile: icon, number, label and caption, opening its list", async () => {
  await draw(
    <SmartCounter
      id="open"
      icon={<Layers />}
      tone="indigo"
      label="Open leads"
      note="Need a decision"
      value={12}
      href="/leads?view=all"
    />,
  );
  const tile = host.querySelector<HTMLAnchorElement>('a[data-card="open"]');
  expect(tile?.getAttribute("href")).toBe("/leads?view=all");
  expect(tile?.getAttribute("data-tone")).toBe("indigo");
  expect(tile?.textContent).toBe("Open leads12Need a decision");
  expect(
    tile?.querySelector('[data-icon][aria-hidden="true"] svg'),
  ).not.toBeNull();
  // It looks tappable: a chevron after its number (the 13 Nov 2026 meeting).
  expect(
    tile?.querySelector('strong [data-go][aria-hidden="true"]'),
  ).not.toBeNull();
});

// Honest numbers (3 Nov 2026): not loaded is a dash and opens nothing; while
// read, a quiet bar holds the number's place.
it("says a dash when the number didn't load, and waits quietly while read", async () => {
  await draw(
    <SmartCounter
      id="new"
      icon={<Layers />}
      tone="teal"
      label="New leads"
      note="First call pending"
      value={null}
      unknown
      href="/leads"
    />,
  );
  expect(host.querySelector("a")).toBeNull();
  expect(host.querySelector("[data-go]")).toBeNull();
  expect(host.querySelector("strong")?.textContent).toBe("–");
  await draw(
    <SmartCounter
      id="new"
      icon={<Layers />}
      tone="teal"
      label="New leads"
      note="First call pending"
      value={undefined}
      href="/leads"
    />,
  );
  expect(host.querySelector("strong")?.getAttribute("aria-busy")).toBe("true");
});

// H3: a box per task due, the done ones ticked, then "+N".
it("draws a box per task due today, ticked when done", async () => {
  await draw(<TaskMarks done={2} open={1} />);
  const boxes = host.querySelectorAll("i");
  expect(boxes).toHaveLength(3);
  expect(Array.from(boxes, (box) => box.hasAttribute("data-done"))).toEqual([
    true,
    true,
    false,
  ]);
  await draw(<TaskMarks done={1} open={7} max={5} />);
  expect(host.querySelectorAll("i")).toHaveLength(5);
  expect(host.textContent).toBe("+3");
  await draw(<TaskMarks done={0} open={0} />);
  expect(host.innerHTML).toBe("");
});

// H1 and H4: the time in its own column, red with the word Late when late,
// and the kind under the words.
it("draws a row with its time, its kind, and Late in words as well as red", async () => {
  await draw(
    <TodayList
      id="list"
      title="Today's list"
      rows={[
        <li key="a">
          <TodayRow
            now={new Date("2026-11-10T09:00:00Z")}
            kind="follow_up"
            at="2026-11-10T08:30:00Z"
            late
            mark={<span />}
            title="Call back Meera Fictional"
            extra="Price question"
          />
        </li>,
        <li key="b">
          <TodayRow
            now={new Date("2026-11-10T09:00:00Z")}
            kind="task"
            at="2026-11-10T12:30:00Z"
            mark={<span />}
            title="Send the brochure"
          />
        </li>,
      ]}
      empty={<p>All clear</p>}
    />,
  );
  const rows = host.querySelectorAll("[data-today-row]");
  expect(rows).toHaveLength(2);
  expect(rows[0].querySelector('[data-col="time"]')?.textContent).toBe(
    "2:00 pm",
  );
  expect(rows[0].querySelector("[data-late-time]")).not.toBeNull();
  expect(rows[0].textContent).toContain("Follow-upLate");
  expect(rows[0].textContent).toContain("Price question");
  expect(rows[1].querySelector("[data-late-time]")).toBeNull();
  expect(rows[1].textContent).not.toContain("Late");
  expect(rows[1].querySelector('[data-col="time"]')?.textContent).toBe(
    "6:00 pm",
  );
  expect(host.textContent).not.toContain("All clear");
  await draw(
    <TodayList
      id="list"
      title="Today's list"
      rows={[]}
      empty={<p>All clear</p>}
    />,
  );
  expect(host.querySelector("ul")).toBeNull();
  expect(host.textContent).toContain("All clear");
});

it("writes times as the picture does, in India time, and an earlier day as its date", () => {
  expect(clockTime("2026-11-10T06:00:00Z")).toBe("11:30 am");
  expect(clockTime(null)).toBe("");
  const now = new Date("2026-11-10T09:00:00Z");
  expect(listTime("2026-11-10T06:00:00Z", now)).toBe("11:30 am");
  // 9 Nov, 11:00 pm in India: yesterday there, though the same day in UTC.
  expect(listTime("2026-11-09T17:30:00Z", now)).toBe("9 Nov");
  expect(listTime(null, now)).toBe("Today");
});

// H2's rings, honest: an arc only for a real share.
it("draws a ring's arc only for a real share", async () => {
  await draw(
    <DoneToday
      id="done"
      note="Inbound calls only · Today"
      figures={[
        {
          key: "attempted",
          label: "Attempted",
          value: 23,
          href: "/a",
          icon: <Layers />,
        },
        {
          key: "connected",
          label: "Connected",
          value: 9,
          of: 23,
          href: "/c",
          icon: <Layers />,
          share: 9 / 23,
        },
      ]}
    />,
  );
  expect(host.querySelector("h2")?.textContent).toBe("Done today");
  const links = host.querySelectorAll("a[data-done]");
  expect(Array.from(links, (link) => link.textContent)).toEqual([
    "Attempted23",
    "Connected9 of 23",
  ]);
  expect(links[0].querySelectorAll("circle")).toHaveLength(1);
  expect(links[1].querySelectorAll("circle")).toHaveLength(2);
  await draw(<DoneRing icon={<Layers />} share={0} />);
  expect(host.querySelectorAll("circle")).toHaveLength(1);
});

// H2's day column: built for later, not on Home (owner, 10 Nov 2026).
it("lays out the day by the hour, with a Now line", async () => {
  await draw(
    <DayTimeline
      now={new Date("2026-11-10T08:10:00Z")}
      items={[
        {
          key: "a",
          at: "2026-11-10T06:00:00Z",
          title: "Send the brochure",
          kind: "task",
          done: true,
        },
        {
          key: "b",
          at: "2026-11-10T08:30:00Z",
          title: "Call back Meera Fictional",
          kind: "follow_up",
          late: true,
        },
      ]}
    />,
  );
  const items = Array.from(host.querySelectorAll("ol > li"));
  const words = items.map((item) => item.textContent ?? "");
  expect(words[0]).toBe("9 am");
  expect(words[words.length - 1]).toBe("7 pm");
  const now = items.findIndex((item) => item.hasAttribute("data-now"));
  const brochure = words.findIndex((text) =>
    text.includes("Send the brochure"),
  );
  const meera = words.findIndex((text) => text.includes("Meera"));
  expect(brochure).toBeLessThan(now);
  expect(now).toBeLessThan(meera);
  expect(words[now]).toContain("Now");
  expect(words[meera]).toContain("Late");
  expect(items[brochure].hasAttribute("data-done")).toBe(true);
});
