import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { nativeHttpDiagnosticsEnabled } from "./dev-media-native-privacy";

const guardFile = path.resolve(__dirname, "dev-media-native-privacy.ts");

function nativeProbe(
  mask: string,
  guarded: boolean,
  clearAfterImport = false,
  protocol = "https",
) {
  const child = spawnSync(
    process.execPath,
    [
      "-e",
      `
      if (${clearAfterImport}) process.env.NODE_DEBUG = '';
      const guard = require(${JSON.stringify(guardFile)});
      const https = require('node:' + ${JSON.stringify(protocol)});
      let refused = false;
      try {
        if (${guarded}) guard.assertDevelopmentMediaNativePrivacy();
        const request = https.request(${JSON.stringify(protocol)} + '://127.0.0.1:1/v1/media/playback/fixture?token=synthetic-invalid-native-privacy', {
          headers: { cookie: '__Host-ac_session=synthetic-invalid-session-marker' }, agent: false
        });
        request.on('error', () => {});
        request.destroy();
      } catch { refused = true; }
      process.stdout.write(JSON.stringify({ refused }));
      `,
    ],
    {
      env: { ...process.env, NODE_DEBUG: mask },
      encoding: "utf8",
      timeout: 5000,
      windowsHide: true,
    },
  );
  expect(child.error).toBeUndefined();
  expect(child.status).toBe(0);
  return {
    ...JSON.parse(child.stdout),
    tokenLogged: child.stderr.includes("synthetic-invalid-native-privacy"),
    cookieLogged: child.stderr.includes("synthetic-invalid-session-marker"),
  };
}

describe("native media diagnostic privacy", () => {
  it.each([
    "http",
    "HTTPS",
    "http,https",
    "*",
    "h*",
    "fs,h*ps",
    "http*",
    "net",
    "TLS",
    "tls,net",
    "n*",
  ])("matches Node native network diagnostic mask %s", (mask) =>
    expect(nativeHttpDiagnosticsEnabled(mask)).toBe(true),
  );
  it.each([undefined, "", "fs", "https-extra", "https ", "h.ttps", "[https]"])(
    "does not widen Node's mask semantics for %s",
    (mask) => expect(nativeHttpDiagnosticsEnabled(mask)).toBe(false),
  );
  it.each(["https", "http,https", "*"])(
    "reproduces the installed native sink without sending a request (%s)",
    (mask) => {
      expect(nativeProbe(mask, false)).toEqual({
        refused: false,
        tokenLogged: true,
        cookieLogged: true,
      });
    },
  );
  it.each(["https", "HTTP,HTTPS", "*", "h*", "net", "tls", "tls,net", "n*"])(
    "refuses the unsafe process before native request construction (%s)",
    (mask) => {
      expect(nativeProbe(mask, true)).toEqual({
        refused: true,
        tokenLogged: false,
        cookieLogged: false,
      });
    },
  );
  it.each(["https", "net", "tls", "tls,net"])(
    "detects Node's cached unsafe mask even if cleared before application import (%s)",
    (mask) => {
      expect(nativeProbe(mask, true, true)).toEqual({
        refused: true,
        tokenLogged: false,
        cookieLogged: false,
      });
    },
  );
  it("reproduces NET credential logging without making a network connection", () => {
    expect(nativeProbe("net", false, false, "http")).toMatchObject({
      refused: false,
      cookieLogged: true,
    });
  });
  it("allows the launcher-cleared process without credential diagnostics", () => {
    expect(nativeProbe("", true)).toEqual({
      refused: false,
      tokenLogged: false,
      cookieLogged: false,
    });
  });
  it("resets only the learner-child mask before its managed process starts", () => {
    const launcher = readFileSync(
      path.resolve(
        __dirname,
        "../../../../scripts/Start-LocalStagingBridge.ps1",
      ),
      "utf8",
    );
    const assignment = '$LearnerEnvironment["NODE_DEBUG"] = ""';
    expect(launcher).toContain(assignment);
    expect(launcher.indexOf(assignment)).toBeLessThan(
      launcher.indexOf("$LearnerProcess = Start-Process"),
    );
    expect(launcher).not.toMatch(/\$env:NODE_DEBUG\s*=/i);
  });
});
