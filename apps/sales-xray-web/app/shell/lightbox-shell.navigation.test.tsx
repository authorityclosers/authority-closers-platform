import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href} data-next-client-link="true">
      {children}
    </a>
  ),
}));

import { AcquisitionShell } from "../acquisition-shell";

it("keeps same-shell navigation on the App Router client-link path", () => {
  const html = renderToStaticMarkup(
    <AcquisitionShell authenticated homeHref="/sales-xray">
      <p>Workspace</p>
    </AcquisitionShell>,
  );
  const host = document.createElement("div");
  host.innerHTML = html;

  const workspaceNav = host.querySelector('nav[aria-label="Workspace"]');
  const mobileNav = host.querySelector(
    'nav[aria-label="Mobile Sales Xray navigation"]',
  );
  expect(
    workspaceNav?.querySelector('a[data-next-client-link="true"]')?.getAttribute("href"),
  ).toBe("/sales-xray?new=1");
  expect(
    mobileNav?.querySelector('a[data-next-client-link="true"]')?.getAttribute("href"),
  ).toBe("/sales-xray?new=1");
  expect(
    workspaceNav?.querySelector('a[href="/calls"][data-next-client-link="true"]'),
  ).not.toBeNull();
  expect(host.querySelector('button.account-nav-signout')).toBeNull();
});
