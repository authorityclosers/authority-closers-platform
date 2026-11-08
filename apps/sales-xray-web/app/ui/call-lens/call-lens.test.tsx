import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import { CallLens } from "./call-lens";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

it("says the outcome in words, its glyph in a lens a screen reader skips", () => {
  const onClick = vi.fn();
  act(() =>
    root.render(
      <CallLens href="/leads?view=to_call" onClick={onClick}>
        Call Rohan now
      </CallLens>,
    ),
  );
  const link = host.querySelector<HTMLAnchorElement>("a[data-call-lens]");
  expect(link?.getAttribute("href")).toBe("/leads?view=to_call");
  expect(link?.textContent).toBe("Call Rohan now");
  expect(link?.querySelector('[aria-hidden="true"]')).not.toBeNull();
  act(() => link?.click());
  expect(onClick).toHaveBeenCalledTimes(1);
});

/** WCAG relative luminance of a #rrggbb colour. */
const luminance = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const c = parseInt(hex.slice(at, at + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

it("fills at 7:1 against its label in both themes, for a phone in the sun", () => {
  // FRAMEWORK L4 (3 Nov 2026): key figures and the primary action at 7:1.
  const palette = readFileSync(
    join(
      process.cwd(),
      "../../packages/typescript/ui/src/kit/tokens/palette.css",
    ),
    "utf8",
  );
  const fills = [...palette.matchAll(/--lx-call: (#[0-9a-f]{6})/g)].map(
    ([, hex]) => hex,
  );
  const inks = [...palette.matchAll(/--lx-on-call: (#[0-9a-f]{6})/g)].map(
    ([, hex]) => hex,
  );
  expect(fills.length).toBeGreaterThanOrEqual(2);
  expect(fills.length).toBe(inks.length);
  fills.forEach((fill, index) =>
    expect(contrast(fill, inks[index])).toBeGreaterThanOrEqual(7),
  );
});
