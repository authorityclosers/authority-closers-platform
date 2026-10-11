import { describe, expect, it } from "vitest";

import {
  JOURNEYS,
  journeyApi,
  OVERLAYS,
  silentWav,
  VARIANTS,
} from "./release-journeys.mjs";
import { MIN_RULES } from "./style-audit.mjs";

describe("release journeys (AUT-1663, owner 11 Oct 03:30 IST)", () => {
  it("walks the owner's flows at 1440 and 390 in light and dark", () => {
    expect(Object.keys(JOURNEYS)).toEqual([
      "sign-in",
      "calls",
      "new-analysis",
      "coaching",
      "settings",
    ]);
    expect(VARIANTS.map(([width, , scheme]) => `${width} ${scheme}`)).toEqual([
      "1440 light",
      "1440 dark",
      "390 light",
      "390 dark",
    ]);
    expect(Object.keys(OVERLAYS)).toEqual([
      "workspace switcher",
      "profile menu",
      "account card",
      "settings",
    ]);
  });

  it("signs in only through the password call, and records any other write", () => {
    const api = journeyApi({ signedIn: false });
    expect(api.respond("GET", "/v1/me/workspaces", "").status).toBe(401);
    expect(api.respond("POST", "/v1/auth/password/login", "").status).toBe(200);
    expect(api.respond("GET", "/v1/me/workspaces", "").status).toBe(200);
    expect(
      api.respond("POST", "/v1/conversation/acquisition/submissions", "")
        .status,
    ).toBe(409);
    expect(api.state.writes).toEqual([
      "POST /v1/conversation/acquisition/submissions",
    ]);
  });

  it("serves the studio a valid entry and a read that keeps failing on request", () => {
    const api = journeyApi({
      failing: ["/v1/conversation/acquisition/submissions/summary"],
    });
    const entry = api.respond("GET", "/v1/conversation/acquisition/entry", "");
    expect(entry.body.allowance_seconds).toBeLessThanOrEqual(6000);
    expect(
      api.respond("GET", "/v1/conversation/acquisition/submissions/summary", "")
        .status,
    ).toBe(503);
  });

  it("picks a real (silent) WAV recording", () => {
    const wav = silentWav(1, 8000);
    expect(wav.toString("ascii", 0, 4)).toBe("RIFF");
    expect(wav.toString("ascii", 8, 12)).toBe("WAVE");
    expect(wav.readUInt32LE(24)).toBe(8000);
    expect(wav.length).toBe(44 + 16000);
  });

  it("asks the style audit for a real stylesheet's worth of rules", () => {
    expect(MIN_RULES).toBeGreaterThanOrEqual(300);
  });
});
