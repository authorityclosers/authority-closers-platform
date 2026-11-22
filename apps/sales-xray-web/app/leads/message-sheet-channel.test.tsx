import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { MessageSheet } from "./message-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const target = {
  leadId: "lead-1",
  phone: "+919999900001",
  name: "Asha Example",
  interest: null,
};
const templates = [
  { key: "intro", label: "Intro", text: "Hi {leadName}, this is {myName}." },
];

// Owner, 19 Oct: the WhatsApp and SMS buttons beside Call open the sheet on
// the channel tapped.
it.each([
  ["whatsapp", /^https:\/\/wa\.me\//],
  ["sms", /^sms:/],
] as const)(
  "opens on %s when that button was tapped",
  async (channel, href) => {
    await act(async () =>
      root.render(
        <MessageSheet
          open
          target={target}
          templates={templates}
          myName="Ravi"
          org="Example Co"
          channel={channel}
          onClose={() => {}}
        />,
      ),
    );
    const send = [
      ...document.querySelectorAll<HTMLAnchorElement>("a[href]"),
    ].find((link) => /wa\.me|^sms:/.test(link.getAttribute("href") ?? ""));
    expect(send?.getAttribute("href")).toMatch(href);
  },
);

// PR #663 review (P1): a held send must not open WhatsApp while this channel's
// limits are still being read; a failed read does not hold it for ever.
it("holds the send until the channel's limits are read", async () => {
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
  await act(async () =>
    root.render(
      <MessageSheet
        open
        target={target}
        templates={templates}
        myName="Ravi"
        org="Example Co"
        channel="whatsapp"
        onClose={() => {}}
      />,
    ),
  );
  const send = () =>
    [...document.querySelectorAll<HTMLAnchorElement>("a[href]")].find((link) =>
      /wa\.me/.test(link.getAttribute("href") ?? ""),
    );
  expect(send()?.getAttribute("aria-disabled")).toBe("true");
  expect(send()?.textContent).toContain("Checking");
  const click = new MouseEvent("click", { bubbles: true, cancelable: true });
  send()?.dispatchEvent(click);
  expect(click.defaultPrevented).toBe(true);

  await act(async () => {
    answer(new Response("{}", { status: 500 }));
  });
  expect(send()?.getAttribute("aria-disabled")).toBeNull();
  expect(send()?.textContent).toContain("Open WhatsApp");
});
