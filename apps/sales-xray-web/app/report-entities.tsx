"use client";

import {
  CalendarDays,
  Clock3,
  Coins,
  DollarSign,
  FileText,
  Globe,
  GraduationCap,
  IndianRupee,
  Mail,
  MapPin,
  Percent,
  UserRound,
  Users,
  Video,
  type LucideIcon,
} from "lucide-react";
import { useId, useMemo, type CSSProperties } from "react";

import {
  useBrandPath,
  useColorLogo,
  useIndexedBrand,
} from "./brands/brand-icons";
import { findEntities, type Entity, type EntityKind } from "./entity-engine";
import styles from "./report-entities.module.css";

export { findEntities, mentions, brandNamed } from "./entity-engine";
export type { Entity, EntityKind, TextPart } from "./entity-engine";

const KIND_ICONS: Record<Exclude<EntityKind, "brand">, LucideIcon> = {
  program: GraduationCap,
  money: IndianRupee,
  percent: Percent,
  document: FileText,
  video: Video,
  date: CalendarDays,
  time: Clock3,
  person: UserRound,
  team: Users,
  place: MapPin,
  email: Mail,
  website: Globe,
};

export function currencyMark(text: string): "usd" | "inr" | "unspecified" {
  if (/\$|\b(?:USD|dollars?)\b/iu.test(text)) return "usd";
  if (/₹|\b(?:INR|Rs\.?|rupees?|रुपये|रुपए|रुपया)\b/iu.test(text)) return "inr";
  return "unspecified";
}

/** Relative luminance of a hex colour, 0 (black) to 1 (white). */
function luminance(hex: string) {
  const [r, g, b] = [0, 2, 4].map((at) => {
    const channel = parseInt(hex.slice(at, at + 2), 16) / 255;
    return channel <= 0.03928
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

type BrandLike = Readonly<{
  name: string;
  slug: string | null;
  hex: string;
  /** Curated brand key; with `logo`, a colour logo exists for it. */
  key?: string;
  logo?: boolean;
}>;

/**
 * A brand's logo: its full-colour logo when we have one, else its one-colour
 * icon in the brand colour (black icons follow the text colour so they show
 * in dark mode). Until a logo loads, or for a brand with none, a monogram in
 * the brand's colour holds the same space.
 */
export function BrandMark({
  brand,
  size = 14,
}: {
  brand: BrandLike;
  size?: number;
}) {
  const color = useColorLogo(brand.logo && brand.key ? brand.key : null);
  const path = useBrandPath(brand.logo ? null : brand.slug);
  // Gradients inside a logo are found by id. The same logo often shows more
  // than once (and inside hidden tabs), so each copy gets its own ids.
  const scope = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const body = useMemo(
    () =>
      color?.body
        .replace(/(\s)id="([^"]+)"/g, `$1id="${scope}-$2"`)
        .replace(/url\(#([^)]+)\)/g, `url(#${scope}-$1)`)
        .replace(/href="#([^"]+)"/g, `href="#${scope}-$1"`) ?? "",
    [color, scope],
  );
  const light = luminance(brand.hex);
  const style = {
    "--brand": `#${brand.hex}`,
    "--size": `${size}px`,
  } as CSSProperties;
  if (color)
    return (
      <svg
        className={styles.logo}
        width={size}
        height={size}
        viewBox={`0 0 ${color.w} ${color.h}`}
        aria-hidden="true"
        data-ink={color.ink ? "" : undefined}
        data-mono={color.mono ? "" : undefined}
        style={style}
        // Static CC0 artwork from our own public/brands/color.json.
        dangerouslySetInnerHTML={{ __html: body }}
      />
    );
  return path ? (
    <svg
      className={styles.brandSvg}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      data-ink={light < 0.04 ? "" : undefined}
      style={style}
    >
      <path d={path} />
    </svg>
  ) : (
    <span
      className={styles.monogram}
      aria-hidden="true"
      data-light={light > 0.55 ? "" : undefined}
      style={style}
    >
      {brand.name.charAt(0)}
    </span>
  );
}

/**
 * The logo for any brand name from our 3,200-brand library, or a neutral
 * monogram when the name is not a known brand.
 */
export function BrandByName({
  name,
  size = 14,
}: {
  name: string;
  size?: number;
}) {
  const found = useIndexedBrand(name);
  return (
    <BrandMark
      brand={found ?? { name, slug: null, hex: "8A94A6" }}
      size={size}
    />
  );
}

/** One mention as an icon chip. */
export function EntityChip({ entity }: { entity: Entity }) {
  if (entity.kind === "brand" && entity.brand) {
    return (
      <span
        className={styles.chip}
        data-kind="brand"
        title={entity.brand.name}
        style={{ "--brand": `#${entity.brand.hex}` } as CSSProperties}
      >
        <BrandMark brand={entity.brand} />
        {entity.text}
      </span>
    );
  }
  if (entity.kind === "brand") return <>{entity.text}</>;
  const currency = entity.kind === "money" ? currencyMark(entity.text) : null;
  const Icon =
    currency === "usd"
      ? DollarSign
      : currency === "inr"
        ? IndianRupee
        : currency === "unspecified"
          ? Coins
          : KIND_ICONS[entity.kind];
  return (
    <span className={styles.chip} data-kind={entity.kind}>
      <Icon size={12} aria-hidden="true" />
      {entity.text}
    </span>
  );
}

/**
 * Text with its mentions shown as icon chips: brands with their logos,
 * programs, money, documents, places, dates and more, in English, Hindi and
 * Marathi. Use it anywhere report or app text is shown. `kinds` limits which
 * mentions become chips.
 */
export function RichText({
  text,
  kinds,
  brandMarks = false,
}: {
  text: string;
  kinds?: readonly EntityKind[];
  /** Logos are shown only when prospect attribution is confirmed. */
  brandMarks?: boolean;
}) {
  return (
    <>
      {findEntities(text).map((part, index) =>
        typeof part === "string" ? (
          part
        ) : kinds && !kinds.includes(part.kind) ? (
          part.text
        ) : part.kind === "brand" && !brandMarks ? (
          part.text
        ) : (
          <EntityChip key={index} entity={part} />
        ),
      )}
    </>
  );
}

/** The earlier name for RichText. */
export const EntityText = RichText;
