"use client";

/**
 * An app's logo on a tile, for Settings' sign-in methods and connected apps
 * (owner, 20 Oct: one card per app, with its logo). Logos come from the brand
 * library (brands/brand-registry, public/brands); Sales Xray's own features
 * get a line icon on an accent tile. Decorative: every use names the app.
 */
import type { CSSProperties } from "react";
import type { LucideIcon } from "lucide-react";

import { BRANDS, type Brand } from "../brands/brand-registry";
import { BrandMark } from "../report-entities";
import styles from "./brand-tile.module.css";

const brand = (key: string): Brand | undefined =>
  BRANDS.find((item) => item.key === key);

export function BrandTile({
  brands,
  icon: Icon,
  size = 36,
}: {
  /** Brand keys from the brand library; a second one sits on the corner. */
  brands?: readonly string[];
  icon?: LucideIcon;
  size?: number;
}) {
  const [first, second] = (brands ?? [])
    .map(brand)
    .filter((item): item is Brand => !!item);
  return (
    <span
      className={styles.tile}
      data-kind={first ? "brand" : "icon"}
      data-brand={first?.key}
      style={{ "--tile": `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      {first ? (
        <BrandMark brand={first} size={Math.round(size * 0.58)} />
      ) : Icon ? (
        <Icon size={Math.round(size * 0.5)} strokeWidth={1.9} />
      ) : null}
      {second ? (
        <span className={styles.corner} data-brand={second.key}>
          <BrandMark brand={second} size={Math.round(size * 0.34)} />
        </span>
      ) : null}
    </span>
  );
}
