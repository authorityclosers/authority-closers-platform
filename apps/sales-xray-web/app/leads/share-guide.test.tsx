// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import {
  WorkspaceAccessContext,
  type WorkspaceAccessValue,
} from "../workspace-access";
import { ShareGuide } from "./share-guide";
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const render = (personId: string, key = "first") =>
  act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={
          {
            status: "ready",
            authenticated: true,
            context: {
              personId,
              tenantId: "fictional-workspace",
              sessionId: "fictional-session",
            },
            retry: () => undefined,
          } satisfies WorkspaceAccessValue
        }
      >
        <ShareGuide key={key} active />
      </WorkspaceAccessContext.Provider>,
    ),
  );
const click = (text: string) =>
  act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent?.includes(text))!
      .click(),
  );
it("walks through three steps, remembers this person, and reopens from help", async () => {
  await render("fictional-person");
  expect(host.textContent).toContain("Choose how to share");
  await click("Next");
  expect(host.textContent).toContain("Pick who gets them");
  await click("Next");
  expect(host.textContent).toContain("Check, then give out");
  await click("Got it");
  expect(host.querySelector("section")).toBeNull();
  await render("fictional-person", "second");
  expect(host.querySelector("section")).toBeNull();
  await click("How it works");
  expect(host.textContent).toContain("1 of 3");
  await click("Skip guide");
  expect(host.querySelector("section")).toBeNull();
  await render("another-fictional-person");
  expect(host.textContent).toContain("Choose how to share");
});
it("still works when browser storage is unavailable", async () => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("Unavailable");
  };
  try {
    await render("fictional-person");
    await click("Skip guide");
    expect(host.querySelector("section")).toBeNull();
  } finally {
    Storage.prototype.setItem = original;
  }
});
