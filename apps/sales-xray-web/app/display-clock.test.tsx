// @vitest-environment happy-dom
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { DisplayDatesProvider, useDisplayDates } from "./display-clock";
import { dayKey, type DisplayDates } from "./display-dates";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

function Probe() {
  const dates = useDisplayDates();
  return (
    <output>
      {dates.locale}|{dates.timeZone}|{dates.today}
    </output>
  );
}

const tree = (value: DisplayDates | null) => (
  <DisplayDatesProvider value={value}>
    <Probe />
  </DisplayDatesProvider>
);

const own = new Intl.DateTimeFormat().resolvedOptions();
const browser = `${own.locale}|${own.timeZone}|${dayKey(Date.now(), own.timeZone)}`;

async function hydrate(value: DisplayDates | null) {
  const host = document.createElement("div");
  host.innerHTML = renderToString(tree(value));
  const serverText = host.textContent;
  const recoverable = vi.fn();
  let root: ReturnType<typeof hydrateRoot> | undefined;
  await act(async () => {
    root = hydrateRoot(host, tree(value), {
      onRecoverableError: recoverable,
    });
  });
  const after = host.textContent;
  await act(async () => root?.unmount());
  return { serverText, after, recoverable };
}

it("starts from the server's dates, then writes the browser's own", async () => {
  const india = {
    locale: "en-IN",
    timeZone: "Asia/Kolkata",
    today: "2026-10-11",
  };
  const { serverText, after, recoverable } = await hydrate(india);
  expect(serverText).toBe("en-IN|Asia/Kolkata|2026-10-11");
  // No mismatch: the browser starts from the server's words, then rewrites.
  expect(recoverable).not.toHaveBeenCalled();
  expect(after).toBe(browser);
});

it("keeps the server's words where the browser writes dates the same way", async () => {
  const [locale, timeZone, today] = browser.split("|");
  const { serverText, after, recoverable } = await hydrate({
    locale,
    timeZone,
    today,
  });
  expect(serverText).toBe(browser);
  expect(after).toBe(browser);
  expect(recoverable).not.toHaveBeenCalled();
});

it("uses the browser's own dates on pages the server drew without data", async () => {
  const { after, recoverable } = await hydrate(null);
  expect(after).toBe(browser);
  expect(recoverable).not.toHaveBeenCalled();
});
