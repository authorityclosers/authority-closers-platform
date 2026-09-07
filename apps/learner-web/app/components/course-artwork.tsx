import Image from "next/image";
import { ACADEMY_ARTWORK, INSTRUCTOR_PORTRAIT } from "@ac/ui";

export type CourseArtworkKind = keyof typeof ACADEMY_ARTWORK;

/**
 * A decorative surface shared by catalog, library and dashboard.
 * It accepts no URL, title, status, instructor or playback properties. Those
 * remain separate server-owned content; the object is not an earned badge.
 */
export function CourseArtwork({
  artwork = "discovery",
  compact = false,
}: {
  artwork?: CourseArtworkKind;
  compact?: boolean;
}) {
  return (
    <div
      className={`academy-artwork academy-artwork--${artwork}${compact ? " academy-artwork--compact" : ""}`}
      aria-hidden="true"
      data-presentation-only="true"
    >
      <span className="academy-artwork__orbit" />
      <Image
        {...ACADEMY_ARTWORK[artwork]}
        alt=""
        sizes={compact ? "64px" : "(max-width: 560px) 240px, 280px"}
        className="academy-artwork__object"
      />
    </div>
  );
}

/** Intrinsic image contract reusable at academy-level editorial surfaces. */
export function InstructorPortrait({
  decorative = false,
  priority = false,
  fill = false,
  sizes = "(max-width: 760px) 100vw, 46vw",
  className,
}: {
  decorative?: boolean;
  priority?: boolean;
  fill?: boolean;
  sizes?: string;
  className?: string;
}) {
  return (
    <Image
      src={INSTRUCTOR_PORTRAIT.src}
      alt={decorative ? "" : INSTRUCTOR_PORTRAIT.alt}
      width={fill ? undefined : INSTRUCTOR_PORTRAIT.width}
      height={fill ? undefined : INSTRUCTOR_PORTRAIT.height}
      fill={fill}
      priority={priority}
      sizes={sizes}
      className={className}
    />
  );
}
