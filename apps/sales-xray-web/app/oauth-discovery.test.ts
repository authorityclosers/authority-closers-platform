import { describe, expect, it } from "vitest";

import { GET as serverMetadata } from "./.well-known/oauth-authorization-server/route.discovery";
import { GET as openIdMetadata } from "./.well-known/openid-configuration/route.discovery";
import { GET as resourceMetadata } from "./.well-known/oauth-protected-resource/[[...resource]]/route.discovery";
import {
  authorizationServerMetadata,
  protectedResourceMetadata,
  publicOrigin,
} from "./oauth-discovery";

// fetch's Request drops a Host header, so the proxy's forwarded host stands in.
const at = (host: string, path = "/") =>
  new Request(`http://internal${path}`, {
    headers: { "x-forwarded-host": host },
  });

describe("OAuth discovery", () => {
  it("answers only for Sales X-Ray's own hosts", () => {
    const of = (host: string) => publicOrigin(new Headers({ host }));
    expect(of("salesxray.authorityclosers.com")).toBe(
      "https://salesxray.authorityclosers.com",
    );
    expect(of("salesxray-dev.authorityclosers.com")).toBe(
      "https://salesxray-dev.authorityclosers.com",
    );
    expect(of("127.0.0.1:3026")).toBe("http://127.0.0.1:3026");
    expect(of("evil.example")).toBeNull();
    expect(of("salesxray.authorityclosers.com.evil.example")).toBeNull();
    expect(
      publicOrigin(
        new Headers({
          host: "127.0.0.1:3026",
          "x-forwarded-host": "salesxray-dev.authorityclosers.com",
        }),
      ),
    ).toBe("https://salesxray-dev.authorityclosers.com");
  });

  it("describes Connect and the MCP server", async () => {
    const origin = "https://salesxray.authorityclosers.com";
    const meta = authorizationServerMetadata(origin);
    expect(meta.authorization_endpoint).toBe(`${origin}/connect`);
    expect(meta.registration_endpoint).toBe(`${origin}/v1/oauth/register`);
    expect(meta.code_challenge_methods_supported).toEqual(["S256"]);
    expect(protectedResourceMetadata(origin, "/v1/mcp")).toMatchObject({
      resource: `${origin}/v1/mcp`,
      authorization_servers: [origin],
    });
    expect(protectedResourceMetadata(origin, "")?.resource).toBe(
      `${origin}/v1/mcp`,
    );
    expect(protectedResourceMetadata(origin, "/v1/admin")).toBeNull();

    const served = await serverMetadata(
      at("salesxray.authorityclosers.com"),
    ).json();
    expect(served.issuer).toBe(origin);
    expect(serverMetadata(at("evil.example")).status).toBe(404);
    const oidc = await openIdMetadata(
      at("salesxray.authorityclosers.com"),
    ).json();
    expect(oidc.registration_endpoint).toBe(`${origin}/v1/oauth/register`);
    expect(
      protectedResourceMetadata(origin, "/v1/mcp")?.scopes_supported,
    ).toEqual([
      "calls:read",
      "reports:read",
      "leads:read",
      "leads:write",
      // AI writes (docs/product/ai-writes.md): notes and tasks, each its own scope.
      "leads:notes",
      "leads:tasks",
    ]);
    const resource = await resourceMetadata(
      at("salesxray.authorityclosers.com"),
      { params: Promise.resolve({ resource: ["v1", "mcp"] }) },
    );
    expect((await resource.json()).resource).toBe(`${origin}/v1/mcp`);
  });
});
