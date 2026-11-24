// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const notify = vi.hoisted(() => vi.fn());
vi.mock("../../notice-center", () => ({ notify }));

import { DisconnectFacebook, disconnectWords } from "./meta-accounts";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const COUNT = {
  done: false,
  accounts: 2,
  pages: 5,
  pagesOn: 3,
  formsOn: 4,
  leadsKept: 120,
  revoked: false,
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  notify.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("says what disconnecting Facebook stops, from the server's own count", () => {
  expect(disconnectWords(COUNT)).toBe(
    "This stops 3 Pages and 4 forms bringing leads, and 5 connected Pages in all go. 120 leads from Facebook already in Sales X-Ray stay, with their history.",
  );
  expect(
    disconnectWords({
      ...COUNT,
      pages: 1,
      pagesOn: 1,
      formsOn: 1,
      leadsKept: 0,
    }),
  ).toBe(
    "This stops 1 Page and 1 form bringing leads. Leads already in Sales X-Ray stay.",
  );
  expect(
    disconnectWords({ ...COUNT, pagesOn: 0, formsOn: 0, pages: 2 }),
  ).toContain("No Page brings leads now");
});

it("asks first (changing nothing), then disconnects only on Disconnect", async () => {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}")) as {
      confirm?: boolean;
    };
    return new Response(
      JSON.stringify({ ...COUNT, done: body.confirm === true, status: {} }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  const changed = vi.fn();
  await act(async () =>
    root.render(<DisconnectFacebook onChanged={changed} />),
  );
  const open = host.querySelector<HTMLButtonElement>(
    'button[data-sx-feature="meta_disconnect_all"]',
  );
  expect(open?.textContent).toBe("Disconnect Facebook account");
  await act(async () => open?.click());
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/lead-desk/meta/disconnect",
    expect.objectContaining({ body: JSON.stringify({ confirm: false }) }),
  );
  const sheet = document.querySelector("dialog");
  expect(sheet?.textContent).toContain("This stops 3 Pages and 4 forms");
  expect(sheet?.textContent).toContain("All 2 Facebook accounts");
  expect(changed).not.toHaveBeenCalled();
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>(
        'button[data-sx-feature="meta_disconnect_all_confirm"]',
      )
      ?.click(),
  );
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/v1/lead-desk/meta/disconnect",
    expect.objectContaining({ body: JSON.stringify({ confirm: true }) }),
  );
  expect(changed).toHaveBeenCalledOnce();
  expect(notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "success",
      title: "Facebook disconnected",
    }),
  );
});
