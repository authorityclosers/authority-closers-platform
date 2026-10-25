import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./.well-known/openai-apps-challenge/route.discovery";
import {
  challengeToken,
  PRODUCTION_CHALLENGE,
  PRODUCTION_HOST,
} from "./openai-apps-challenge";

const TOKEN = "oa-challenge.Example_token-123";

// fetch's Request drops a Host header, so the proxy's forwarded host stands in.
function request(host: string) {
  return new Request(`https://${host}/.well-known/openai-apps-challenge`, {
    headers: { "x-forwarded-host": host },
  });
}

describe("ChatGPT domain verification", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("answers the configured token as plain text, never cached", async () => {
    vi.stubEnv("AC_OPENAI_APPS_CHALLENGE", ` ${TOKEN}\n`);
    const answer = GET(request("salesxray-dev.authorityclosers.com"));
    expect(answer.status).toBe(200);
    expect(answer.headers.get("content-type")).toBe(
      "text/plain; charset=utf-8",
    );
    expect(answer.headers.get("cache-control")).toBe("no-store");
    expect(await answer.text()).toBe(TOKEN);
  });

  it("is a 404 with no token, a malformed one, or another site", () => {
    expect(GET(request(PRODUCTION_HOST)).status).toBe(
      PRODUCTION_CHALLENGE ? 200 : 404,
    );
    vi.stubEnv("AC_OPENAI_APPS_CHALLENGE", "<script>x</script>");
    expect(GET(request("salesxray-dev.authorityclosers.com")).status).toBe(404);
    vi.stubEnv("AC_OPENAI_APPS_CHALLENGE", TOKEN);
    expect(GET(request("example.com")).status).toBe(404);
  });

  it("keeps the production token to the production host", () => {
    expect(challengeToken("salesxray-staging.authorityclosers.com", "")).toBe(
      null,
    );
    expect(challengeToken(PRODUCTION_HOST, undefined)).toBe(
      PRODUCTION_CHALLENGE || null,
    );
    expect(challengeToken(PRODUCTION_HOST, TOKEN)).toBe(TOKEN);
    expect(challengeToken(PRODUCTION_HOST, "short")).toBe(
      PRODUCTION_CHALLENGE || null,
    );
  });
});
