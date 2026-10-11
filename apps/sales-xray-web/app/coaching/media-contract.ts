/** Only fixed authenticated source routes; dataset paths never reach a player. */
export type CoachingClip = {
  topic_id: string;
  revision: string;
  review_id: string;
  title: string;
  kind: "audio" | "video";
  placeholder: true;
  voice: "neutral";
  access: "full";
  entitlement_policy: "AUT-1678-open-access";
  start_ms: number;
  end_ms: number;
  reason: string;
  takeaways: string[];
  transcript_excerpt: string;
  slides: { segment_id: string; title: string; bullets: string[] }[];
};
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const texts = (v: unknown): v is string[] => Array.isArray(v) && v.every(text);
const object = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
export function parseClips(value: unknown): CoachingClip[] {
  if (!Array.isArray(value) || value.length > 3) return [];
  const clips: CoachingClip[] = [];
  for (const raw of value) {
    const c = object(raw);
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
      c.access !== "full" ||
      c.entitlement_policy !== "AUT-1678-open-access" ||
      !Number.isSafeInteger(c.start_ms) ||
      !Number.isSafeInteger(c.end_ms) ||
      (c.start_ms as number) < 0 ||
      (c.end_ms as number) <= (c.start_ms as number) ||
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
    clips.push(c as CoachingClip);
  }
  return clips;
}
export function clipSource(clip: CoachingClip): string {
  return `/v1/me/coaching/media/${clip.topic_id}/${clip.revision}/${clip.review_id}/source`;
}
