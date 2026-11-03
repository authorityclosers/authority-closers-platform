import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceAccessValue } from "../../workspace-access";
import example from "../../review-fixture/coaching-guide/example.json";
import { GuideEntry } from "./guide-entry";
import { parseGuide, type Guide } from "./guide-content";
import { GuidePage } from "./guide-page";

const mocks = vi.hoisted(() => ({
  access: null as WorkspaceAccessValue | null,
}));
vi.mock("../../workspace-access", () => ({
  useWorkspaceAccess: () => mocks.access,
}));
vi.mock("../../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: React.ReactNode }) => (
    <main>{children}</main>
  ),
}));

const SIGNED_IN = {
  status: "ready",
  authenticated: true,
  context: { personId: "p", sessionId: "s", tenantId: "t" },
  retry: () => {},
} as WorkspaceAccessValue;

/** Fictional placeholder rows, never coaching content. */
const REAL = parseGuide({
  format: 1,
  version: 2,
  examples: false,
  starters: ["A-1"],
  questions: [
    {
      id: "A-1",
      question: "Fictional question?",
      answer: "Fictional answer.",
      next: [],
    },
  ],
}) as Guide;
const EMPTY = parseGuide({
  format: 1,
  version: 0,
  examples: false,
  starters: [],
  questions: [],
});

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  window.history.replaceState(null, "", "/coaching/guide");
  mocks.access = SIGNED_IN;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

const open = async (guide: Guide | null) =>
  act(async () => root.render(<GuidePage load={async () => guide} />));

describe("Dipak's answers page", () => {
  it("shows real content under Coaching", async () => {
    await open(REAL);
    expect(host.querySelector("h1")?.textContent).toBe("Dipak’s answers");
    expect(host.textContent).toContain("1 question");
    expect(host.textContent).not.toContain("1 questions");
    expect(host.querySelector('a[href="/coaching"]')?.textContent).toContain(
      "Coaching",
    );
    expect(host.textContent).toContain("Fictional question?");
  });

  it.each([
    ["an empty content file", EMPTY],
    ["EXAMPLE content", parseGuide(example)],
    ["a file it could not read", null],
  ])("never shows %s", async (_, guide) => {
    await open(guide);
    expect(host.textContent).toContain("Dipak’s answers are on their way");
    expect(host.textContent).not.toContain("EXAMPLE");
    expect(host.textContent).not.toContain("People usually ask");
  });

  it("asks a signed-out visitor to sign in, and shows nothing of the guide", async () => {
    mocks.access = {
      status: "ready",
      authenticated: false,
      retry: () => {},
    } as WorkspaceAccessValue;
    await open(REAL);
    expect(host.textContent).toContain("Sign in for your Coaching");
    expect(host.textContent).not.toContain("Fictional question?");
  });

  it("shows the outline while it loads", async () => {
    await act(async () =>
      root.render(<GuidePage load={() => new Promise(() => {})} />),
    );
    expect(host.querySelector("[aria-busy='true']")).not.toBeNull();
    expect(host.textContent).not.toContain("on their way");
  });
});

describe("Coaching's way in", () => {
  it("draws nothing while the shipped content is empty", () => {
    expect(renderToStaticMarkup(<GuideEntry />)).toBe("");
    expect(
      renderToStaticMarkup(
        <GuideEntry
          summary={{ version: 1, shown: false, questions: 3, categories: [] }}
        />,
      ),
    ).toBe("");
  });

  it("is one row to the guide once real content is loaded", () => {
    const html = renderToStaticMarkup(
      <GuideEntry
        summary={{
          version: 4,
          shown: true,
          questions: 58,
          categories: ["objection handling", "closing", "discovery"],
        }}
      />,
    );
    expect(html).toContain('href="/coaching/guide"');
    expect(html).toContain("Dipak’s answers");
    expect(html).toContain(
      "Objection handling, closing and more · 58 questions",
    );
  });
});
