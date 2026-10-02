import { z } from "zod";
import { AdminApiProblem } from "./admin-api";

export const platformOrganisationsSchema = z
  .object({
    organisations: z.array(
      z
        .object({
          tenant_id: z.uuid(),
          name: z.string().min(1),
          member_count: z.number().int().nonnegative(),
          created_at: z.string().min(1),
        })
        .strict(),
    ),
  })
  .strict();

export type PlatformOrganisations = z.infer<typeof platformOrganisationsSchema>;

export async function loadPlatformOrganisations({
  fetcher = fetch,
  signal,
}: {
  fetcher?: typeof fetch;
  signal?: AbortSignal;
} = {}): Promise<PlatformOrganisations> {
  const response = await fetcher("/v1/platform/organisations", {
    method: "GET",
    headers: { accept: "application/json" },
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const problem =
      typeof payload === "object" && payload !== null
        ? (payload as Record<string, unknown>)
        : {};
    const text = (key: string, fallback: string) =>
      typeof problem[key] === "string" && problem[key].trim()
        ? problem[key]
        : fallback;
    throw new AdminApiProblem({
      status: response.status,
      code: text("code", `http_${response.status}`),
      title: text("title", "Admin request rejected"),
      detail: text("detail", "The admin request was rejected."),
      requestId:
        typeof problem.request_id === "string" ? problem.request_id : null,
    });
  }
  return platformOrganisationsSchema.parse(payload);
}
