import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  deskLink,
  fromPage,
  leadLink,
  parseContact,
  phoneFromTel,
} from "../lead-link.js";

test("reads a contact from selected text", () => {
  assert.deepEqual(parseContact("Asha Patil\n+91 98765 43210"), {
    name: "Asha Patil",
    phone: "+919876543210",
    email: undefined,
  });
  assert.deepEqual(
    parseContact("Name: Ravi Kumar\nPhone: 91234-56780\nravi@example.com"),
    { name: "Ravi Kumar", phone: "9123456780", email: "ravi@example.com" },
  );
  assert.equal(parseContact("call me on 98765 43210").phone, "9876543210");
  assert.equal(parseContact("12345").phone, undefined);
});

test("puts the lead after # so it never reaches a server", () => {
  const link = leadLink("live", {
    name: " Asha Patil ",
    phone: "+91 98765 43210",
    note: "Added from linkedin.com",
  });
  const url = new URL(link);
  assert.equal(url.origin, "https://salesxray.authorityclosers.com");
  assert.equal(url.pathname, "/leads");
  assert.equal(url.search, "");
  const params = new URLSearchParams(url.hash.slice(1));
  assert.equal(params.get("add"), "lead");
  assert.equal(params.get("name"), "Asha Patil");
  assert.equal(params.get("phone"), "+91 98765 43210");
  assert.equal(params.get("email"), null);
});

test("bounds every field and picks the site", () => {
  const params = new URLSearchParams(
    new URL(leadLink("dev", { name: "x".repeat(500) })).hash.slice(1),
  );
  assert.equal(params.get("name").length, 200);
  assert.ok(
    leadLink("dev", { name: "A" }).startsWith("https://salesxray-dev."),
  );
  assert.ok(leadLink("other", { name: "A" }).startsWith("https://salesxray."));
  assert.equal(
    deskLink("live"),
    "https://salesxray.authorityclosers.com/leads",
  );
});

test("names the page by its site only", () => {
  assert.equal(
    fromPage("https://www.linkedin.com/in/asha-patil?trk=x"),
    "Added from linkedin.com",
  );
  assert.equal(fromPage("not a url"), "");
  assert.equal(phoneFromTel("tel:%2B91%2098765%2043210"), "+91 98765 43210");
});

test("asks for no site access up front", () => {
  const manifest = JSON.parse(
    readFileSync(new URL("../manifest.json", import.meta.url), "utf8"),
  );
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.host_permissions, undefined);
  assert.deepEqual(manifest.optional_host_permissions, [
    "https://web.whatsapp.com/*",
  ]);
  assert.deepEqual(manifest.permissions.sort(), [
    "contextMenus",
    "scripting",
    "storage",
  ]);
});
