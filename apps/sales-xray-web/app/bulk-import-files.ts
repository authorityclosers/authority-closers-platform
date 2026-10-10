/** Browser inventory only. Native intake verifies format, bytes and duration. */
export const MAX_IMPORT_FILES = 256;
export const MAX_IMPORT_BYTES = 1024 ** 3;
export const MAX_IMPORT_FILE_BYTES = 32 * 1024 ** 2;

export type ImportSource = {
  relative_path: string;
  source_sha256: string;
  source_bytes: number;
};
export type ImportManifest = { files: ImportSource[] };
export type ImportSelection = {
  manifest: ImportManifest;
  files: Map<string, File>;
  skipped: number;
};
export type ImportResult<T> =
  | { data: T; error: null }
  | { data: null; error: string };

const failure = (error: string): ImportResult<never> => ({ data: null, error });
export async function importManifestDigest(
  manifest: ImportManifest,
): Promise<string> {
  // Same canonical UTF-8 JSON as the acquisition service, including Devanagari.
  const bytes = new TextEncoder().encode(
    JSON.stringify({
      files: manifest.files.map((file) => ({
        relative_path: file.relative_path,
        source_bytes: file.source_bytes,
        source_sha256: file.source_sha256,
      })),
    }),
  );
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
const supported = (path: string) => {
  const name = path.split("/").at(-1) ?? "";
  return !name.includes(".") || /\.(mp3|m4a|ogg|wav)$/i.test(name);
};
const safe = (path: string) =>
  path.length > 0 &&
  path.length <= 512 &&
  !path.startsWith("/") &&
  !path.includes("\\") &&
  !/^[a-z]:/i.test(path) &&
  !/[\u0000-\u001f\u007f]/.test(path) &&
  path
    .split("/")
    .every((part) => !["", ".", ".."].includes(part.normalize("NFKC")));

async function boundedHash(file: File, signal?: AbortSignal): Promise<string> {
  let cancel: (() => void) | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stopped = new Promise<never>((_resolve, reject) => {
    cancel = () => reject(new Error("cancelled"));
    timer = setTimeout(cancel, 60_000);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
  });
  try {
    const bytes = await Promise.race([file.arrayBuffer(), stopped]);
    if (bytes.byteLength !== file.size) throw new Error("changed");
    if (signal?.aborted) throw new Error("cancelled");
    const digest = await Promise.race([
      crypto.subtle.digest("SHA-256", bytes),
      stopped,
    ]);
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("");
  } finally {
    clearTimeout(timer);
    if (cancel) signal?.removeEventListener("abort", cancel);
  }
}

/** Strip precisely the directory picker root; retain salesperson subfolders. */
export function selectedImportFiles(files: readonly File[]): ImportResult<{
  files: Map<string, File>;
  skipped: number;
}> {
  const directories = files.filter((file) => file.webkitRelativePath);
  const roots = new Set(
    directories.map((file) => file.webkitRelativePath.split("/")[0]),
  );
  if (
    roots.size > 1 ||
    (directories.length && directories.length !== files.length)
  )
    return failure("Choose one folder at a time.");
  const selected = new Map<string, File>();
  let total = 0;
  let skipped = 0;
  for (const file of files) {
    const original = file.webkitRelativePath || file.name;
    const path = (
      file.webkitRelativePath
        ? original.split("/").slice(1).join("/")
        : original
    ).normalize("NFC");
    if (!safe(path))
      return failure(
        "One filename is unsafe or too long. Rename it and try again.",
      );
    if (!supported(path)) {
      skipped++;
      continue;
    }
    if (
      !Number.isSafeInteger(file.size) ||
      file.size < 1 ||
      file.size > MAX_IMPORT_FILE_BYTES
    )
      return failure(
        "Each recording must contain audio and be no larger than 32 MiB.",
      );
    if (selected.has(path))
      return failure("Two files have the same relative name. Choose one copy.");
    selected.set(path, file);
    total += file.size;
    if (selected.size > MAX_IMPORT_FILES || total > MAX_IMPORT_BYTES)
      return failure("Choose up to 256 recordings and 1 GiB per batch.");
  }
  if (!selected.size)
    return failure(
      "Choose MP3, M4A, OGG, WAV or recordings without an extension.",
    );
  return { data: { files: selected, skipped }, error: null };
}

/** Hash one bounded file at a time: never allocate the complete folder. */
export async function inventoryImportFiles(
  files: readonly File[],
  options: {
    signal?: AbortSignal;
    onHashed?: (done: number, total: number) => void;
  } = {},
): Promise<ImportResult<ImportSelection>> {
  const selected = selectedImportFiles(files);
  if (selected.error !== null) return selected;
  const sources: ImportSource[] = [];
  try {
    for (const [path, file] of selected.data.files) {
      if (options.signal?.aborted)
        return failure("Folder selection was cancelled.");
      const digest = await boundedHash(file, options.signal);
      if (options.signal?.aborted)
        return failure("Folder selection was cancelled.");
      sources.push({
        relative_path: path,
        source_sha256: digest,
        source_bytes: file.size,
      });
      options.onHashed?.(sources.length, selected.data.files.size);
    }
    return {
      data: { ...selected.data, manifest: { files: sources } },
      error: null,
    };
  } catch (error) {
    if (options.signal?.aborted)
      return failure("Folder selection was cancelled.");
    if (error instanceof Error && error.message === "changed")
      return failure(
        "A recording changed while being read. Choose the folder again.",
      );
    return failure(
      "The folder could not be read securely. Choose it again and try again.",
    );
  }
}
