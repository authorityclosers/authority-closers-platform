import { ACQUISITION, UUID } from "./acquisition-client";
import type { ImportManifest, ImportResult } from "./bulk-import-files";
import { importManifestDigest } from "./bulk-import-files";

export type ImportPreview = {
  tenantId: string;
  manifestSha: string;
  folders: {
    folder: string;
    proposedPersonId: string | null;
    count: number;
    bytes: number;
    state: "suggested" | "ambiguous" | "unassigned";
  }[];
  members: { personId: string; name: string }[];
};
const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
const count = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= 0;

/** Sparse/older API responses return unavailable, without manufacturing a match. */
export function readImportPreview(
  value: unknown,
  manifest: ImportManifest,
): ImportPreview | null {
  const row = object(value);
  if (
    !row ||
    typeof row.tenant_id !== "string" ||
    !UUID.test(row.tenant_id) ||
    typeof row.manifest_sha256 !== "string" ||
    !/^[a-f0-9]{64}$/.test(row.manifest_sha256) ||
    row.requires_confirmation !== true ||
    row.total_files !== manifest.files.length ||
    row.total_bytes !==
      manifest.files.reduce((sum, file) => sum + file.source_bytes, 0) ||
    !Array.isArray(row.folders) ||
    !Array.isArray(row.members)
  )
    return null;
  const members: ImportPreview["members"] = [];
  const ids = new Set<string>();
  for (const raw of row.members) {
    const member = object(raw);
    if (
      !member ||
      typeof member.person_id !== "string" ||
      !UUID.test(member.person_id) ||
      ids.has(member.person_id)
    )
      return null;
    ids.add(member.person_id);
    members.push({
      personId: member.person_id,
      name:
        typeof member.display_name === "string" && member.display_name
          ? member.display_name
          : "Member",
    });
  }
  const expected = new Map<string, { count: number; bytes: number }>();
  for (const file of manifest.files) {
    const folder = file.relative_path.includes("/")
      ? file.relative_path.split("/")[0]
      : "";
    const totals = expected.get(folder) ?? { count: 0, bytes: 0 };
    totals.count++;
    totals.bytes += file.source_bytes;
    expected.set(folder, totals);
  }
  const folders: ImportPreview["folders"] = [];
  for (const raw of row.folders) {
    const folder = object(raw);
    if (!folder || typeof folder.folder !== "string") return null;
    const totals = expected.get(folder.folder);
    if (
      !totals ||
      !count(folder.file_count) ||
      !count(folder.source_bytes) ||
      folder.file_count !== totals.count ||
      folder.source_bytes !== totals.bytes ||
      !["suggested", "ambiguous", "unassigned"].includes(
        String(folder.match_state),
      ) ||
      (folder.proposed_person_id !== null &&
        (typeof folder.proposed_person_id !== "string" ||
          !ids.has(folder.proposed_person_id))) ||
      (folder.match_state === "suggested") !==
        (folder.proposed_person_id !== null)
    )
      return null;
    expected.delete(folder.folder);
    folders.push({
      folder: folder.folder,
      proposedPersonId: folder.proposed_person_id as string | null,
      count: folder.file_count,
      bytes: folder.source_bytes,
      state: folder.match_state as ImportPreview["folders"][number]["state"],
    });
  }
  if (expected.size) return null;
  return {
    tenantId: row.tenant_id,
    manifestSha: row.manifest_sha256,
    members,
    folders,
  };
}

export async function previewImportFolder(
  manifest: ImportManifest,
  signal?: AbortSignal,
): Promise<ImportResult<ImportPreview>> {
  const abort = new AbortController();
  const cancel = () => abort.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) abort.abort();
  const timer = setTimeout(cancel, 15_000);
  try {
    const expectedDigest = await importManifestDigest(manifest);
    if (abort.signal.aborted)
      return { data: null, error: "Folder preview did not finish. Try again." };
    const response = await fetch(`${ACQUISITION}/imports/preview`, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: abort.signal,
      headers: {
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify(manifest),
    });
    if (!response.ok)
      return {
        data: null,
        error: [401, 403].includes(response.status)
          ? "Select an organisation where you are an owner or admin, then try again."
          : "Folder preview is unavailable. Try again shortly.",
      };
    const data = readImportPreview(await response.json(), manifest);
    return data && data.manifestSha === expectedDigest
      ? { data, error: null }
      : {
          data: null,
          error: "Folder preview is unavailable. Try again shortly.",
        };
  } catch {
    return {
      data: null,
      error: signal?.aborted
        ? "Folder selection was cancelled."
        : "Folder preview did not finish. Check your connection and try again.",
    };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
