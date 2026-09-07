import { describe, expect, it } from "vitest";
import {
  DEVELOPMENT_MEDIA_MAX_BYTES,
  isDevelopmentMediaObjectUrl,
  isDevelopmentMediaRange,
  developmentMediaRegistrationUrl,
  readDevelopmentMediaSource,
} from "./dev-media-transport";

const ORIGIN = "http://learner.localhost:3100";
const KEY =
  "tenants/tenant-1/media/lesson_video/asset-1/version-1/original/renditions/lesson.mp4";
const TOKEN = `AC-MEDIA.fixture.${"s".repeat(43)}`;
const path = (key = KEY) =>
  `/v1/media/playback/${encodeURIComponent(key)}?token=${TOKEN}`;
const source = (key = KEY) =>
  `https://staging.authorityclosers.com${path(key)}`;

describe("development media transport", () => {
  it("uses a fixed token-free registration endpoint, never a signed local URL", () => {
    expect(developmentMediaRegistrationUrl(ORIGIN, ORIGIN)).toBe(
      ORIGIN + "/v1/dev-bridge/media",
    );
  });

  it("requires the current exact configured loopback origin, including SSR", () => {
    for (const current of [
      null,
      "http://localhost:3100",
      "http://learner.localhost:3101",
      "https://learner.localhost:3100",
      "https://staging.authorityclosers.com",
    ]) {
      expect(developmentMediaRegistrationUrl(ORIGIN, current)).toBeNull();
    }
    for (const configured of [
      "https://evil.example",
      ORIGIN + "/",
      ORIGIN + "/path",
      "http://user@learner.localhost:3100",
      ORIGIN + "?origin=x",
    ]) {
      expect(
        developmentMediaRegistrationUrl(configured, configured),
      ).toBeNull();
    }
  });

  it("rejects arbitrary, production, credentialed, fragmented, and normalized source URLs", () => {
    for (const value of [
      source().replace(
        "staging.authorityclosers.com",
        "app.authorityclosers.com",
      ),
      source().replace(
        "staging.authorityclosers.com",
        "api-staging.authorityclosers.com",
      ),
      source().replace(
        "staging.authorityclosers.com",
        "staging.authorityclosers.com.evil.example",
      ),
      source().replace("https:", "http:"),
      source().replace("https://", "https://user@"),
      source() + "#fragment",
      " " + source(),
      source().replace("https://", "//"),
      source().replace(
        "staging.authorityclosers.com",
        "STAGING.authorityclosers.com",
      ),
    ])
      expect(readDevelopmentMediaSource(value)).toBeNull();
  });

  it("rejects traversal, ambiguous encoding, wrong scope, HLS, and extra query fields", () => {
    for (const value of [
      path().replace("%2F", "%2f"),
      path().replace("%2F", "/"),
      path().replace("%2F", "%252F"),
      path(KEY.replace("/original/", "/../")),
      path(KEY.replace("/original/", "/./")),
      path(KEY.replace("/original/", "//")),
      path(KEY.replace("/original/", "/white space/")),
      path(KEY.replace("/original/", "/back\\slash/")),
      path(KEY.replace("tenants/", "other/")),
      path(KEY.replace("/media/", "/private/")),
      path("tenants/t/media/video/a/v/" + "x".repeat(512)),
      path(KEY.replace(/lesson.mp4$/, "playlist.m3u8")),
      path(KEY.replace(/lesson.mp4$/, "playlist.M3U8")),
      path() + "&token=" + TOKEN,
      path() + "&url=https://evil.example",
      path() + "&download=1",
      path().replace("?token=", "?%74oken="),
      path().replace("AC-MEDIA", "%41C-MEDIA"),
      path().replace(TOKEN, "x".repeat(4097)),
      path().replace(TOKEN, "invalid"),
      path().replace("/playback/", "/read/"),
    ])
      expect(isDevelopmentMediaObjectUrl(new URL(ORIGIN + value)), value).toBe(
        false,
      );
  });

  it("forwards only canonical bounded open or closed single ranges", () => {
    for (const range of [
      null,
      "bytes=0-",
      "bytes=0-1023",
      "bytes=500-500",
      `bytes=${DEVELOPMENT_MEDIA_MAX_BYTES - 1}-`,
    ])
      expect(isDevelopmentMediaRange(range)).toBe(true);
    for (const range of [
      "",
      "bytes=-500",
      "bytes=0-1,2-3",
      "bytes=01-2",
      "bytes=0-01",
      "bytes=5-4",
      "Bytes=0-1",
      "bytes=0-1 ",
      "bytes=0--1",
      "bytes=1e3-",
      `bytes=${DEVELOPMENT_MEDIA_MAX_BYTES}-`,
      `bytes=0-${DEVELOPMENT_MEDIA_MAX_BYTES}`,
      "bytes=" + "9".repeat(65) + "-",
    ])
      expect(isDevelopmentMediaRange(range), range).toBe(false);
  });
});
