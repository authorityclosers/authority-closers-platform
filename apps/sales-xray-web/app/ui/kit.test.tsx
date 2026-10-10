import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Inbox } from "lucide-react";

import {
  Avatar,
  Delta,
  Empty,
  InlineEdit,
  Kpi,
  Panel,
  QueryTabs,
  Spark,
  Table,
  Tiles,
  initials,
} from "./kit";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
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

it("says a change in words and an arrow, never colour alone", () => {
  const up = renderToStaticMarkup(<Delta value={12} previous={10} />);
  expect(up).toContain('data-trend="up"');
  expect(up).toContain("up ");
  expect(up).toContain("20%");
  expect(renderToStaticMarkup(<Delta value={8} previous={10} />)).toContain(
    "down ",
  );
  expect(renderToStaticMarkup(<Delta value={3} previous={0} />)).toContain(
    "new",
  );
  expect(renderToStaticMarkup(<Delta value={0} previous={0} />)).toContain(
    'data-trend="flat"',
  );
});

it("draws a sparkline only when three or more points carry it", () => {
  expect(renderToStaticMarkup(<Spark values={[0, 4, 0, 1]} label="x" />)).toBe(
    "",
  );
  const markup = renderToStaticMarkup(
    <Spark values={[1, 4, 2, 3]} label="Calls per week" />,
  );
  expect(markup).toContain('aria-label="Calls per week"');
  expect(markup.match(/<i /g)).toHaveLength(4);
});

it("builds tiles, panels and tables with their labels", () => {
  const markup = renderToStaticMarkup(
    <>
      <Tiles>
        <Kpi label="Calls" value={14} note="last 30 days" />
      </Tiles>
      <Panel
        title="Team calls"
        sub="14"
        action={{ href: "/calls", label: "Open" }}
      >
        <Table label="Team calls" cards={<p>card</p>}>
          <tbody>
            <tr>
              <td>Row</td>
            </tr>
          </tbody>
        </Table>
      </Panel>
    </>,
  );
  expect(markup).toContain('aria-label="Key numbers"');
  expect(markup).toContain("last 30 days");
  expect(markup).toContain('href="/calls"');
  expect(markup).toContain('<table class="');
  expect(markup).toContain('aria-label="Team calls"');
  expect(markup).toContain("data-has-cards");
});

it("keeps tabs in the address and marks the current one", () => {
  const markup = renderToStaticMarkup(
    <QueryTabs
      base="/organisation"
      current="members"
      items={[
        { key: "overview", label: "Overview" },
        { key: "members", label: "Members", count: 8 },
      ]}
    />,
  );
  expect(markup).toContain('href="/organisation"');
  expect(markup).toContain('href="/organisation?tab=members"');
  expect(markup).toMatch(/aria-current="page"[^>]*>Members/);
});

it("gives people stable initials and an empty state one action", () => {
  expect(initials("Dr. Asha Menon")).toBe("AM");
  expect(initials("समीर जोशी")).toBe("सज");
  expect(initials("  ")).toBe("?");
  expect(renderToStaticMarkup(<Avatar name="Asha Menon" />)).toContain("AM");
  const empty = renderToStaticMarkup(
    <Empty
      icon={Inbox}
      title="No calls yet"
      text="Analyse a call to see it here."
      action={{ href: "/analysis/new", label: "Analyse a call" }}
    />,
  );
  expect(empty.match(/<a /g)).toHaveLength(1);
});

async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const key = (input: HTMLInputElement, name: string) =>
  act(async () => {
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: name, bubbles: true }),
    );
  });

it("edits in place: Enter saves, Escape keeps the old value", async () => {
  const onSave = vi.fn(async () => {});
  await act(async () =>
    root.render(
      <InlineEdit value="Discovery call" label="Call name" onSave={onSave} />,
    ),
  );
  const trigger = host.querySelector("button")!;
  expect(trigger.getAttribute("aria-label")).toBe(
    "Call name: Discovery call. Edit",
  );
  await act(async () => trigger.click());
  let input = host.querySelector("input")!;
  await type(input, "Pricing call");
  await key(input, "Escape");
  expect(onSave).not.toHaveBeenCalled();
  expect(host.querySelector("input")).toBeNull();

  await act(async () => host.querySelector("button")!.click());
  input = host.querySelector("input")!;
  await type(input, "  Pricing call ");
  await key(input, "Enter");
  expect(onSave).toHaveBeenCalledOnce();
  expect(onSave).toHaveBeenCalledWith("Pricing call");
  expect(host.querySelector("input")).toBeNull();
});

it("keeps the draft and says why when a save fails", async () => {
  const onSave = vi.fn(async () => {
    throw new Error("Someone renamed this call. Reload to see it.");
  });
  await act(async () =>
    root.render(<InlineEdit value="Call" label="Call name" onSave={onSave} />),
  );
  await act(async () => host.querySelector("button")!.click());
  const input = host.querySelector("input")!;
  await type(input, "Renamed");
  await key(input, "Enter");
  expect(host.querySelector("input")?.value).toBe("Renamed");
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "Someone renamed this call. Reload to see it.",
  );
});

it("uses only the shared tokens: no raw colours in the kit's styles", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "kit.module.css"),
    "utf8",
  );
  expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  expect(css).not.toMatch(/\b(rgb|rgba|hsl|hsla)\(/);
  // Text stays on the scale: 12 px or more (16 px phone fields included).
  const sizes = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)].map(
    (match) => Number(match[1]),
  );
  expect(sizes.every((size) => size >= 12)).toBe(true);
});
