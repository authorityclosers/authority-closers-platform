"use client";

/**
 * The Settings frame (owner, 20 Oct): the sections down the side on a
 * computer; on a phone the list first, then one section with a way back.
 * Every section is its own address, so Back, refresh and shared links work.
 *
 * Owner's round-2 board 7 (option A, 20 Nov 2026): one Settings for the whole
 * organisation, grouped the way an owner thinks, each group saying who it
 * affects (Everyone in <organisation>, Just me, This phone); the overview has
 * the setup checklist on top.
 *
 * sx-redesign (owner 21 Nov 2026, board pick C): the overview is the hub
 * (settings-hub.tsx), a group opens its own page, and a section's frame is
 * one title row: the way back, the section's name and a tiny chip saying who
 * it affects, then one short line. No second "Settings" over it.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, LayoutGrid } from "lucide-react";

import {
  GROUP_LINE,
  GROUP_SLUG,
  groupBySlug,
  groupScope,
  isSettingsSection,
  sectionById,
  type SettingsGroup,
  type SettingsSectionId,
} from "./settings-sections";
import { useCanHere } from "../workspace-role";
import { ScopeChip } from "./scope-chip";
import {
  SettingsHub,
  useHubKind,
  useInOrganisation,
  useVisibleGroups,
} from "./settings-hub";
import styles from "./settings-shell.module.css";

export { useInOrganisation, useVisibleGroups };

export function currentSection(
  pathname: string | null,
): SettingsSectionId | null {
  const id = (pathname ?? "").split("/")[2] ?? null;
  return isSettingsSection(id) ? id : null;
}

/** The group a /settings/group/<slug> address opens; null elsewhere. */
export function currentGroup(pathname: string | null): SettingsGroup | null {
  const [, root, group, slug] = (pathname ?? "").split("/");
  return root === "settings" && group === "group" ? groupBySlug(slug) : null;
}

/**
 * While a section or group page shows its own title row, the phone's page row
 * from the app frame ("Settings") steps aside (sx-redesign: no second
 * "Settings" over the section's name).
 */
export const OWN_TITLE_ATTRIBUTE = "data-sx-settings-own-title";

function useOwnTitle(on: boolean) {
  useEffect(() => {
    if (!on) return;
    const html = document.documentElement;
    html.setAttribute(OWN_TITLE_ATTRIBUTE, "");
    return () => html.removeAttribute(OWN_TITLE_ATTRIBUTE);
  }, [on]);
}

/** Sections grouped as the list shows them. */
export function SectionList({
  current,
  variant,
}: {
  current: SettingsSectionId | null;
  variant: "nav" | "list";
}) {
  const groups = useVisibleGroups();
  const inOrganisation = useInOrganisation();
  return (
    <>
      {groups.map(({ group, sections }) => (
        <section
          key={group}
          className={styles.group}
          aria-label={group}
          data-variant={variant}
        >
          <div className={styles.groupHead}>
            <h2>{group}</h2>
            {variant === "list" ? (
              <ScopeChip scope={groupScope(group, inOrganisation)} />
            ) : null}
          </div>
          <ul>
            {sections.map(({ id, label, hint, icon: Icon }) => (
              <li key={id}>
                <Link
                  href={`/settings/${id}`}
                  className={styles.item}
                  aria-current={current === id ? "page" : undefined}
                  data-variant={variant}
                >
                  <span className={styles.icon} aria-hidden="true">
                    <Icon size={17} />
                  </span>
                  <span className={styles.text}>
                    <span className={styles.label}>{label}</span>
                    {variant === "list" ? (
                      <span className={styles.hint}>{hint}</span>
                    ) : null}
                  </span>
                  {variant === "list" ? (
                    <ChevronRight
                      size={16}
                      aria-hidden="true"
                      className={styles.chevron}
                    />
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

export function SettingsShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const current = currentSection(pathname);
  const group = current ? null : currentGroup(pathname);
  const section = current ? sectionById(current) : null;
  // A section your role can't use keeps its name, not its promise ("Your plan
  // and invoices" over a seller's billing line): the section says why itself.
  const canHere = useCanHere();
  const inOrganisation = useInOrganisation();
  const groups = useVisibleGroups();
  const kind = useHubKind();
  const promised = !section?.needs || canHere(section.needs) !== false;
  // The section it opens inside says who it is for (Privacy in Phone & alerts).
  const home = section?.within ? sectionById(section.within) : section;
  useOwnTitle(Boolean(section || group));
  // Back goes one step up: on the owner's hub a section of a group with
  // several opens from the group's page; everything else from Settings.
  const parent: SettingsGroup | null =
    home && kind === "owner"
      ? home.group === "This phone"
        ? "Just me"
        : home.group
      : null;
  const siblings = parent
    ? groups
        .filter(({ group: name }) =>
          parent === "Just me"
            ? name === "Just me" || name === "This phone"
            : name === parent,
        )
        .flatMap(({ sections }) => sections).length
    : 0;
  const back =
    parent && (siblings > 1 || parent === "Just me")
      ? {
          href: `/settings/group/${GROUP_SLUG[parent]}`,
          label: `Back to ${parent}`,
        }
      : { href: "/settings", label: "Back to Settings" };
  const title =
    section && home
      ? {
          name: section.label,
          line: promised ? section.hint : null,
          scope: groupScope(home.group, inOrganisation),
          back,
        }
      : group
        ? {
            name: group,
            line: GROUP_LINE[group],
            scope: groupScope(group, inOrganisation),
            back: { href: "/settings", label: "Back to Settings" },
          }
        : null;
  return (
    <div
      className={styles.shell}
      data-section={current ?? (group ? "group" : "index")}
    >
      <nav className={styles.nav} aria-label="Settings sections">
        <Link
          href="/settings"
          className={styles.navTitle}
          aria-current={current || group ? undefined : "page"}
        >
          <span className={styles.icon} aria-hidden="true">
            <LayoutGrid size={17} />
          </span>
          All settings
        </Link>
        <SectionList current={current} variant="nav" />
      </nav>
      <div className={styles.content} id="settings-content">
        {title ? (
          // One row: the way back, the name, who it affects; one line under.
          <header className={styles.header}>
            <div className={styles.titleRow}>
              <Link
                href={title.back.href}
                className={styles.back}
                aria-label={title.back.label}
                title={title.back.label}
              >
                <ChevronLeft size={24} aria-hidden="true" />
              </Link>
              <h1>{title.name}</h1>
              <span className={styles.scope}>
                <ScopeChip scope={title.scope} short />
              </span>
            </div>
            {title.line ? <p>{title.line}</p> : null}
          </header>
        ) : null}
        {children}
      </div>
    </div>
  );
}

/** Settings itself: the hub for whoever opened it (settings-hub.tsx). */
export function SettingsOverview() {
  return <SettingsHub />;
}
