"use client";

/**
 * Everything AC does, as cards in categories: search, product, status and
 * audience filters, and a detail sheet with screenshots (fictional fixture
 * data), where the code lives and the preview link. Internal: Admin only.
 */
import {
  Brain,
  Building2,
  Code,
  ExternalLink,
  Gauge,
  GraduationCap,
  Megaphone,
  MessageCircle,
  Phone,
  Search,
  ShieldCheck,
  Smartphone,
  Target,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { blankOffer } from "../offers/offer-model";
import { useStudio, withOffer } from "../offers/offer-store";

import {
  CATALOGUE,
  NO_FILTERS,
  STATUS_LABEL,
  filterFeatures,
  groupByCategory,
  productName,
  shotFor,
  statusText,
  type Feature,
  type Filters,
  type StatusFilter,
} from "./catalogue-data";
import styles from "./catalogue.module.css";

export const CATEGORY_ICONS: Record<string, LucideIcon> = {
  phone: Phone,
  leads: Users,
  brain: Brain,
  coach: Target,
  chat: MessageCircle,
  ads: Megaphone,
  team: Building2,
  admin: Gauge,
  code: Code,
  android: Smartphone,
  academy: GraduationCap,
  shield: ShieldCheck,
};

const STATUSES: StatusFilter[] = ["all", "live", "dev", "planned"];

export function StatusPill({ feature }: { feature: Feature }) {
  return (
    <span className={styles.pill} data-status={feature.status}>
      <span className={styles.dot} aria-hidden="true" />
      {statusText(feature)}
    </span>
  );
}

function Shot({
  feature,
  size,
  className,
}: {
  feature: Feature;
  size: "390" | "1440";
  className?: string;
}) {
  const light = shotFor(feature, size, "light");
  const dark = shotFor(feature, size, "dark");
  if (!light && !dark) return null;
  return (
    <span className={`${styles.shot} ${className ?? ""}`} data-size={size}>
      {light ? (
        // eslint-disable-next-line @next/next/no-img-element -- static fixture screenshots
        <img
          className={styles.shotLight}
          src={light}
          alt={`${feature.name}, ${size === "390" ? "phone" : "computer"}`}
          loading="lazy"
        />
      ) : null}
      {dark ? (
        // eslint-disable-next-line @next/next/no-img-element -- static fixture screenshots
        <img
          className={styles.shotDark}
          src={dark}
          alt={`${feature.name}, ${size === "390" ? "phone" : "computer"}, dark`}
          loading="lazy"
        />
      ) : null}
    </span>
  );
}

function FeatureCard({
  feature,
  onOpen,
}: {
  feature: Feature;
  onOpen: (feature: Feature) => void;
}) {
  return (
    <li className={styles.card} data-status={feature.status}>
      <button
        type="button"
        className={styles.cardButton}
        onClick={() => onOpen(feature)}
        aria-label={`${feature.name}: ${feature.value}`}
      >
        <span className={styles.cardTop}>
          <StatusPill feature={feature} />
          <span className={styles.product}>{productName(feature.product)}</span>
        </span>
        <Shot feature={feature} size="1440" className={styles.cardShot} />
        <Shot feature={feature} size="390" className={styles.cardShotPhone} />
        <strong className={styles.cardName}>{feature.name}</strong>
        <span className={styles.cardValue}>{feature.value}</span>
        <span className={styles.chips}>
          {feature.for.map((who) => (
            <span key={who} className={styles.chip}>
              {who}
            </span>
          ))}
          {feature.switch ? (
            <span className={styles.chip} data-tone="warn">
              Switched off
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

/** Puts the feature in the studio's current offer (or starts one), in this browser. */
function AddToOffer({ feature }: { feature: Feature }) {
  const { studio, save } = useStudio();
  const offer =
    studio.offers.find((o) => o.id === studio.activeId) ??
    studio.offers[0] ??
    null;
  const inOffer = offer?.stack.some((s) => s.featureId === feature.id) ?? false;
  const name = offer ? offer.naming.chosen || offer.name : "";
  const toggle = () => {
    const item = { featureId: feature.id, worth: 0, label: "" };
    if (!offer) {
      const created = { ...blankOffer(), stack: [item] };
      save({
        ...studio,
        offers: [...studio.offers, created],
        activeId: created.id,
      });
      return;
    }
    save(
      withOffer(studio, {
        ...offer,
        stack: inOffer
          ? offer.stack.filter((s) => s.featureId !== feature.id)
          : [...offer.stack, item],
      }),
    );
  };
  return (
    <span className={styles.sheetActions}>
      <button
        type="button"
        className={styles.addToOffer}
        aria-pressed={inOffer}
        onClick={toggle}
      >
        {inOffer
          ? `In “${name}” · remove`
          : offer
            ? `Add to “${name}”`
            : "Start an offer with this"}
      </button>
      <Link className={styles.studioLink} href="/offers">
        Open the Offer Studio
      </Link>
    </span>
  );
}

function FeatureSheet({
  feature,
  onClose,
}: {
  feature: Feature | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (feature && !dialog.open) dialog.showModal();
    if (!feature && dialog.open) dialog.close();
  }, [feature]);
  const category = feature
    ? CATALOGUE.categories.find((c) => c.id === feature.category)
    : null;
  return (
    <dialog
      ref={ref}
      className={styles.sheet}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      aria-label={feature?.name ?? "Feature"}
    >
      {feature ? (
        <div className={styles.sheetBody}>
          <header className={styles.sheetHead}>
            <span className={styles.sheetKicker}>
              <StatusPill feature={feature} />
              <span>
                {productName(feature.product)} · {category?.name}
              </span>
            </span>
            <button
              type="button"
              className={styles.close}
              onClick={onClose}
              aria-label="Close"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          <h2 className={styles.sheetTitle}>{feature.name}</h2>
          <p className={styles.sheetValue}>{feature.value}</p>
          {feature.switch ? (
            <p className={styles.switchNote}>{feature.switch}</p>
          ) : null}
          {Object.keys(feature.shots).length ? (
            <div className={styles.sheetShots}>
              <Shot feature={feature} size="390" />
              <Shot feature={feature} size="1440" />
            </div>
          ) : null}
          {feature.details.length ? (
            <ul className={styles.details}>
              {feature.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          ) : null}
          <dl className={styles.facts}>
            <div>
              <dt>For</dt>
              <dd>{feature.for.join(", ")}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                {feature.status === "live" && feature.since
                  ? `In releases ${feature.since.or_earlier ? "by" : "since"} ${feature.since.version} (${feature.since.date})`
                  : STATUS_LABEL[feature.status]}
              </dd>
            </div>
            {feature.api.routes ? (
              <div>
                <dt>API</dt>
                <dd>
                  {feature.api.routes} routes under{" "}
                  {feature.api.prefixes.join(", ")}
                </dd>
              </div>
            ) : null}
            {feature.anchors.length ? (
              <div>
                <dt>In the code</dt>
                <dd>
                  <ul className={styles.paths}>
                    {feature.anchors.map((anchor) => (
                      <li key={anchor.anchor}>
                        <code>{anchor.path}</code>
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            ) : null}
          </dl>
          <AddToOffer feature={feature} />
          {feature.preview ? (
            <a
              className={styles.previewLink}
              href={feature.preview}
              target="_blank"
              rel="noreferrer"
            >
              Open the preview on dev
              <ExternalLink size={14} aria-hidden="true" />
            </a>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}

export function CatalogueView({
  initialQuery = "",
}: {
  initialQuery?: string;
}) {
  const [filters, setFilters] = useState<Filters>({
    ...NO_FILTERS,
    query: initialQuery,
  });
  const [open, setOpen] = useState<Feature | null>(null);
  const shown = useMemo(
    () => filterFeatures(CATALOGUE.features, filters),
    [filters],
  );
  const groups = useMemo(() => groupByCategory(shown), [shown]);
  const set = (patch: Partial<Filters>) =>
    setFilters((current) => ({ ...current, ...patch }));
  const filtered =
    filters.query !== "" ||
    filters.product !== "all" ||
    filters.status !== "all" ||
    filters.audience !== "all";

  return (
    <div className={styles.catalogue}>
      <div className={styles.toolbar} role="search">
        <label className={styles.search}>
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            value={filters.query}
            onChange={(event) => set({ query: event.target.value })}
            placeholder="Search features, e.g. WhatsApp, coaching, cost"
            aria-label="Search features"
          />
        </label>
        <div className={styles.segmented} aria-label="Status">
          {STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={filters.status === status}
              onClick={() => set({ status })}
            >
              {status === "all" ? "All" : STATUS_LABEL[status]}
              <span className={styles.count}>
                {status === "all"
                  ? CATALOGUE.features.length
                  : CATALOGUE.counts[status]}
              </span>
            </button>
          ))}
        </div>
        <div className={styles.selects}>
          <select
            value={filters.product}
            onChange={(event) => set({ product: event.target.value })}
            aria-label="Product"
          >
            <option value="all">Every product</option>
            {CATALOGUE.products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
          <select
            value={filters.audience}
            onChange={(event) => set({ audience: event.target.value })}
            aria-label="Who it's for"
          >
            <option value="all">Everyone</option>
            {CATALOGUE.audiences.map((audience) => (
              <option key={audience} value={audience}>
                {audience}
              </option>
            ))}
          </select>
        </div>
      </div>

      <nav className={styles.jump} aria-label="Categories">
        {groups.map(({ category, features }) => {
          const Icon = CATEGORY_ICONS[category.icon] ?? Gauge;
          return (
            <a key={category.id} href={`#cat-${category.id}`}>
              <Icon size={14} aria-hidden="true" />
              {category.name}
              <span className={styles.count}>{features.length}</span>
            </a>
          );
        })}
      </nav>

      {filtered ? (
        <p className={styles.resultLine} aria-live="polite">
          {shown.length} of {CATALOGUE.features.length} features
          <button type="button" onClick={() => setFilters(NO_FILTERS)}>
            Clear
          </button>
        </p>
      ) : null}

      {groups.length ? (
        groups.map(({ category, features }) => {
          const Icon = CATEGORY_ICONS[category.icon] ?? Gauge;
          return (
            <section
              key={category.id}
              id={`cat-${category.id}`}
              className={styles.section}
              aria-labelledby={`cat-${category.id}-title`}
            >
              <header className={styles.sectionHead}>
                <span className={styles.sectionIcon} data-cat={category.id}>
                  <Icon size={18} aria-hidden="true" />
                </span>
                <span>
                  <h2 id={`cat-${category.id}-title`}>{category.name}</h2>
                  <p>{category.line}</p>
                </span>
                <span className={styles.sectionCount}>{features.length}</span>
              </header>
              <ul className={styles.grid}>
                {features.map((feature) => (
                  <FeatureCard
                    key={feature.id}
                    feature={feature}
                    onOpen={setOpen}
                  />
                ))}
              </ul>
            </section>
          );
        })
      ) : (
        <p className={styles.empty}>
          No feature matches. Try fewer words or clear the filters.
        </p>
      )}

      <FeatureSheet feature={open} onClose={() => setOpen(null)} />
    </div>
  );
}
