import { describe, expect, it } from "vitest";
import { type AppConfig, compareVersions, installedAndroidVersion, parseVersion, REMIND_AFTER_MS, reminderHeld, updateState, validConfig } from "./app-compatibility";
export const config: AppConfig = {
  min_app_version: { android: "1.2.0", ios: "0.0.0", desktop: "0.0.0" },
  recommended_app_version: { android: "1.10.0", ios: "0.0.0", desktop: "0.0.0" },
  features_off: [],
};
describe("app compatibility", () => {
  it("parses strict release versions and compares numerically", () => {
    expect(parseVersion("1.10.3")).toEqual([1, 10, 3]);
    for (const value of ["1.2", "01.2.3", "1.2.3-beta", "1.2.3\n", "١.2.3"]) expect(parseVersion(value)).toBeNull();
    expect(compareVersions("1.10.0", "1.2.0")).toBe(1);
    expect(compareVersions("1.2.0", "1.2.0")).toBe(0);
    expect(compareVersions("bad", "1.2.0")).toBeNull();
  });
  it("requires an update below minimum; recommends between versions", () => {
    expect(updateState("Android SalesXrayApp/1.1.9", config)).toBe("required");
    expect(updateState("Android SalesXrayApp/1.2.0", config)).toBe("recommended");
    expect(updateState("Android SalesXrayApp/1.10.0", config)).toBeNull();
  });
  it("leaves browsers and malformed app markers alone", () => {
    for (const ua of ["Mozilla/5.0 Android Chrome/140", "", "SalesXrayApp/bad", "OtherSalesXrayApp/1.0.0"]) {
      expect(installedAndroidVersion(ua)).toBeNull();
      expect(updateState(ua, config)).toBeNull();
    }
  });
  it("holds a recommendation three days, rejecting corrupt/future storage", () => {
    const now = 1000;
    expect(reminderHeld(String(now + REMIND_AFTER_MS), now)).toBe(true);
    expect(reminderHeld(String(now), now)).toBe(false);
    expect(reminderHeld("NaN", now)).toBe(false);
    expect(reminderHeld(String(now + REMIND_AFTER_MS + 1), now)).toBe(false);
  });
  it("rejects malformed configuration", () => {
    expect(validConfig(config)).toBe(true);
    for (const value of [null, {}, { ...config, features_off: ["unknown"] }, { ...config, min_app_version: { android: "bad" } }]) expect(validConfig(value)).toBe(false);
  });
});
