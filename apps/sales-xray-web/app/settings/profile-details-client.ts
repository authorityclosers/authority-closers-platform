/**
 * The member's profile (migration 0135, 25 Oct 2026): user id, title, team, the photo
 * and how complete the profile is. The fields ride on the account profile read; this
 * parses them strictly and sends the three writes.
 */
import {
  ACCOUNT_PROFILE_PATH,
  type AccountProfileRecord,
} from "../account-profile-client";

export type ProfileItem =
  | "photo"
  | "name"
  | "handle"
  | "title"
  | "team"
  | "phone";

export type ProfileCompletion = Readonly<{
  done: number;
  total: number;
  missing: readonly ProfileItem[];
}>;

export type ProfileDetails = Readonly<{
  handle: string | null;
  title: string | null;
  team: string | null;
  /** The details' own revision, sent back as expected_revision. */
  revision: number;
  avatarUrl: string | null;
  /** The person's own upload, which they can remove; a Google photo is not. */
  ownPhoto: boolean;
  completion: ProfileCompletion | null;
}>;

const ITEMS: readonly ProfileItem[] = [
  "photo",
  "name",
  "handle",
  "title",
  "team",
  "phone",
];
const ITEM_WORDS: Record<ProfileItem, string> = {
  photo: "a photo",
  name: "your name",
  handle: "a user id",
  title: "your job title",
  team: "your team",
  phone: "your phone number",
};
const AVATAR =
  /^\/v1\/people\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/photo\?v=[0-9a-f]{8}$/;
const HANDLE = /^[a-z0-9][a-z0-9._-]{2,29}$/;
export const PHOTO_SIZE = 256;
export const DETAIL_MAX = 80;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const text = (value: unknown) =>
  typeof value === "string" && value.trim() ? value : null;

function completionOf(value: unknown): ProfileCompletion | null {
  if (
    !isRecord(value) ||
    !Number.isSafeInteger(value.done) ||
    !Number.isSafeInteger(value.total) ||
    !Array.isArray(value.missing)
  )
    return null;
  const done = Number(value.done);
  const total = Number(value.total);
  if (total < 1 || done < 0 || done > total) return null;
  const missing = value.missing.filter((item): item is ProfileItem =>
    ITEMS.includes(item as ProfileItem),
  );
  return { done, total, missing };
}

/** The new fields, read strictly from the account profile (older servers lack them). */
export function profileDetails(profile: AccountProfileRecord): ProfileDetails {
  const raw = profile as unknown as Record<string, unknown>;
  const avatar = raw.avatar_url;
  const revision = Number(raw.details_revision);
  return {
    handle: text(raw.handle),
    title: text(raw.title),
    team: text(raw.team),
    revision: Number.isSafeInteger(revision) && revision >= 0 ? revision : 0,
    avatarUrl:
      typeof avatar === "string" && AVATAR.test(avatar) ? avatar : null,
    ownPhoto: raw.own_photo === true,
    completion: completionOf(raw.completion),
  };
}

/** "a photo, a user id and your team" */
export function missingWords(items: readonly ProfileItem[]): string {
  const words = items.map((item) => ITEM_WORDS[item]);
  if (words.length < 2) return words[0] ?? "";
  return `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

/** As the server keeps it: lower case, no leading @; null when it cannot be one. */
export function normalizeHandle(value: string): string | null {
  const handle = value.trim().replace(/^@+/, "").toLowerCase();
  return HANDLE.test(handle) ? handle : null;
}

export class ProfileDetailsError extends Error {
  constructor(
    readonly status: number,
    message = "",
  ) {
    super(message);
    this.name = "ProfileDetailsError";
  }
}

async function send(path: string, init: RequestInit): Promise<void> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", ...init.headers },
  });
  if (response.ok) return;
  let detail = "";
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && typeof body.detail === "string") detail = body.detail;
  } catch {
    // No readable reason; the status still says what happened.
  }
  throw new ProfileDetailsError(response.status, detail);
}

export function saveProfileDetails(
  input: Readonly<{
    handle: string | null;
    title: string;
    team: string;
    expected_revision: number;
  }>,
  signal?: AbortSignal,
): Promise<void> {
  return send(`${ACCOUNT_PROFILE_PATH}/details`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
}

export function uploadProfilePhoto(
  photo: Blob,
  signal?: AbortSignal,
): Promise<void> {
  return send(`${ACCOUNT_PROFILE_PATH}/photo`, {
    method: "PUT",
    headers: { "content-type": photo.type },
    body: photo,
    signal,
  });
}

export function removeProfilePhoto(signal?: AbortSignal): Promise<void> {
  return send(`${ACCOUNT_PROFILE_PATH}/photo`, { method: "DELETE", signal });
}

/**
 * The middle square of the photo at 256 x 256, as WebP where the browser can (PNG
 * otherwise). Decoding here also turns a phone's HEIC photo into something we take.
 */
export async function squarePhoto(
  file: Blob,
  size = PHOTO_SIZE,
): Promise<Blob> {
  const image = await createImageBitmap(file);
  try {
    const side = Math.min(image.width, image.height);
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    if (!context || side < 1) throw new Error("photo_unreadable");
    context.drawImage(
      image,
      (image.width - side) / 2,
      (image.height - side) / 2,
      side,
      side,
      0,
      0,
      size,
      size,
    );
    const photo = await new Promise<Blob | null>((done) =>
      canvas.toBlob(done, "image/webp", 0.86),
    );
    if (!photo) throw new Error("photo_unreadable");
    return photo;
  } finally {
    image.close();
  }
}
