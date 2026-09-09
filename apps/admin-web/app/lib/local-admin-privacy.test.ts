import { spawnSync } from "node:child_process";
import path from "node:path";

import { describe, expect, it } from "vitest";

const transport = path.resolve(__dirname, "local-admin-transport.ts");

function probe(startup: string, current?: string, clearBeforeImport = false) {
  const child = spawnSync(
    process.execPath,
    [
      "-e",
      `
    (async () => {
      if (${clearBeforeImport}) process.env.NODE_DEBUG = '';
      const transport = require(${JSON.stringify(transport)});
      if (${current !== undefined}) process.env.NODE_DEBUG = ${JSON.stringify(current ?? "")};
      let refused = false;
      try {
        await transport.fetchLocalAdminWire('http://127.0.0.1:1/v1/me', {
          headers: {cookie: 'ac_session=synthetic-invalid-admin-privacy'},
          signal: AbortSignal.abort()
        });
      } catch (error) { refused = error.message.startsWith('Local admin requires native HTTP diagnostics'); }
      process.stdout.write(JSON.stringify({refused}));
    })();
  `,
    ],
    {
      env: { ...process.env, NODE_DEBUG: startup },
      encoding: "utf8",
      timeout: 5000,
      windowsHide: true,
    },
  );
  expect(child.error).toBeUndefined();
  expect(child.status).toBe(0);
  expect(child.stderr).not.toContain("synthetic-invalid-admin-privacy");
  return JSON.parse(child.stdout).refused as boolean;
}

describe("local admin native diagnostic privacy", () => {
  it.each(["http", "HTTPS", "*", "h*", "fs,http*", "net", "tls,net", "tls"])(
    "refuses startup mask %s before constructing the credentialed request",
    (mask) => {
      expect(probe(mask)).toBe(true);
    },
  );
  it("still refuses cached startup logging if the environment is cleared before import", () => {
    expect(probe("http", undefined, true)).toBe(true);
  });
  it("refuses diagnostics enabled after application import", () => {
    expect(probe("", "HTTP,HTTPS")).toBe(true);
  });
  it.each(["", "fs", "http-extra"])(
    "allows diagnostic-safe mask %s",
    (mask) => {
      expect(probe(mask)).toBe(false);
    },
  );
});
