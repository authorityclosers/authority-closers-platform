/**
 * The shared offer store (/v1/admin/offers): every save is a new version,
 * refused with 409 when someone saved since. Reads never throw; writes go
 * through lib/client-api's send (same origin, the page's Origin).
 */
import { send, type CommandResult } from "../lib/client-api";
import type { Offer } from "./offer-model";

export type SharedVersion = Readonly<{
  offerId: string;
  version: number;
  name: string;
  archived: boolean;
  author: string | null;
  createdAt: string;
  body: unknown;
}>;

export type ReadResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const isSharedId = (id: unknown): id is string =>
  typeof id === "string" && UUID.test(id);

function version(raw: unknown): SharedVersion | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!isSharedId(r.offer_id) || typeof r.version !== "number") return null;
  return {
    offerId: r.offer_id,
    version: r.version,
    name: typeof r.name === "string" ? r.name : "Untitled offer",
    archived: r.archived === true,
    author: typeof r.author === "string" && r.author ? r.author : null,
    createdAt: typeof r.created_at === "string" ? r.created_at : "",
    body: r.body,
  };
}

async function read<T>(
  path: string,
  pick: (payload: unknown) => T,
  fetcher: typeof fetch,
): Promise<ReadResult<T>> {
  let response: Response;
  try {
    response = await fetcher(path, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { accept: "application/json" },
    });
  } catch {
    return { ok: false, status: 0, message: "No connection. Try again." };
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : null;
    return {
      ok: false,
      status: response.status,
      message:
        typeof detail === "string" && detail.length < 300
          ? detail
          : response.status === 404
            ? "Shared offers aren't available here yet."
            : "Couldn't load shared offers.",
    };
  }
  return { ok: true, data: pick(payload) };
}

const list = (payload: unknown, key: string) =>
  payload &&
  typeof payload === "object" &&
  Array.isArray((payload as Record<string, unknown>)[key])
    ? ((payload as Record<string, unknown>)[key] as unknown[])
        .map(version)
        .filter((v): v is SharedVersion => v !== null)
    : [];

export const listShared = (fetcher: typeof fetch = fetch) =>
  read("/v1/admin/offers", (p) => list(p, "offers"), fetcher);

export const historyOf = (offerId: string, fetcher: typeof fetch = fetch) =>
  read(
    `/v1/admin/offers/${offerId}/versions`,
    (p) => list(p, "versions"),
    fetcher,
  );

export const versionOf = (
  offerId: string,
  n: number,
  fetcher: typeof fetch = fetch,
) => read(`/v1/admin/offers/${offerId}/versions/${n}`, version, fetcher);

/** The document a shared version keeps: the offer without its link to the store. */
export function sharedBody(offer: Offer): Record<string, unknown> {
  const body: Record<string, unknown> = { ...offer };
  delete body.shared;
  return body;
}

export async function saveShared(
  offer: Offer,
  offerId: string,
  fetcher: typeof fetch = fetch,
): Promise<CommandResult<SharedVersion>> {
  const result = await send<unknown>(
    "POST",
    `/v1/admin/offers/${offerId}/versions`,
    { base_version: offer.shared?.version ?? null, body: sharedBody(offer) },
    null,
    fetcher,
  );
  if (!result.ok) return result;
  const saved = version(result.data);
  return saved
    ? { ok: true, data: saved }
    : {
        ok: false,
        status: 502,
        message: "The save wasn't confirmed. Try again.",
      };
}

export async function archiveShared(
  offerId: string,
  baseVersion: number,
  fetcher: typeof fetch = fetch,
): Promise<CommandResult<SharedVersion>> {
  const result = await send<unknown>(
    "POST",
    `/v1/admin/offers/${offerId}/archive`,
    { base_version: baseVersion },
    null,
    fetcher,
  );
  if (!result.ok) return result;
  const saved = version(result.data);
  return saved
    ? { ok: true, data: saved }
    : {
        ok: false,
        status: 502,
        message: "The change wasn't confirmed. Try again.",
      };
}
