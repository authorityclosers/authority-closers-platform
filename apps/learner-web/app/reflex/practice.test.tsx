// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { PracticeHub } from "./practice";
import { assertCopy, engineMock, harness } from "./test-support";
import type { PracticeApi } from "../lib/practice-api";
const catalog = () =>
  ({
    catalog: vi.fn().mockResolvedValue({
      items: [
        {
          id: "next-move",
          title: "One clear question",
          kind: "choice",
          estimated_minutes: 4,
        },
        {
          id: "listen",
          title: "Listen carefully",
          kind: "audio",
          estimated_minutes: 2,
        },
      ],
    }),
  }) as unknown as PracticeApi;
describe("Reflex Practice hub", () => {
  const h = harness();
  it("shows seven weekly day dots and a real daily set link", async () => {
    const api = catalog();
    const engine = engineMock();
    await h.mount(<PracticeHub api={api} engineApi={engine} />);
    expect(
      h.el.querySelectorAll('ol[aria-label="Practice days this week"] li'),
    ).toHaveLength(7);
    expect(h.el.querySelectorAll("li[data-done]")).toHaveLength(3);
    expect(h.el.textContent).toContain("3 of 7 days practised this week");
    expect(h.link("Start today’s set")?.getAttribute("href")).toBe(
      "/practice?set=next-move",
    );
    expect(h.link("Listen carefully")?.getAttribute("href")).toBe(
      "/practice?set=listen",
    );
    expect(h.el.textContent).toContain("Listening");
    expect(h.el.textContent).toContain("About 2 min");
    expect(engine.issue).not.toHaveBeenCalled();
    assertCopy(h.el);
  });
  it("offers the last five attempts using the existing resume parameters", async () => {
    await h.mount(<PracticeHub api={catalog()} engineApi={engineMock()} />);
    expect(h.link("Practice 0")?.getAttribute("href")).toBe(
      "/practice?set=next-move&attempt=attempt-0",
    );
    expect(h.link("Practice 4")).toBeTruthy();
    expect(h.link("Practice 5")).toBeNull();
    assertCopy(h.el);
  });
  it("handles loading, an empty library and failed progress without invented numbers", async () => {
    await h.mount(<PracticeHub state="LOADING" />);
    expect(h.el.querySelector('[aria-label="Loading"]')).toBeTruthy();
    const api = catalog();
    vi.mocked(api.catalog).mockResolvedValue({
      mode: "published",
      items: [],
      responses_stored: true,
      course_progress_affected: false,
    });
    await h.mount(<PracticeHub api={api} engineApi={engineMock()} />);
    expect(h.el.textContent).toContain("New practice sets are on the way.");
    assertCopy(h.el);
    const engine = engineMock();
    vi.mocked(engine.progress).mockRejectedValue(new Error("fixture"));
    await h.mount(<PracticeHub api={api} engineApi={engine} />);
    expect(h.button("Try again")).toBeTruthy();
    expect(h.el.textContent).not.toContain("0 of 7");
    assertCopy(h.el);
  });
});
