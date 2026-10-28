import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";

import { SideScroll } from "./side-scroll";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

it("keeps the chosen item visible inside its row and fades only overflowing edges", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = (chosen: string) =>
    act(async () =>
      root.render(
        <SideScroll chosen={chosen} className="app-row">
          <button aria-pressed={chosen === "first"}>First</button>
          <button aria-pressed={chosen === "last"}>Last</button>
        </SideScroll>,
      ),
    );
  try {
    await render("first");
    const row = host.firstElementChild as HTMLElement;
    const last = row.lastElementChild as HTMLElement;
    Object.defineProperties(row, {
      clientWidth: { value: 100 },
      scrollWidth: { value: 400 },
    });
    Object.defineProperties(last, {
      offsetLeft: { value: 300 },
      offsetWidth: { value: 100 },
    });
    await render("last");
    expect(row.scrollLeft).toBeGreaterThanOrEqual(300);
    expect(row.classList.contains("app-row")).toBe(true);
    await act(async () => row.dispatchEvent(new Event("scroll")));
    expect(row.hasAttribute("data-less")).toBe(true);
    expect(row.hasAttribute("data-more")).toBe(false);
    await act(async () => {
      row.scrollLeft = 0;
      row.dispatchEvent(new Event("scroll"));
    });
    expect(row.hasAttribute("data-less")).toBe(false);
    expect(row.hasAttribute("data-more")).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
