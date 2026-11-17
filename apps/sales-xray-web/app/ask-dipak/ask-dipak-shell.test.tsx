/**
 * Ask Dipak in the app's own navigation (Dipak's spec, sections 2 and 3):
 * the middle tab opens his library and is lit there, the bottom bar keeps
 * its five tabs, and on his tab the bar's search is his Search. The bar
 * keeps Home's set, so the workspace's name keeps its room (owner, 16 Nov
 * 2026: "the name of the organization is lost"). Elsewhere it is as before.
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

it("lights Ask Dipak's tab on his library and carries his Search, alone, in the bar", () => {
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
  expect(bar?.querySelector('button[aria-label="Search"]')).toBeNull();
  // No bookmark beside it: the bar is Home's, so the name isn't squeezed.
  expect(bar?.querySelector('button[aria-label="Saved questions"]')).toBeNull();
});

it("gives the bar as many buttons on Ask Dipak as on Home", () => {
  const count = () => shell().bar?.querySelectorAll("button, a").length;
  place.path = "/ask-dipak";
  place.query = "";
  const ask = count();
  place.path = "/dashboard";
  const home = count();
  expect(ask).toBe(home);
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

it("shows no page-title row on Ask Dipak: the tab bar says it (owner, 17 Nov 2026)", () => {
  const titleRow = (path: string) => {
    place.path = path;
    place.query = "";
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <AcquisitionShell authenticated active="coaching" pageName="Ask Dipak">
        <p>Page</p>
      </AcquisitionShell>,
    );
    return host.querySelector("[data-page-title]");
  };
  expect(titleRow("/ask-dipak")).toBeNull();
  // Other pages keep theirs.
  expect(titleRow("/growth")?.textContent).toBe("Ask Dipak");
});
