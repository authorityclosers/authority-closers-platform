// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { LearnScreen } from "./learn";
import { apiMock, assertCopy, harness, program } from "./test-support";
import LearnPage from "../(app)/learning/page";
import DiscoverPage from "../(app)/discover/page";
const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
describe("Reflex Learn", () => {
  const h = harness();
  it("lists enrolled courses with artwork, progress and their next step", async () => {
    await h.mount(<LearnScreen api={apiMock()} />);
    expect(h.el.textContent).toContain("Step next");
    expect(h.el.textContent).toContain("40% complete");
    expect(h.link(program.title)?.getAttribute("href")).toBe(
      `/learn/${program.slug}`,
    );
    expect(h.el.querySelector("img")).toBeTruthy();
    assertCopy(h.el);
    await h.click(h.button("Explore"));
    expect(navigation.replace).toHaveBeenCalledWith("/learning?view=explore", {
      scroll: false,
    });
  });
  it("routes enrolled catalogue courses to Continue and others to View course", async () => {
    const api = apiMock();
    vi.mocked(api.listPrograms).mockResolvedValue({
      items: [
        program,
        {
          ...program,
          id: "course-b",
          slug: "ask-clearly",
          title: "Ask clearly",
          module_count: 3,
        },
      ],
      next_cursor: null,
    } as Awaited<ReturnType<typeof api.listPrograms>>);
    await h.mount(<LearnScreen api={api} view="explore" />);
    expect(h.el.textContent).toContain("Courses from Closers' Academy");
    expect(h.el.textContent).toContain("3 modules");
    expect(h.link("Continue")?.getAttribute("href")).toBe(
      `/learn/${program.slug}`,
    );
    expect(h.link("View course")?.getAttribute("href")).toBe(
      "/programs/ask-clearly",
    );
    await h.click(h.button("My courses"));
    expect(navigation.replace).toHaveBeenCalledWith("/learning", {
      scroll: false,
    });
    assertCopy(h.el);
  });
  it("selects Explore from the query and keeps old discover links working", async () => {
    const page = await LearnPage({
      searchParams: Promise.resolve({ view: "explore", state: "empty" }),
    });
    expect(page.props.children[1].props.view).toBe("explore");
    await h.mount(page);
    expect(h.button("Explore")?.getAttribute("aria-pressed")).toBe("true");
    const old = await DiscoverPage({ searchParams: Promise.resolve({}) });
    expect(old.props.children[1].props.view).toBe("explore");
    assertCopy(h.el);
  });
  it("offers Explore when no courses have been started", async () => {
    await h.mount(<LearnScreen api={apiMock([])} />);
    expect(h.el.textContent).toContain("You haven’t started a course yet");
    expect(h.link("Explore")?.getAttribute("href")).toBe(
      "/learning?view=explore",
    );
    assertCopy(h.el);
  });
  it("gives a truthful empty catalogue and loading/error states", async () => {
    const api = apiMock([]);
    vi.mocked(api.listPrograms).mockResolvedValue({
      items: [],
      next_cursor: null,
    });
    await h.mount(<LearnScreen api={api} view="explore" />);
    expect(h.el.textContent).toContain("New courses are on the way.");
    assertCopy(h.el);
    await h.mount(<LearnScreen state="LOADING" />);
    expect(h.el.querySelector('[aria-label="Loading"]')).toBeTruthy();
    vi.mocked(api.learningCollection).mockRejectedValue(new Error("fixture"));
    await h.mount(<LearnScreen api={api} />);
    expect(h.button("Try again")).toBeTruthy();
    assertCopy(h.el);
  });
});
