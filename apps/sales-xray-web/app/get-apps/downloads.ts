import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const platforms = [
  "android",
  "ios",
  "windows",
  "macos",
  "chrome",
] as const;
export type AppFile = {
  name: string;
  platform: (typeof platforms)[number];
  size: number;
  sha256: string;
};
export type AppDownloads = { version: string; files: AppFile[] };
export const downloadsDir = () =>
  process.env.SALES_XRAY_COMPANION_DOWNLOADS_DIR?.trim() || null;
export const safeFileName = (name: string) =>
  /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,179}$/.test(name) &&
  !name.includes("..") &&
  name !== "latest.json";

/** Card 20 publishes latest.json and artifacts into the configured directory. */
export async function readDownloads(): Promise<AppDownloads | null> {
  const directory = downloadsDir();
  if (!directory) return null;
  try {
    const manifest = JSON.parse(
      await readFile(join(directory, "latest.json"), "utf8"),
    );
    if (
      typeof manifest?.version !== "string" ||
      !manifest.version.trim() ||
      !Array.isArray(manifest.files)
    )
      return null;
    const files: AppFile[] = manifest.files.filter(
      (file: AppFile) =>
        file &&
        typeof file.name === "string" &&
        safeFileName(file.name) &&
        platforms.includes(file.platform) &&
        Number.isSafeInteger(file.size) &&
        file.size > 0 &&
        typeof file.sha256 === "string" &&
        /^[a-fA-F0-9]{64}$/.test(file.sha256),
    );
    if (new Set(files.map((file) => file.name)).size !== files.length)
      return null;
    return { version: manifest.version, files };
  } catch {
    return null;
  }
}
