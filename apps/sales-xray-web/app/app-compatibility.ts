export const FEATURE_KEYS = ["clarity"] as const;
export type FeatureKey = (typeof FEATURE_KEYS)[number];
export type AppConfig = {
  min_app_version: Record<"android" | "ios" | "desktop", string>;
  recommended_app_version: Record<"android" | "ios" | "desktop", string>;
  features_off: FeatureKey[];
  message?: string | null;
};
const versionPattern =
  /^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})(?![\s\S])/;
export function parseVersion(value: string): number[] | null {
  return versionPattern.test(value) ? value.split(".").map(Number) : null;
}
export function compareVersions(a: string, b: string): number | null {
  const left = parseVersion(a),
    right = parseVersion(b);
  if (!left || !right) return null;
  for (let i = 0; i < 3; i++) {
    if (left[i] !== right[i]) return Math.sign(left[i] - right[i]);
  }
  return 0;
}
export function installedAndroidVersion(ua: string): string | null {
  const value = /(?:^|\s)SalesXrayApp\/([^\s]+)/.exec(ua)?.[1];
  return value && parseVersion(value) ? value : null;
}
export function updateState(
  ua: string,
  config: AppConfig,
): "required" | "recommended" | null {
  const version = installedAndroidVersion(ua);
  if (!version) return null;
  if (compareVersions(version, config.min_app_version.android) === -1)
    return "required";
  if (compareVersions(version, config.recommended_app_version.android) === -1)
    return "recommended";
  return null;
}
export function validConfig(value: unknown): value is AppConfig {
  if (!value || typeof value !== "object") return false;
  const config = value as AppConfig;
  return (
    [config.min_app_version, config.recommended_app_version].every(
      (versions) =>
        versions &&
        ["android", "ios", "desktop"].every(
          (platform) =>
            typeof versions[platform as keyof typeof versions] === "string" &&
            parseVersion(versions[platform as keyof typeof versions]) !== null,
        ),
    ) &&
    Array.isArray(config.features_off) &&
    config.features_off.every((key) => FEATURE_KEYS.includes(key)) &&
    (config.message == null ||
      (typeof config.message === "string" && config.message.length <= 280))
  );
}
export const REMIND_AFTER_MS = 3 * 24 * 60 * 60 * 1000;
export function reminderHeld(until: string | null, now: number): boolean {
  const value = Number(until);
  return (
    Number.isFinite(value) && value > now && value <= now + REMIND_AFTER_MS
  );
}
