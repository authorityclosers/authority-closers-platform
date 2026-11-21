"use client";

/**
 * The Settings hub (sx-redesign, owner 21 Nov 2026: "Organisation, Settings
 * and mobile are bad"; he loves the v1.90 Home look). Board pick C, "Summary
 * first", for both people who open it:
 *
 * - An owner, admin or manager: one hero with the setup ring, the next step
 *   and one green button; then a card for each company group under "For
 *   everyone" and one card under "Just me". Each card is a dark icon tile, the
 *   group's name and one short line; it opens the group's page, or the section
 *   itself when the group has only one.
 * - A seller (or a personal workspace): one hero when call recording matters
 *   ("Call recording is on", a button only when something is wrong), who you
 *   are, then short rows: Just me, This phone, the company's few, Look (Light
 *   or Dark) and Sign out in red at the bottom.
 *
 * Nothing here deletes anything; every section keeps its own address.
 */
import Link from "next/link";
import {
  ChevronRight,
  LogOut,
  Moon,
  PhoneCall,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { useSalesXraySignOut } from "../account-navigation";
import {
  readCaptureSetup,
  type CaptureSetup,
} from "../capture-setup/capture-setup-client";
import { useTheme } from "../lightbox/theme-provider";
import { roleLabel } from "../organisation/roles";
import { accountInitials } from "../shell/account-initials";
import { useShellProfile } from "../shell/profile-store";
import { AccountAvatarImage } from "../speaker-avatar";
import { useWorkspaceAccess } from "../workspace-access";
import { useCanHere } from "../workspace-role";
import { readAiApps } from "./ai-apps-client";
import {
  GROUP_ICON,
  GROUP_LINE,
  GROUP_SLUG,
  SETTINGS_GROUPS,
  SETTINGS_SECTIONS,
  groupPageGroups,
  type SettingsGroup,
  type SettingsSection,
  type SettingsSectionId,
} from "./settings-sections";
import { SetupHero, useSetup, type SetupFacts } from "./setup-checklist";
import { ThemePills } from "./theme-pills";
import styles from "./settings-hub.module.css";

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

/** The groups that set things for the whole company, not just you. */
const PERSONAL_GROUPS: readonly SettingsGroup[] = ["Just me", "This phone"];

/**
 * Which hub this person gets: the owner's (setup and company cards) where
 * they can set the company up, or while the role is still unknown; the
 * seller's everywhere else, a personal workspace included.
 */
export function useHubKind(): "owner" | "personal" {
  const canHere = useCanHere();
  const inOrganisation = useInOrganisation();
  return inOrganisation && canHere("leads.manage") !== false
    ? "owner"
    : "personal";
}

/** Where a group's card goes: its one section, or its own page. */
export function groupHref(
  group: SettingsGroup,
  sections: readonly SettingsSection[],
): string {
  return sections.length === 1 && !PERSONAL_GROUPS.includes(group)
    ? `/settings/${sections[0].id}`
    : `/settings/group/${GROUP_SLUG[group]}`;
}

/** One short line for a company card, from what the setup reads found. */
export function groupLine(
  group: SettingsGroup,
  facts: SetupFacts | null,
): string {
  if (facts) {
    if (group === "Team" && facts.people !== undefined) {
      const people = `${facts.people} ${facts.people === 1 ? "person" : "people"}`;
      return facts.invited ? `${people} · ${facts.invited} invited` : people;
    }
    if (group === "Calls & phones" && facts.phonesTotal !== undefined) {
      return facts.phonesTotal === 0
        ? "No sellers' phones yet"
        : `Sellers' phones ${facts.phonesReady ?? 0} of ${facts.phonesTotal} ready`;
    }
    if (group === "Connections" && facts.appsConnected !== undefined) {
      return facts.appsConnected === 0
        ? "Nothing connected yet"
        : `${facts.appsConnected} ${facts.appsConnected === 1 ? "app" : "apps"} connected`;
    }
    if (group === "Company" && facts.companyDone !== undefined) {
      return facts.companyDone
        ? "Logo and details added"
        : "Add your logo and details";
    }
  }
  return GROUP_LINE[group];
}

function IconTile({ icon: Icon, tone }: { icon: LucideIcon; tone?: "bad" }) {
  return (
    <span className={styles.tile} data-tone={tone} aria-hidden="true">
      <Icon size={20} strokeWidth={1.9} />
    </span>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <h2 className={styles.label}>{children}</h2>;
}

/** A group's card on the owner's hub. */
function GroupCard({
  group,
  sections,
  line,
}: {
  group: SettingsGroup;
  sections: readonly SettingsSection[];
  line: string;
}) {
  return (
    <Link
      href={groupHref(group, sections)}
      className={styles.card}
      data-group={GROUP_SLUG[group]}
    >
      <IconTile icon={GROUP_ICON[group]} />
      <span className={styles.text}>
        <span className={styles.name}>{group}</span>
        <span className={styles.line}>{line}</span>
      </span>
      <ChevronRight size={18} aria-hidden="true" className={styles.chevron} />
    </Link>
  );
}

/** The owner's hub: setup first, then the company's cards, then yours. */
function OwnerHub() {
  const setup = useSetup();
  const groups = useVisibleGroups();
  const company = groups.filter(
    ({ group }) => !PERSONAL_GROUPS.includes(group),
  );
  const mine = groups.filter(({ group }) => PERSONAL_GROUPS.includes(group));
  const mineSections = mine.flatMap(({ sections }) => sections);
  const phoneSections =
    mine.find(({ group }) => group === "This phone")?.sections ?? [];
  return (
    <>
      <SetupHero setup={setup} />
      {company.length > 0 ? (
        <section className={styles.block} aria-label="For everyone">
          <Label>For everyone</Label>
          <div className={styles.grid}>
            {company.map(({ group, sections }) => (
              <GroupCard
                key={group}
                group={group}
                sections={sections}
                line={groupLine(group, setup?.facts ?? null)}
              />
            ))}
          </div>
        </section>
      ) : null}
      {mineSections.length > 0 ? (
        <section className={styles.block} aria-label="Just me">
          <Label>Just me</Label>
          {/* Two cards, so a laptop's row is never a lone half (judge, 21 Nov 2026). */}
          <div className={styles.grid}>
            <GroupCard
              group="Just me"
              sections={mineSections}
              line="Profile, sounds, sign-in"
            />
            {phoneSections.length > 0 ? (
              <GroupCard
                group="This phone"
                sections={phoneSections}
                line={GROUP_LINE["This phone"]}
              />
            ) : null}
          </div>
        </section>
      ) : null}
    </>
  );
}

/** One short row: dark icon tile, bold name, a quiet value, chevron. */
function Row({
  section,
  value,
  hint = false,
}: {
  section: SettingsSection;
  value?: string | null;
  /** A group's page says what each is for, in one line under its name. */
  hint?: boolean;
}) {
  return (
    <li>
      <Link
        href={`/settings/${section.id}`}
        className={styles.row}
        data-section={section.id}
      >
        <IconTile icon={section.icon} />
        <span className={styles.text}>
          <span className={styles.rowName}>{section.label}</span>
          {hint ? <span className={styles.line}>{section.hint}</span> : null}
        </span>
        {value ? <span className={styles.value}>{value}</span> : null}
        <ChevronRight size={18} aria-hidden="true" className={styles.chevron} />
      </Link>
    </li>
  );
}

function Rows({
  label,
  showLabel = true,
  sections,
  values = {},
  hint = false,
  children,
}: {
  label: string;
  /** A group's page with one list: the title above already names it. */
  showLabel?: boolean;
  sections: readonly SettingsSection[];
  values?: Partial<Record<SettingsSectionId, string | null>>;
  hint?: boolean;
  children?: ReactNode;
}) {
  if (sections.length === 0 && !children) return null;
  return (
    <section className={styles.block} aria-label={label}>
      {showLabel ? <Label>{label}</Label> : null}
      <ul className={styles.rows}>
        {sections.map((section) => (
          <Row
            key={section.id}
            section={section}
            value={values[section.id]}
            hint={hint}
          />
        ))}
        {children}
      </ul>
    </section>
  );
}

/** The Look row: Light or Dark. */
export function LookRow() {
  const theme = useTheme();
  if (!theme) return null;
  return (
    <li className={styles.look}>
      <IconTile icon={theme.preference === "dark" ? Moon : Sun} />
      <span className={styles.rowName} id="settings-look">
        Look
      </span>
      <ThemePills labelledBy="settings-look" />
    </li>
  );
}

/** Sign out: quiet red words at the bottom, never a big button. */
export function SignOutRow() {
  const { signOut, signingOut, error } = useSalesXraySignOut();
  return (
    <li>
      <button
        type="button"
        className={styles.signOut}
        onClick={() => void signOut()}
        disabled={signingOut}
      >
        <IconTile icon={LogOut} tone="bad" />
        <span className={styles.text}>
          <span>{signingOut ? "Signing out…" : "Sign out"}</span>
          {error ? (
            <span className={styles.error} role="alert">
              {error}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

/** Sign out on its own, the last card. */
function SignOutCard() {
  return (
    <section className={styles.block} aria-label="Sign out">
      <ul className={styles.rows}>
        <SignOutRow />
      </ul>
    </section>
  );
}

/** What call recording on your phone needs, if anything. */
export type RecordingState =
  | { kind: "on"; app: string | null }
  | { kind: "no-phone" }
  | { kind: "fix" }
  | { kind: "off" };

export function recordingState(setup: CaptureSetup): RecordingState | null {
  if (setup.consent !== "on")
    return setup.required && setup.consent !== "unavailable"
      ? { kind: "off" }
      : null;
  const newest = [...setup.phones].sort((a, b) => b.at.localeCompare(a.at))[0];
  if (!newest) return setup.required ? { kind: "no-phone" } : null;
  if (!newest.recordings) return { kind: "fix" };
  return { kind: "on", app: newest.app_version || null };
}

const RECORDING: Record<
  RecordingState["kind"],
  { title: string; line?: string; action?: string; href?: string }
> = {
  on: { title: "Call recording is on" },
  "no-phone": {
    title: "Set up your phone",
    line: "Then your calls are recorded and get reports.",
    action: "Set up phone",
    href: "/settings/notifications",
  },
  fix: {
    title: "Call recording needs a fix",
    line: "Your phone's recordings are not reaching us.",
    action: "Fix phone setup",
    href: "/settings/notifications",
  },
  off: {
    title: "Call recording is off",
    line: "Turn it on so your calls get reports.",
    action: "Turn on call recording",
    href: "/settings/privacy",
  },
};

/** Your call recording, read once; null while unknown or when it fails. */
function useRecording(enabled: boolean): RecordingState | null {
  const [state, setState] = useState<RecordingState | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    readCaptureSetup(controller.signal).then(
      (setup) => {
        if (!controller.signal.aborted) setState(recordingState(setup));
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [enabled]);
  return enabled ? state : null;
}

/** The seller's one hero: recording on (no button), or what to fix (one button). */
function RecordingHero({ state }: { state: RecordingState | null }) {
  if (!state) return null;
  const words = RECORDING[state.kind];
  const ok = state.kind === "on";
  return (
    <section
      className={styles.hero}
      data-tone={ok ? "good" : "warn"}
      aria-label="Call recording"
    >
      <span className={styles.heroTile} aria-hidden="true">
        <PhoneCall size={24} strokeWidth={1.9} />
      </span>
      <div className={styles.heroWords}>
        <h2>{words.title}</h2>
        {ok ? (
          <p className={styles.chips}>
            <span className={styles.chip} data-tone="good">
              Phone setup done
            </span>
            {state.app ? (
              <span className={styles.chip}>App {state.app}</span>
            ) : null}
          </p>
        ) : (
          <p className={styles.heroLine}>{words.line}</p>
        )}
      </div>
      {!ok && words.href && words.action ? (
        <Link href={words.href} className={styles.go}>
          {words.action}
        </Link>
      ) : null}
    </section>
  );
}

/** Who you are, with a quiet way to your profile. */
function ProfileCard() {
  const access = useWorkspaceAccess();
  const profile = useShellProfile(access?.authenticated === true);
  const here = access?.workspaces?.find(
    (workspace) => workspace.tenant_id === access.context?.tenantId,
  );
  const name = profile?.name?.trim() || null;
  const email = profile?.email ?? null;
  const line =
    here?.kind === "organisation"
      ? `${roleLabel(here.role)} · ${here.name}`
      : (email ?? "Personal");
  return (
    <section className={styles.profile} aria-label="You">
      <span className={styles.avatar} aria-hidden="true">
        <AccountAvatarImage key={email ?? ""} photoUrl={profile?.photo_url}>
          {accountInitials(name, email) || "You"}
        </AccountAvatarImage>
      </span>
      <span className={styles.text}>
        <span className={styles.profileName}>{name ?? "Your profile"}</span>
        <span className={styles.line}>{line}</span>
      </span>
      <Link href="/settings/profile" className={styles.quiet}>
        Edit profile
      </Link>
    </section>
  );
}

/** How many AI apps you connected: "2 on", "Off"; null while unknown. */
function useAiAppsValue(): string | null {
  const signedIn = useWorkspaceAccess()?.authenticated === true;
  const [value, setValue] = useState<string | null>(null);
  useEffect(() => {
    if (!signedIn) return;
    const controller = new AbortController();
    readAiApps(controller.signal).then(
      (apps) => {
        if (!controller.signal.aborted)
          setValue(apps.length > 0 ? `${apps.length} on` : "Off");
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [signedIn]);
  return value;
}

/** Sections of a group as rows: those listed on their own and those that open inside another. */
function groupSections(group: SettingsGroup, listed: SettingsSection[]) {
  const ids = new Set(listed.map((section) => section.id));
  return SETTINGS_SECTIONS.filter(
    (section) =>
      section.group === group && (ids.has(section.id) || section.within),
  );
}

/** The seller's hub (and a personal workspace's). */
function PersonalHub() {
  const groups = useVisibleGroups();
  const inOrganisation = useInOrganisation();
  const signedIn = useWorkspaceAccess()?.authenticated === true;
  const recording = useRecording(signedIn);
  const ai = useAiAppsValue();
  const listed = (group: SettingsGroup) =>
    groups.find((entry) => entry.group === group)?.sections ?? [];
  const mine = groupSections("Just me", listed("Just me")).filter(
    (section) => section.id !== "profile",
  );
  const phone = groupSections("This phone", listed("This phone"));
  const company = groups
    .filter(({ group }) => !PERSONAL_GROUPS.includes(group))
    .flatMap(({ sections }) => sections);
  const values: Partial<Record<SettingsSectionId, string | null>> = {
    "ai-apps": ai,
    notifications:
      recording?.kind === "on" ? "Ready" : recording ? "Needs a fix" : null,
    devices:
      recording?.kind === "on" && recording.app ? `App ${recording.app}` : null,
  };
  return (
    <>
      <RecordingHero state={recording} />
      <ProfileCard />
      <Rows label="Just me" sections={mine} values={values} />
      <Rows label="This phone" sections={phone} values={values}>
        <LookRow />
      </Rows>
      <Rows
        label={inOrganisation ? "For everyone" : "Plan"}
        sections={company}
      />
      <SignOutCard />
    </>
  );
}

/** /settings: the hub for whoever opened it. */
export function SettingsHub() {
  const kind = useHubKind();
  return (
    <div className={styles.hub} data-hub={kind}>
      {/* The top bar already says Settings: the heading is for readers. */}
      <h1 className={styles.readerOnly}>Settings</h1>
      {kind === "owner" ? <OwnerHub /> : <PersonalHub />}
    </div>
  );
}

/**
 * A group's own page (/settings/group/<slug>): its sections as rows, each
 * with one line on what it is for. "Just me" lists "This phone" too, then
 * Look and Sign out.
 */
export function SettingsGroupView({ group }: { group: SettingsGroup }) {
  const groups = useVisibleGroups();
  const listed = (name: SettingsGroup) =>
    groups.find((entry) => entry.group === name)?.sections ?? [];
  const shown = groupPageGroups(group);
  return (
    <div className={styles.hub} data-hub="group">
      {shown.map((name) => (
        <Rows
          key={name}
          label={name}
          showLabel={shown.length > 1}
          sections={
            PERSONAL_GROUPS.includes(name)
              ? groupSections(name, listed(name))
              : listed(name)
          }
          hint
        />
      ))}
      {group === "Just me" ? (
        <>
          <section className={styles.block} aria-label="Look">
            <ul className={styles.rows}>
              <LookRow />
            </ul>
          </section>
          <SignOutCard />
        </>
      ) : null}
    </div>
  );
}
