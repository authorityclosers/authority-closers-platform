import { z } from "zod";
import { createLearnerApi } from "./learner-api";

export const appUpdateId = z
  .string()
  .max(128)
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
const appUpdateSchema = z.strictObject({
  id: appUpdateId,
  title: z.string().min(1).max(200),
  message: z.string().min(1).max(1000),
  version: z.string().min(1).max(80),
  highlights: z.array(z.string().min(1).max(300)).max(8),
  target_href: z.string().max(500).nullable(),
  created_at: z.iso.datetime({ offset: true }),
  read: z.boolean(),
});
export const appUpdatesSchema = z
  .strictObject({
    person_id: z.uuid(),
    tenant_id: z.uuid(),
    items: z.array(appUpdateSchema).max(50),
    unread_count: z.number().int().min(0).max(50),
  })
  .refine(
    (value) =>
      value.unread_count === value.items.filter((item) => !item.read).length &&
      new Set(value.items.map((item) => item.id)).size === value.items.length,
    { message: "App update counts or identities disagree" },
  );
export type AppUpdateFeed = z.infer<typeof appUpdatesSchema>;
export type AppUpdate = AppUpdateFeed["items"][number];

/** Package-owned release notes with server receipts; never private offline cache. */
export function createAppUpdatesApi(api = createLearnerApi()) {
  async function request(path: string, signal: AbortSignal, method = "GET") {
    const result = await api.request<unknown>(path, {
      signal,
      method,
      cache: "no-store",
      mode: "same-origin",
      redirect: "error",
    });
    return appUpdatesSchema.parse(result);
  }
  return {
    list: (signal: AbortSignal) => request("/v1/me/app-updates", signal),
    markRead: async (id: string, signal: AbortSignal) => {
      const response = await request(
        `/v1/me/app-updates/${appUpdateId.parse(id)}/read`,
        signal,
        "POST",
      );
      if (!response.items.some((item) => item.id === id && item.read)) {
        throw new Error(
          "The server did not confirm the app update read receipt.",
        );
      }
      return response;
    },
  };
}
export type AppUpdatesApi = ReturnType<typeof createAppUpdatesApi>;
