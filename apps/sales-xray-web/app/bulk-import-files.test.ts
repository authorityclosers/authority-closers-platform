import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  importManifestDigest,
  inventoryImportFiles,
  selectedImportFiles,
} from "./bulk-import-files";
import { previewImportFolder, readImportPreview } from "./bulk-import-client";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
function recording(path: string, text = "abc") {
  const bytes = new TextEncoder().encode(text);
  return {
    name: path.split("/").at(-1),
    webkitRelativePath: path,
    size: bytes.length,
    arrayBuffer: vi.fn(async () => bytes.buffer),
  } as unknown as File;
}
const manifest = {
  files: [
    {
      relative_path: "स्वामिनी/call.wav",
      source_sha256: "a".repeat(64),
      source_bytes: 3,
    },
  ],
};

it("reselecting the same Unicode folder reproduces its manifest independent of browser order", async () => {
  const files = [
    recording("Team/स्वामिनी/one"),
    recording("Team/😀/two"),
    recording("Team/Rep/three"),
  ];
  const first = await inventoryImportFiles(files);
  const second = await inventoryImportFiles([...files].reverse());
  expect(first.error).toBeNull();
  expect(second.data?.manifest).toEqual(first.data?.manifest);
  expect(await importManifestDigest(second.data!.manifest)).toBe(
    await importManifestDigest(first.data!.manifest),
  );
  expect(
    selectedImportFiles([recording("Team/Rep/\ud800")]).error,
  ).toBeTruthy();
});
const memberId = "00000000-0000-4000-8000-000000000002";
const preview = () => ({
  tenant_id: "00000000-0000-4000-8000-000000000001",
  manifest_sha256: "b".repeat(64),
  requires_confirmation: true,
  total_files: 1,
  total_bytes: 3,
  members: [{ person_id: memberId, display_name: "स्वामिनी" }],
  folders: [
    {
      folder: "स्वामिनी",
      proposed_person_id: memberId,
      match_state: "suggested",
      file_count: 1,
      source_bytes: 3,
    },
  ],
});

it("strips the picker root, hashes actual bytes sequentially and keeps extensionless calls", async () => {
  const progress = vi.fn();
  const files = [
    recording("Team/Swamini/one"),
    recording("Team/स्वामिनी/two.OGG"),
    recording("Team/notes.txt"),
  ];
  const result = await inventoryImportFiles(files, { onHashed: progress });
  expect(result.error).toBeNull();
  expect(result.data?.manifest.files).toEqual([
    {
      relative_path: "Swamini/one",
      source_sha256:
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      source_bytes: 3,
    },
    {
      relative_path: "स्वामिनी/two.OGG",
      source_sha256:
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      source_bytes: 3,
    },
  ]);
  expect(result.data?.skipped).toBe(1);
  expect(files[2].arrayBuffer).not.toHaveBeenCalled();
  expect(progress.mock.calls).toEqual([
    [1, 2],
    [2, 2],
  ]);
});

it("matches the service canonical UTF-8 digest including Devanagari", async () => {
  expect(await importManifestDigest(manifest)).toBe(
    "11fa59115cc11c0b57561b4398d91297b8c67abab3a3508d62053ff3ddda23fe",
  );
});

it.each([
  "Team/../one.wav",
  "Team/Rep\\one.wav",
  "Team//one.wav",
  "Team/C:/one.wav",
  "Team/Rep/one\n.wav",
])("rejects unsafe path %s before reading bytes", (path) => {
  const file = recording(path);
  expect(selectedImportFiles([file]).error).toBeTruthy();
  expect(file.arrayBuffer).not.toHaveBeenCalled();
});

it("rejects mixed roots, Unicode duplicate paths and source caps before hashing", () => {
  expect(
    selectedImportFiles([recording("A/one.wav"), recording("B/two.wav")]).error,
  ).toBeTruthy();
  expect(
    selectedImportFiles([recording("A/é.wav"), recording("A/e\u0301.wav")])
      .error,
  ).toBeTruthy();
  expect(
    selectedImportFiles(
      Array.from({ length: 257 }, (_, index) => recording(`A/${index}.wav`)),
    ).error,
  ).toBeTruthy();
  expect(
    selectedImportFiles([
      { ...recording("A/one.wav"), size: 32 * 1024 ** 2 + 1 } as File,
    ]).error,
  ).toBeTruthy();
  expect(
    selectedImportFiles(
      Array.from(
        { length: 33 },
        (_, index) =>
          ({ ...recording(`A/${index}.wav`), size: 32 * 1024 ** 2 }) as File,
      ),
    ).error,
  ).toBeTruthy();
});

it("cancels between files without uploading bytes or hashing the rest", async () => {
  const abort = new AbortController();
  const first = recording("A/one.wav"),
    second = recording("A/two.wav");
  const result = await inventoryImportFiles([first, second], {
    signal: abort.signal,
    onHashed: () => abort.abort(),
  });
  expect(result.error).toMatch(/cancelled/);
  expect(second.arrayBuffer).not.toHaveBeenCalled();
});

it("a changed or unreadable recording gives an error result", async () => {
  const changed = recording("A/one.wav");
  vi.mocked(changed.arrayBuffer).mockResolvedValue(new ArrayBuffer(2));
  expect((await inventoryImportFiles([changed])).error).toMatch(/changed/);
  vi.mocked(changed.arrayBuffer).mockRejectedValue(
    new Error("fictional file failure"),
  );
  expect((await inventoryImportFiles([changed])).error).toMatch(
    /could not be read/,
  );
});

it("a stalled local file read is bounded and can be cancelled immediately", async () => {
  vi.useFakeTimers();
  const file = recording("A/one.wav");
  vi.mocked(file.arrayBuffer).mockImplementation(() => new Promise(() => {}));
  const pending = inventoryImportFiles([file]);
  await vi.advanceTimersByTimeAsync(60_000);
  expect((await pending).error).toMatch(/could not be read/);
  const abort = new AbortController();
  const cancelled = inventoryImportFiles([file], { signal: abort.signal });
  abort.abort();
  expect((await cancelled).error).toMatch(/cancelled/);
  expect(vi.getTimerCount()).toBe(0);
});

it("sparse or inconsistent responses cannot create a proposed member", () => {
  expect(readImportPreview(null, manifest)).toBeNull();
  expect(readImportPreview({ folders: [] }, manifest)).toBeNull();
  expect(
    readImportPreview(preview(), manifest)?.folders[0].proposedPersonId,
  ).toBe(memberId);
  expect(readImportPreview({ ...preview(), members: [] }, manifest)).toBeNull();
  expect(
    readImportPreview(
      { ...preview(), folders: [...preview().folders, ...preview().folders] },
      manifest,
    ),
  ).toBeNull();
  expect(readImportPreview({ ...preview(), folders: [] }, manifest)).toBeNull();
});

it("a preview request is bound to the selected manifest, private and read-only", async () => {
  const reply = {
    ...preview(),
    manifest_sha256: await importManifestDigest(manifest),
  };
  const fetcher = vi.fn(async () => Response.json(reply));
  vi.stubGlobal("fetch", fetcher);
  expect((await previewImportFolder(manifest)).data?.members[0].name).toBe(
    "स्वामिनी",
  );
  expect(fetcher.mock.calls[0]).toEqual([
    "/v1/conversation/acquisition/imports/preview",
    expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      body: JSON.stringify(manifest),
    }),
  ]);
  reply.manifest_sha256 = "f".repeat(64);
  expect((await previewImportFolder(manifest)).data).toBeNull();
});

it.each([401, 403, 404, 503])(
  "an unavailable preview %s is an error result",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status })),
    );
    const result = await previewImportFolder(manifest);
    expect(result.data).toBeNull();
    expect(result.error).toBeTruthy();
  },
);

it("the preview network budget and caller cancellation end the read", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_path: string, options: RequestInit) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener(
            "abort",
            () => reject(new Error("cancelled")),
            { once: true },
          );
        }),
    ),
  );
  const pending = previewImportFolder(manifest);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
  await vi.advanceTimersByTimeAsync(15_000);
  expect((await pending).error).toMatch(/did not finish/);
  const abort = new AbortController();
  const cancelled = previewImportFolder(manifest, abort.signal);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  abort.abort();
  expect((await cancelled).error).toMatch(/cancelled/);
});
