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
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import {
  SETTINGS_GROUPS,
  SETTINGS_SECTIONS,
  groupScope,
  isSettingsSection,
  sectionById,
  type SettingsGroup,
  type SettingsSection,
  type SettingsSectionId,
} from "./settings-sections";
import { useCanHere } from "../workspace-role";
import { useWorkspaceAccess } from "../workspace-access";
import { ScopeChip } from "./scope-chip";
import { SetupChecklist } from "./setup-checklist";
import styles from "./settings-shell.module.css";

export function currentSection(
  pathname: string | null,
): SettingsSectionId | null {
  const id = (pathname ?? "").split("/")[2] ?? null;
  return isSettingsSection(id) ? id : null;
}

/**
 * Whether the open workspace is an organisation: true outside the app frame
 * (tests, previews) and while it isn't known, so nothing flickers away.
 */
export function useInOrganisation(): boolean {
  const access = useWorkspaceAccess();
  const here = access?.workspaces?.find(
    (workspace) => workspace.tenant_id === access.context?.tenantId,
  );
  return here ? here.kind === "organisation" : true;
}

/** The sections of each group this person may open, groups with none left out. */
export function useVisibleGroups(): {
  group: SettingsGroup;
  sections: SettingsSection[];
}[] {
  // A section the server would refuse your role isn't listed (Plan & billing
  // for a member of an organisation); it stays while your role is unknown.
  const canHere = useCanHere();
  const inOrganisation = useInOrganisation();
  return SETTINGS_GROUPS.map((group) => ({
    group,
    sections: SETTINGS_SECTIONS.filter(
      (item) =>
        item.group === group &&
        !item.within &&
        (!item.org || inOrganisation) &&
        (!item.needs || canHere(item.needs) !== false),
    ),
  })).filter((entry) => entry.sections.length > 0);
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
  const current = currentSection(usePathname());
  const section = current ? sectionById(current) : null;
  // A section your role can't use keeps its name, not its promise ("Your plan
  // and invoices" over a seller's billing line): the section says why itself.
  const canHere = useCanHere();
  const inOrganisation = useInOrganisation();
  const promised = !section?.needs || canHere(section.needs) !== false;
  // The section it opens inside says who it is for (Privacy in Phone & alerts).
  const home = section?.within ? sectionById(section.within) : section;
  return (
    <div className={styles.shell} data-section={current ?? "index"}>
      <nav className={styles.nav} aria-label="Settings sections">
        <Link
          href="/settings"
          className={styles.navTitle}
          aria-current={current ? undefined : "page"}
        >
          Settings
        </Link>
        <SectionList current={current} variant="nav" />
      </nav>
      <div className={styles.content} id="settings-content">
        {section && home ? (
          // The chevron beside the section's name, not on a row of its own
          // (Redmi QA on the owner's production build, 13 Nov 2026).
          <div className={styles.titleRow}>
            <Link
              href="/settings"
              className={styles.back}
              aria-label="Back to Settings"
              title="Back to Settings"
            >
              <ChevronLeft size={22} aria-hidden="true" />
            </Link>
            <header className={styles.header}>
              <h1>{section.label}</h1>
              {promised ? <p>{section.hint}</p> : null}
              <span className={styles.scope}>
                <ScopeChip scope={groupScope(home.group, inOrganisation)} />
              </span>
            </header>
          </div>
        ) : null}
        {children}
      </div>
    </div>
  );
}

/** Every section at a glance: the setup checklist, then the groups as cards. */
export function SettingsOverview() {
  return (
    <div className={styles.overview}>
      <header className={styles.overviewHead}>
        <h1>Settings</h1>
        <p>
          Your organisation, just you, and this phone. Each group says who it
          affects.
        </p>
      </header>
      <SetupChecklist />
      <div className={styles.cards}>
        <SectionList current={null} variant="list" />
      </div>
    </div>
  );
}
