// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { activityMediaIdentity } from "./activity-media-identity";
import type { ActivityResponse } from "./learner-api";

const origin = "https://learn.authorityclosers.test";
const issued = Date.parse("2026-09-08T10:00:00Z") / 1000;
const baseClaims = {
  typ: "AC-MEDIA",
  token_type: "playback",
  iat: issued,
  exp: issued + 300,
  tenant_id: "tenant-1",
  person_id: "person-1",
  session_id: "identity-session-1",
  activity_id: "activity-1",
  activity_version: "published-1",
  asset_id: "asset-1",
  version_id: "version-1",
  binding_id: "binding-1",
  enrollment_id: "enrollment-1",
  delivery_grant_id: "grant-1",
  supports_range: false,
  nonce: "synthetic_nonce_1",
};
function encode(value: Record<string, unknown>) {
  return Buffer.from(
    JSON.stringify(
      Object.fromEntries(
        Object.entries(value).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
      ),
    ),
  ).toString("base64url");
}
function url(
  key: string,
  claims: Record<string, unknown>,
  selectedOrigin = origin,
) {
  // Synthetic, structurally valid data only; this is not a signature proof.
  return `${selectedOrigin}/v1/media/playback/${encodeURIComponent(key)}?token=AC-MEDIA.${encode({ ...claims, key })}.${"A".repeat(43)}`;
}
function fixture(
  changes: Record<string, unknown> = {},
  selectedOrigin = origin,
) {
  const claims = { ...baseClaims, ...changes };
  const prefix = `tenants/${claims.tenant_id}/media/video/${claims.asset_id}/${claims.version_id}/original`;
  const manifest = url(
    `${prefix}/renditions/hls/master.m3u8`,
    claims,
    selectedOrigin,
  );
  const progressive = url(
    `${prefix}/renditions/progressive.mp4`,
    { ...claims, supports_range: true },
    selectedOrigin,
  );
  const caption = url(
    `${prefix}/captions/en/captions/caption-1`,
    { ...claims, nonce: "separate_caption_nonce" },
    selectedOrigin,
  );
  const activity: ActivityResponse = {
    id: String(claims.activity_id),
    module_id: "module-1",
    program_id: "program-1",
    program_version_id: "program-version-1",
    enrollment_id: String(claims.enrollment_id),
    position: 1,
    kind: "video",
    title: "Synthetic lesson",
    prompt: null,
    state: "available",
    revision: 0,
    required: true,
    explanation: {
      activity_id: String(claims.activity_id),
      state: "available",
      required: true,
      reason: "available",
      missing_activity_ids: [],
      missing_module_ids: [],
    },
    allowed_actions: [],
    draft_revision: 0,
    draft_payload: null,
    media: {
      state: "approved",
      reason: "approved_media_delivery_available",
      binding_id: String(claims.binding_id),
      media_id: String(claims.asset_id),
      media_version_id: String(claims.version_id),
      activity_version: String(claims.activity_version),
      content_type: "video/mp4",
      duration_seconds: 1200,
      width: 3840,
      height: 2160,
      renditions: [
        {
          id: "hls-1",
          protocol: "hls",
          content_type: "application/vnd.apple.mpegurl",
          width: null,
          height: null,
          bitrate_kbps: null,
        },
      ],
      captions: [
        {
          id: "caption-1",
          media_version_id: String(claims.version_id),
          language: "en",
          kind: "captions",
          state: "ready",
          content_type: "text/vtt",
          is_default: true,
          source_url: caption,
          created_at: "2026-09-08T09:00:00Z",
        },
      ],
      playback_available: true,
      delivery: {
        protocol: "hls",
        manifest_url: manifest,
        progressive_url: progressive,
      },
    },
  };
  return {
    activity,
    media: { protocol: "hls", src: manifest, fallback: { src: progressive } },
  };
}
type Fixture = ReturnType<typeof fixture>;
function result(input = fixture(), mode = "read-only") {
  return activityMediaIdentity(input.activity, input.media, mode);
}
function changeUrl(
  source: string,
  changes: Record<string, unknown>,
  remove: string[] = [],
) {
  const parsed = new URL(source);
  const payload = JSON.parse(
    Buffer.from(
      parsed.searchParams.get("token")!.split(".")[1],
      "base64url",
    ).toString("utf8"),
  );
  Object.assign(payload, changes);
  for (const key of remove) delete payload[key];
  return url(
    decodeURIComponent(parsed.pathname.slice("/v1/media/playback/".length)),
    payload,
    parsed.origin,
  );
}
function replacePrimary(input: Fixture, source: string) {
  input.media.src = source;
  input.activity.media!.delivery!.manifest_url = source;
}
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("application media rotation identity", () => {
  it("pins full content and identity while exposing the primary generation", () => {
    const value = result();
    expect(value).toEqual({
      identity: expect.stringContaining("ac-activity-media-v1"),
      issuedAt: issued * 1000,
      expiresAt: (issued + 300) * 1000,
      grantId: "grant-1",
    });
    expect(value!.identity).not.toContain("AC-MEDIA.");
    expect(value!.identity).not.toContain("synthetic_nonce_1");
  });
  it("compares different complete grant generations without extending either expiry", () => {
    const first = result()!;
    const next = result(
      fixture({
        delivery_grant_id: "grant-2",
        iat: issued + 290,
        exp: issued + 590,
        nonce: "nonce_2",
      }),
    )!;
    expect(next.identity).toBe(first.identity);
    expect(next.grantId).not.toBe(first.grantId);
    expect(next.issuedAt).toBe((issued + 290) * 1000);
    expect(first.expiresAt).toBe((issued + 300) * 1000);
  });
  it("recognizes re-signing one grant without treating its nonce as identity", () => {
    expect(result(fixture({ nonce: "another_nonce" }))).toEqual(result());
    const input = fixture();
    replacePrimary(
      input,
      input.media.src.replace(
        /A{43}$/,
        Buffer.alloc(32, 1).toString("base64url"),
      ),
    );
    expect(result(input)).toEqual(result());
  });
  it("can compare an expired original independent of current time", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2036-09-08T10:00:00Z"));
    expect(result()).not.toBeNull();
    vi.setSystemTime(new Date("2000-01-01T00:00:00Z"));
    expect(result()).not.toBeNull(); // Fresh playback validation owns future/expiry checks.
  });
  it.each([
    "tenant_id",
    "person_id",
    "session_id",
    "activity_id",
    "activity_version",
    "asset_id",
    "version_id",
    "binding_id",
    "enrollment_id",
  ])("never treats changed %s as generation-only rotation", (field) => {
    const changed = result(fixture({ [field]: "different-scope" }));
    expect(changed).not.toBeNull();
    expect(changed!.identity).not.toBe(result()!.identity);
  });
  it.each(["program_id", "program_version_id"] as const)(
    "pins %s outside token claims",
    (field) => {
      const input = fixture();
      input.activity[field] = "different-program";
      expect(result(input)!.identity).not.toBe(result()!.identity);
    },
  );
  it("pins mode and selected protocol, not progress revisions or presentation copy", () => {
    expect(result(fixture(), "tracked")!.identity).not.toBe(result()!.identity);
    const input = fixture();
    input.activity.state = "in_progress";
    input.activity.revision = 10;
    input.activity.title = "Renamed lesson";
    expect(result(input)).toEqual(result());
    const progressive = {
      protocol: "progressive",
      src: input.media.fallback.src,
    };
    expect(
      activityMediaIdentity(input.activity, progressive, "read-only")!.identity,
    ).not.toBe(result()!.identity);
  });
  it.each([
    (input: Fixture) => {
      input.activity.media!.duration_seconds = 1300;
    },
    (input: Fixture) => {
      input.activity.media!.width = 1920;
    },
    (input: Fixture) => {
      input.activity.media!.height = 1080;
    },
    (input: Fixture) => {
      input.activity.media!.content_type = "video/webm";
    },
    (input: Fixture) => {
      input.activity.media!.renditions[0].id = "hls-2";
    },
    (input: Fixture) => {
      input.activity.media!.captions[0].language = "hi";
    },
    (input: Fixture) => {
      input.activity.media!.captions[0].kind = "subtitles";
    },
    (input: Fixture) => {
      input.activity.media!.captions[0].is_default = false;
    },
    (input: Fixture) => {
      input.activity.media!.captions[0].source_url =
        input.activity.media!.captions[0].source_url!.replace(
          "caption-1?",
          "caption-2?",
        );
      const old = input.activity.media!.captions[0].source_url!;
      const parsed = new URL(old);
      const key = decodeURIComponent(
        parsed.pathname.slice("/v1/media/playback/".length),
      );
      input.activity.media!.captions[0].source_url = url(key, baseClaims);
    },
  ])("pins content and caption metadata %#", (change) => {
    const input = fixture();
    change(input);
    expect(result(input)).not.toBeNull();
    expect(result(input)!.identity).not.toBe(result()!.identity);
  });
  it("pins delivery origin and exact rendition paths", () => {
    expect(
      result(fixture({}, "https://another.authorityclosers.test"))!.identity,
    ).not.toBe(result()!.identity);
    const input = fixture();
    const source = input.media.src;
    const parsed = new URL(source);
    const key = decodeURIComponent(
      parsed.pathname.slice("/v1/media/playback/".length),
    ).replace("master.m3u8", "other.m3u8");
    replacePrimary(input, url(key, baseClaims));
    expect(result(input)!.identity).not.toBe(result()!.identity);
  });
  it.each([
    "person_id",
    "tenant_id",
    "session_id",
    "delivery_grant_id",
    "iat",
    "exp",
  ])("rejects a fallback with mixed %s", (field) => {
    const input = fixture();
    const changed = changeUrl(input.media.fallback.src, {
      [field]:
        field === "iat"
          ? issued + 1
          : field === "exp"
            ? issued + 301
            : "different",
    });
    input.media.fallback.src = changed;
    input.activity.media!.delivery!.progressive_url = changed;
    expect(result(input)).toBeNull();
  });
  it.each([
    "person_id",
    "tenant_id",
    "session_id",
    "delivery_grant_id",
    "iat",
    "exp",
  ])(
    "rejects every supplied caption with mixed %s, including non-display transcript metadata",
    (field) => {
      const input = fixture();
      const caption = input.activity.media!.captions[0];
      caption.kind = "transcript";
      caption.source_url = changeUrl(caption.source_url!, {
        [field]:
          field === "iat"
            ? issued + 1
            : field === "exp"
              ? issued + 301
              : "different",
      });
      expect(result(input)).toBeNull();
    },
  );
  it("rejects a foreign caption or fallback origin and a mismatched selected fallback", () => {
    const input = fixture();
    input.activity.media!.captions[0].source_url =
      input.activity.media!.captions[0].source_url!.replace(
        origin,
        "https://other.test",
      );
    expect(result(input)).toBeNull();
    const other = fixture();
    other.media.fallback.src = fixture(
      {},
      "https://other.test",
    ).media.fallback.src;
    expect(result(other)).toBeNull();
  });
  it.each([
    "session_id",
    "tenant_id",
    "person_id",
    "binding_id",
    "delivery_grant_id",
    "nonce",
    "supports_range",
  ])("rejects missing %s", (field) => {
    const input = fixture();
    replacePrimary(input, changeUrl(input.media.src, {}, [field]));
    expect(result(input)).toBeNull();
  });
  it.each([
    { iat: -1 },
    { iat: 1.5 },
    { exp: issued },
    { exp: issued + 3601 },
    { exp: Number.MAX_SAFE_INTEGER },
    { iat: "1" },
    { exp: null },
    { typ: "other" },
    { token_type: "read" },
    { session_id: "" },
    { person_id: "../person" },
    { supports_range: "true" },
    { nonce: "" },
    { nonce: " ".repeat(5) },
    { unexpected_claim: "new-authority" },
  ])("rejects malformed or unsupported claims %#", (changes) => {
    const input = fixture();
    replacePrimary(input, changeUrl(input.media.src, changes));
    expect(result(input)).toBeNull();
  });
  it.each([
    (value: string) => `${value}&extra=1`,
    (value: string) => `${value}&token=duplicate`,
    (value: string) => `${value}#fragment`,
    (value: string) => value.replace("https://", "https://user@"),
    (value: string) => value.replace("https://", "http://"),
    (value: string) => value.replace("%2F", "/"),
    (value: string) => value.replace("%2F", "%2f"),
    (value: string) => value.replace(/A{43}$/, "a".repeat(43)),
    (value: string) => value.replace(/AC-MEDIA\.[^.]+\./, "AC-MEDIA.W10."),
  ])("rejects noncanonical or malformed URLs %#", (change) => {
    const input = fixture();
    replacePrimary(input, change(input.media.src));
    expect(result(input)).toBeNull();
  });
  it("rejects duplicate JSON keys even if JSON.parse would retain the valid last value", () => {
    const input = fixture();
    const parsed = new URL(input.media.src);
    const token = parsed.searchParams.get("token")!;
    const body = Buffer.from(token.split(".")[1], "base64url").toString("utf8");
    const duplicate = Buffer.from(
      `{"person_id":"different",${body.slice(1)}`,
    ).toString("base64url");
    replacePrimary(
      input,
      input.media.src.replace(token.split(".")[1], duplicate),
    );
    expect(result(input)).toBeNull();
  });
  it.each([
    "tenants/other/media/video/asset-1/version-1/original/renditions/master.m3u8",
    "tenants/tenant-1/media/avatar/asset-1/version-1/original/renditions/master.m3u8",
    "tenants/tenant-1/media/video/other/version-1/original/renditions/master.m3u8",
    "tenants/tenant-1/media/video/asset-1/other/original/renditions/master.m3u8",
    "tenants/tenant-1/media/video/asset-1/version-1/not-original/renditions/master.m3u8",
    "tenants/tenant-1/media/video/asset-1/version-1/original/../master.m3u8",
  ])("requires the canonical object namespace %s", (key) => {
    const input = fixture();
    replacePrimary(input, url(key, baseClaims));
    expect(result(input)).toBeNull();
  });
  it.each([
    (input: Fixture) => {
      input.activity.media!.state = "blocked";
    },
    (input: Fixture) => {
      input.activity.media!.playback_available = false;
    },
    (input: Fixture) => {
      input.activity.state = "locked";
    },
    (input: Fixture) => {
      input.activity.kind = "reflection";
    },
    (input: Fixture) => {
      input.activity.media!.media_version_id = "not-bound";
    },
    (input: Fixture) => {
      input.activity.media!.captions[0].source_url = null;
    },
    (input: Fixture) => {
      input.activity.media!.captions[0].source_url =
        "https://other.test/captions.vtt";
    },
    (input: Fixture) => {
      input.activity.media!.captions.push({
        ...input.activity.media!.captions[0],
      });
    },
    (input: Fixture) => {
      input.activity.media!.duration_seconds = Number.NaN;
    },
    (input: Fixture) => {
      input.activity.media!.renditions.push({
        ...input.activity.media!.renditions[0],
      });
    },
  ])("does not stabilize malformed or unavailable descriptors %#", (change) => {
    const input = fixture();
    change(input);
    expect(result(input)).toBeNull();
  });
  it("returns null for legacy sources rather than collapsing their exact-source identities", () => {
    const input = fixture();
    expect(
      activityMediaIdentity(
        input.activity,
        { src: "https://provider.test/lesson.mp4" },
        "tracked",
      ),
    ).toBeNull();
    expect(activityMediaIdentity(input.activity, null, "tracked")).toBeNull();
    input.activity.media = null;
    expect(result(input)).toBeNull();
  });
  it("permits loopback comparison only through the existing exact development opt-in", () => {
    const localOrigin = "http://learner.localhost:3100";
    const input = fixture({}, localOrigin);
    expect(result(input)).toBeNull();
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED", "true");
    vi.stubGlobal("window", { location: { origin: localOrigin } });
    expect(result(input)).not.toBeNull();
    vi.stubEnv("NODE_ENV", "production");
    expect(result(input)).toBeNull();
  });
});
