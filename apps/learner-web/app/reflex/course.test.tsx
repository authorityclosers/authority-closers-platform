// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { CourseScreen } from "./course";
import { apiMock, assertCopy, harness, program } from "./test-support";
describe("Reflex course and module", () => {
  const h = harness();
  it("shows course artwork and progress, continue and all module states", async () => {
    await h.mount(<CourseScreen slug={program.slug} api={apiMock()} />);
    expect(h.el.textContent).toContain("40% complete");
    expect(h.el.querySelector("img")).toBeTruthy();
    expect(h.el.textContent).toContain("Lesson by Dipak Vishwakarma");
    expect(h.link("Continue")?.getAttribute("href")).toBe("/activity/next");
    expect(h.link("Listen first")?.getAttribute("href")).toContain(
      "/module/module-a",
    );
    const rows = h.el.querySelectorAll("li");
    expect(rows[0].textContent).toContain("1/2 steps done");
    expect(rows[0].textContent).toContain("In progress");
    expect(rows[1].textContent).toContain("Locked");
    expect(rows[1].textContent).toContain("Finish the earlier required steps");
    expect(rows[1].querySelector("a")).toBeNull();
    expect(rows[1].querySelector("svg")).toBeTruthy();
    expect(rows[2].textContent).toContain("Done");
    expect(rows[3].textContent).toContain("Available");
    assertCopy(h.el);
  });
  it("lists module steps by kind and state and never links locked steps", async () => {
    await h.mount(
      <CourseScreen slug={program.slug} moduleId="module-a" api={apiMock()} />,
    );
    expect(h.el.querySelector("h2")?.textContent).toBe("Listen first");
    expect(h.link("Step done")?.getAttribute("href")).toBe("/activity/done");
    expect(h.link("Step next")?.getAttribute("href")).toBe("/activity/next");
    expect(h.el.textContent).toContain("Watch");
    expect(h.el.textContent).toContain("Reflect");
    assertCopy(h.el);
    await h.mount(
      <CourseScreen slug={program.slug} moduleId="module-b" api={apiMock()} />,
    );
    expect(h.el.textContent).toContain("Locked");
    expect(h.el.querySelector('a[href="/activity/locked"]')).toBeNull();
    expect(h.el.textContent).toContain("Finish the earlier required modules");
    assertCopy(h.el);
  });
  it("does not invent modules or activities and exposes a retry on failed reads", async () => {
    await h.mount(
      <CourseScreen slug={program.slug} moduleId="missing" api={apiMock()} />,
    );
    expect(h.el.textContent).toContain("isn’t available");
    const api = apiMock();
    vi.mocked(api.learning).mockRejectedValue(new Error("fixture"));
    await h.mount(<CourseScreen slug={program.slug} api={api} />);
    expect(h.button("Try again")).toBeTruthy();
    assertCopy(h.el);
  });
  it("preserves course and module loading simulations", async () => {
    await h.mount(<CourseScreen slug={program.slug} state="LOADING" />);
    expect(h.el.querySelector('[aria-label="Loading"]')).toBeTruthy();
    await h.mount(
      <CourseScreen slug={program.slug} moduleId="module-a" state="LOCKED" />,
    );
    expect(h.el.textContent).toContain("Finish the earlier steps first.");
    assertCopy(h.el);
  });
});
