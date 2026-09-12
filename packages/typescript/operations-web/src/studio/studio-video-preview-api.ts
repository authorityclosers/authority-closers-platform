import { z } from "zod";
import { AdminApiProblem } from "../admin-api";

const identifier = z.uuid();
const descriptor = z
  .object({
    program_id: identifier,
    asset_id: identifier,
    version_id: identifier,
    content_type: z.literal("video/mp4"),
    byte_length: z
      .number()
      .int()
      .positive()
      .max(8 * 1024 ** 3),
    duration_seconds: z.number().finite().positive(),
    preview_href: z.string().min(1).max(400),
  })
  .strict();

export type StudioVideoPreviewDescriptor = z.infer<typeof descriptor>;
export type StudioVideoPreviewIdentity = {
  programId: string;
  assetId: string;
  versionId: string;
};

export function studioVideoPreviewPath(identity: StudioVideoPreviewIdentity) {
  return `/v1/admin/studio/programs/${identifier.parse(identity.programId)}/videos/${identifier.parse(identity.assetId)}/versions/${identifier.parse(identity.versionId)}/preview`;
}

export async function loadStudioVideoPreview(
  identity: StudioVideoPreviewIdentity,
  {
    signal,
    fetcher = fetch,
  }: { signal?: AbortSignal; fetcher?: typeof fetch } = {},
): Promise<StudioVideoPreviewDescriptor> {
  const path = studioVideoPreviewPath(identity);
  const response = await fetcher(path, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    // Keep provider bodies/paths out of the UI. A status is enough for recovery.
    await response.body?.cancel();
    throw new AdminApiProblem({
      status: response.status,
      code: "studio_video_preview_unavailable",
      title: "Video preview unavailable",
      detail: "The preview could not be loaded.",
      requestId: null,
    });
  }
  const result = descriptor.parse(await response.json());
  if (
    result.program_id !== identity.programId ||
    result.asset_id !== identity.assetId ||
    result.version_id !== identity.versionId ||
    result.preview_href !== `${path}/bytes`
  )
    throw new TypeError("The preview does not belong to the selected video.");
  return result;
}
