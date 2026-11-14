/**
 * Ask Dipak in the app's own navigation (Dipak's spec, sections 2 and 3):
 * the middle tab opens his library and is lit there, the bottom bar keeps
 * its five tabs, and on his tab the bar's search is his Search and Saved
 * lessons (lit while Saved lessons is open). Elsewhere the bar is as before.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

const place = vi.hoisted(() => ({ path: "/ask-dipak", query: "view=saved" }));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  usePathname: () => place.path,
  useSearchParams: () => new URLSearchParams(place.query),
}));

import { AcquisitionShell } from "../acquisition-shell";

function shell() {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <AcquisitionShell authenticated active="coaching">
      <p>Page</p>
    </AcquisitionShell>,
  );
  return {
    nav: host.querySelector('nav[aria-label="Mobile Sales Xray navigation"]'),
    bar: host.querySelector("header"),
  };
}

it("lights Ask Dipak's tab on his library and carries his Search and Saved lessons in the bar", () => {
  place.path = "/ask-dipak";
  place.query = "view=saved";
  const { nav, bar } = shell();
  expect(
    Array.from(nav?.children ?? [], (item) => item.textContent?.trim()),
  ).toEqual(["Home", "Leads", "Ask Dipak", "Reports", "Growth"]);
  const tab = nav?.querySelector('a[href="/ask-dipak"]');
  expect(tab?.getAttribute("aria-current")).toBe("page");
  expect(nav?.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
  expect(
    bar?.querySelector('button[aria-label="Search questions"]'),
  ).not.toBeNull();
  expect(
    bar
      ?.querySelector('button[aria-label="Saved questions"]')
      ?.getAttribute("aria-current"),
  ).toBe("page");
  expect(bar?.querySelector('button[aria-label="Search"]')).toBeNull();
});

it("leaves the bookmark unlit on his other screens", () => {
  place.path = "/ask-dipak";
  place.query = "lesson=PB03";
  const { bar } = shell();
  expect(
    bar
      ?.querySelector('button[aria-label="Saved questions"]')
      ?.getAttribute("aria-current"),
  ).toBeNull();
});

it("keeps the app's own search on every other tab", () => {
  place.path = "/growth";
  place.query = "";
  const { nav, bar } = shell();
  expect(
    nav?.querySelector('a[href="/ask-dipak"]')?.getAttribute("aria-current"),
  ).toBeNull();
  expect(bar?.querySelector('button[aria-label="Search"]')).not.toBeNull();
  expect(bar?.querySelector('button[aria-label="Saved questions"]')).toBeNull();
});
