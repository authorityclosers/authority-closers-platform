"use client";

/**
 * The Settings frame (owner, 20 Oct): the sections down the side on a
 * computer; on a phone the list first, then one section with a way back.
 * Every section is its own address, so Back, refresh and shared links work.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";

import {
  SETTINGS_GROUPS,
  SETTINGS_LINKS,
  SETTINGS_SECTIONS,
  hubAddress,
  isSettingsSection,
  sectionById,
  type SettingsSectionId,
} from "./settings-sections";
import styles from "./settings-shell.module.css";

export function currentSection(
  pathname: string | null,
): SettingsSectionId | null {
  const id = (pathname ?? "").split("/")[2] ?? null;
  return isSettingsSection(id) ? id : null;
}

/** Sections grouped as the list shows them. */
export function SectionList({
  current,
  variant,
}: {
  current: SettingsSectionId | null;
  variant: "nav" | "list";
}) {
  return (
    <>
      {SETTINGS_GROUPS.map((group) => (
        <section key={group} className={styles.group} aria-label={group}>
          <h2>{group}</h2>
          <ul>
            {SETTINGS_SECTIONS.filter(
              (item) => item.group === group && !hubAddress(item.id),
            ).map(({ id, label, hint, icon: Icon }) => (
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
            {SETTINGS_LINKS.filter((item) => item.group === group).map(
              ({ key, href, label, hint, icon: Icon }) => (
                <li key={key}>
                  <Link
                    href={href}
                    className={styles.item}
                    data-variant={variant}
                    data-elsewhere=""
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
                    ) : (
                      <ArrowUpRight
                        size={14}
                        aria-hidden="true"
                        className={styles.chevron}
                      />
                    )}
                  </Link>
                </li>
              ),
            )}
          </ul>
        </section>
      ))}
    </>
  );
}

export function SettingsShell({ children }: { children: ReactNode }) {
  const current = currentSection(usePathname());
  const section = current ? sectionById(current) : null;
  return (
    <div className={styles.shell} data-section={current ?? "index"}>
      <nav className={styles.nav} aria-label="Settings sections">
        <p className={styles.navTitle}>Settings</p>
        <SectionList current={current} variant="nav" />
      </nav>
      <div className={styles.content} id="settings-content">
        {section ? (
          <>
            <Link href="/settings" className={styles.back}>
              <ChevronLeft size={16} aria-hidden="true" />
              Settings
            </Link>
            <header className={styles.header}>
              <h1>{section.label}</h1>
              <p>{section.hint}</p>
            </header>
          </>
        ) : null}
        {children}
      </div>
    </div>
  );
}

/** Every section at a glance: the list on a phone, cards on a computer. */
export function SettingsOverview() {
  return (
    <div className={styles.overview}>
      <header className={styles.overviewHead}>
        <h1>Settings</h1>
        <p>
          Your account, your organisation, the apps you connect and this device.
        </p>
      </header>
      <SectionList current={null} variant="list" />
    </div>
  );
}
