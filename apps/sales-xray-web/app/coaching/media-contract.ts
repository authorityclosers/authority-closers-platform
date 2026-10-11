/** Only fixed authenticated source routes; dataset paths never reach a player. */
export type ClipAccess = "full" | "preview" | "locked";
export type ClipOffer = {
  /** Same-origin path to the full coaching offer; never a payment provider. */
  full_coaching_href: string;
  /** A verified Learner's Academy course or lesson, when one matches. */
  academy: { href: string; label: string } | null;
};
export type CoachingClip = {
  topic_id: string;
  revision: string;
  review_id: string;
  title: string;
  kind: "audio" | "video";
  placeholder: true;
  voice: "neutral";
  /** Decided by the server from the Coaching entitlement and durable usage. */
  access: ClipAccess;
  entitlement_policy: string;
  start_ms: number;
  end_ms: number;
  /** Absolute source time where a preview stops; only for `preview`. */
  preview_end_ms?: number | null;
  offer?: ClipOffer | null;
  reason: string;
  takeaways: string[];
  transcript_excerpt: string;
  slides: { segment_id: string; title: string; bullets: string[] }[];
};
export const FULL_COACHING_HREF = "/plans";
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const texts = (v: unknown): v is string[] => Array.isArray(v) && v.every(text);
const object = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
const POLICY = /^[A-Za-z0-9._:-]{1,128}$/;

/** A same-origin app path only: no scheme, host or protocol-relative URL. */
function appPath(value: unknown): string | null {
  return typeof value === "string" &&
    /^\/[A-Za-z0-9/_?=&.-]*$/.test(value) &&
    !value.startsWith("//")
    ? value
    : null;
}

/** An HTTPS link on an Authority Closers host, never an arbitrary site. */
function academyLink(value: unknown): ClipOffer["academy"] {
  const item = object(value);
  if (!text(item.label) || typeof item.href !== "string") return null;
  try {
    const url = new URL(item.href);
    const host = url.hostname.toLowerCase();
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      (host === "authorityclosers.com" ||
        host.endsWith(".authorityclosers.com"))
      ? { href: url.href, label: item.label }
      : null;
  } catch {
    return null;
  }
}

function offer(value: unknown): ClipOffer {
  const item = object(value);
  return {
    full_coaching_href: appPath(item.full_coaching_href) ?? FULL_COACHING_HREF,
    academy: academyLink(item.academy),
  };
}

export function parseClips(value: unknown): CoachingClip[] {
  if (!Array.isArray(value) || value.length > 3) return [];
  const clips: CoachingClip[] = [];
  for (const raw of value) {
    const c = object(raw);
    const access = c.access as ClipAccess;
    const start = c.start_ms as number,
      end = c.end_ms as number;
    if (
      !/^[a-z0-9][a-z0-9_-]{0,99}$/.test(String(c.topic_id)) ||
      !/^[0-9a-f]{64}$/.test(String(c.revision)) ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
        String(c.review_id),
      ) ||
      !text(c.title) ||
      !["audio", "video"].includes(String(c.kind)) ||
      c.placeholder !== true ||
      c.voice !== "neutral" ||
      !["full", "preview", "locked"].includes(access) ||
      !POLICY.test(String(c.entitlement_policy)) ||
      // Open access is the only policy that may grant a full clip today.
      (access === "full" && c.entitlement_policy !== "AUT-1678-open-access") ||
      !Number.isSafeInteger(start) ||
      !Number.isSafeInteger(end) ||
      start < 0 ||
      end <= start ||
      !text(c.reason) ||
      !texts(c.takeaways) ||
      !c.takeaways.length ||
      !text(c.transcript_excerpt) ||
      !Array.isArray(c.slides) ||
      "url" in c ||
      "relative_path" in c ||
      "source_url" in c
    )
      continue;
    const preview = c.preview_end_ms as number;
    if (
      access === "preview" &&
      !(Number.isSafeInteger(preview) && preview > start && preview < end)
    )
      continue;
    const slides = c.slides.map(object);
    if (
      slides.some(
        (s) =>
          !text(s.segment_id) ||
          !text(s.title) ||
          !texts(s.bullets) ||
          !s.bullets.length,
      )
    )
      continue;
    clips.push({
      ...(c as CoachingClip),
      preview_end_ms: access === "preview" ? preview : null,
      offer: access === "full" && c.offer == null ? null : offer(c.offer),
    });
  }
  return clips;
}
export function clipSource(clip: CoachingClip): string {
  return `/v1/me/coaching/media/${clip.topic_id}/${clip.revision}/${clip.review_id}/source`;
}
