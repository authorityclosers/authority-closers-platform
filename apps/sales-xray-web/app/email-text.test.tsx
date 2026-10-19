import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { EmailText } from "./email-text";

// Cloudflare's scrape shield looks for a whole address in the served HTML.
const ADDRESS = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;

it("serves an address that obfuscation cannot match, and reads the same", () => {
  const html = renderToStaticMarkup(
    <a href="mailto:admin@authorityclosers.com">
      <EmailText address="admin@authorityclosers.com" />
    </a>,
  );
  expect(html.replace(/href="[^"]*"/, "")).not.toMatch(ADDRESS);
  expect(html.replace(/<[^>]+>/g, "")).toBe("admin@authorityclosers.com");
});

it("leaves text without an address alone", () => {
  expect(renderToStaticMarkup(<EmailText address="Contact us" />)).toBe(
    "Contact us",
  );
});
