// @vitest-environment node
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET } from "../api/downloads/[file]/route";
import { readDownloads } from "./downloads";
import { sessionStatus } from "./session";

let directory: string;
const name = "sales-xray-android.apk";
const artifact = "fictional companion artifact";
const sha256 = createHash("sha256").update(artifact).digest("hex");
const entry = {
  name,
  platform: "android",
  size: Buffer.byteLength(artifact),
  sha256,
};
const manifest = (files: unknown[] = [entry]) =>
  writeFile(
    join(directory, "latest.json"),
    JSON.stringify({ version: "0.1.0", files }),
  );
const download = (file = name, signedIn = true) =>
  GET(
    new Request("https://untrusted.example/api/downloads/file", {
      headers: signedIn ? { cookie: "ac_session=fictional-session" } : {},
    }),
    { params: Promise.resolve({ file }) },
  );

beforeEach(async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "0");
  directory = await mkdtemp(
    join(process.env.PAPERCLIP_RUN_SCRATCH_DIR ?? tmpdir(), "companion-test-"),
  );
  vi.stubEnv("SALES_XRAY_COMPANION_DOWNLOADS_DIR", directory);
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "http://api.example.test");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async () =>
      Response.json({
        person_id: "fictional-person",
        session_id: "fictional-session",
      }),
    ),
  );
  await writeFile(join(directory, name), artifact);
  await manifest();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  await rm(directory, { recursive: true, force: true });
});

it("streams the listed artifact with private attachment headers and the declared hash", async () => {
  const response = await download();
  expect(response.status).toBe(200);
  expect(
    createHash("sha256")
      .update(Buffer.from(await response.arrayBuffer()))
      .digest("hex"),
  ).toBe(sha256);
  expect(response.headers.get("cache-control")).toBe("private, no-store");
  expect(response.headers.get("content-disposition")).toBe(
    `attachment; filename="${name}"`,
  );
  expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  expect(fetch).toHaveBeenCalledWith(
    new URL("http://api.example.test/v1/me/workspaces"),
    expect.objectContaining({ cache: "no-store", redirect: "error" }),
  );
});
it.each([
  "unlisted.apk",
  "latest.json",
  "..",
  "../file",
  "%2fetc",
  "/etc/passwd",
  "file\\path",
  "file%252fpath",
])("refuses %s", async (file) => {
  expect((await download(file)).status).toBe(404);
});
it("rejects signed-out and revoked sessions before serving a file", async () => {
  expect((await download(name, false)).status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
  vi.mocked(fetch).mockResolvedValue(Response.json({}, { status: 401 }));
  expect((await download()).status).toBe(401);
});
it("fails closed on API outage, invalid identity and unconfigured or unsafe origins", async () => {
  vi.mocked(fetch).mockRejectedValue(new Error("offline"));
  expect((await download()).status).toBe(503);
  vi.mocked(fetch).mockResolvedValue(Response.json({}));
  expect(await sessionStatus("fictional-cookie")).toBe(503);
  for (const origin of [
    "",
    "http://user:password@example.test",
    "http://example.test/path",
  ]) {
    vi.stubEnv("AC_CONVERSATION_API_ORIGIN", origin);
    expect(await sessionStatus("fictional-cookie")).toBe(503);
  }
});
it("refuses symlinks, directories, absent and size-mismatched artifacts", async () => {
  await manifest([{ ...entry, name: "missing.apk" }]);
  expect((await download("missing.apk")).status).toBe(404);
  await symlink(join(directory, name), join(directory, "linked.apk"));
  await manifest([{ ...entry, name: "linked.apk" }]);
  expect((await download("linked.apk")).status).toBe(404);
  await manifest([{ ...entry, name: "folder" }]);
  await mkdir(join(directory, "folder"));
  expect((await download("folder")).status).toBe(404);
  await manifest([{ ...entry, size: entry.size + 1 }]);
  expect((await download()).status).toBe(404);
});
it("has an empty state for unset, empty, missing or malformed manifests", async () => {
  for (const value of ["", " "]) {
    vi.stubEnv("SALES_XRAY_COMPANION_DOWNLOADS_DIR", value);
    expect(await readDownloads()).toBeNull();
  }
  vi.stubEnv("SALES_XRAY_COMPANION_DOWNLOADS_DIR", directory);
  await manifest([]);
  expect((await readDownloads())?.files).toEqual([]);
  for (const invalid of [
    "invalid JSON",
    "null",
    '{"files":[]}',
    '{"version":"1","files":null}',
  ]) {
    await writeFile(join(directory, "latest.json"), invalid);
    expect(await readDownloads()).toBeNull();
  }
  await rm(join(directory, "latest.json"));
  expect(await readDownloads()).toBeNull();
});
it("filters invalid entries and refuses duplicate filenames", async () => {
  await manifest([
    null,
    { ...entry, name: "../outside.apk" },
    { ...entry, sha256: "bad" },
    { ...entry, platform: "unknown" },
    { ...entry, size: -1 },
    entry,
  ]);
  expect((await readDownloads())?.files).toEqual([entry]);
  await manifest([entry, entry]);
  expect(await readDownloads()).toBeNull();
});

it("never serves artifacts or checks sessions in the static preview", async () => {
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "1");
  expect((await download()).status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});
