"use client";

/**
 * What each Settings section holds. The account, organisation and connection
 * screens already exist; Settings gathers them (owner, 20 Oct), each in its own
 * section, and adds what had no home (notifications, apps and devices).
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { Download, RefreshCw, Smartphone } from "lucide-react";

import {
  AccountSettings,
  type SettingsBillingProps,
} from "../account-settings";
import { PLAY } from "../apps/play";
import { UnsentBeforeSwitch } from "../apps/unsent-before-switch";
import { refreshAppData } from "../shell/refresh-app";
import { ANDROID_APK_URL } from "../apps/release";
import { CallAiSettingsSection } from "../call-ai/call-ai-settings";
import { AlertsCard } from "../leads/alerts-card";
import { CaptureSetupPanel } from "../organisation/capture-setup-panel";
import { OrganisationView } from "../organisation/organisation-view";
import { OrganisationRules } from "../organisation/setup/rules";
import { OrganisationSources } from "../organisation/setup/sources";
import { OrganisationStages } from "../organisation/setup/stages";
import { PulsePanel } from "../organisation/pulse/pulse-panel";
import { BILLING_WITH_OWNER, useApkLinksAllowed } from "../purchase-policy";
import { Panel } from "../ui/kit";
import { AiAppsSection } from "./ai-apps";
import { AnalysisTimeSection } from "./analysis-time";
import { ConnectedApps } from "./connected-apps";
import { DevelopersSection } from "./developers";
import { NotificationPrefs } from "./notification-prefs";
import { MicrophoneCard } from "../organisation/setup/microphone";
import { PhoneSetupPanel, VibrationPanel } from "./phone-panel";
import { PrivacySettings } from "./privacy";
import { CallUploads } from "./call-uploads/call-uploads";
import { ProfileDetailsPanel } from "./profile-details";
import { SellingSettings } from "./selling";
import { ThemePills } from "./theme-pills";
import { MySounds, TeamSounds } from "./sounds";
import type { SettingsSectionId } from "./settings-sections";
import { useCanHere } from "../workspace-role";
import styles from "./sections.module.css";

function Note({
  icon,
  title,
  children,
  href,
  action,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  href?: string;
  action?: string;
}) {
  return (
    <div className={styles.note}>
      <span className={styles.noteIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.noteText}>
        <strong>{title}</strong>
        <span>{children}</span>
      </span>
      {href && action ? (
        <Link href={href} className={styles.noteAction}>
          {action}
        </Link>
      ) : null}
    </div>
  );
}

/** The app on this phone: from Google Play, or the download link. */
function AppPanel() {
  // The Google Play app updates only through Play: no APK link there (Play policy).
  const apkLinks = useApkLinksAllowed();
  return (
    <Panel title="Sales X-Ray on your phone">
      {apkLinks ? (
        <>
          <Note icon={<Download size={18} />} title="Android app">
            Calls, leads and alerts on your phone. {PLAY.switching}
            <UnsentBeforeSwitch />
          </Note>
          {/* Google Play first (24 Oct 2026); the file stays for people
              without a Play invite. */}
          <a className={styles.download} href={PLAY.url} rel="noopener">
            {PLAY.get}
          </a>
          <a className={styles.fileLink} href={ANDROID_APK_URL} rel="noopener">
            {PLAY.file}
          </a>
        </>
      ) : (
        <Note icon={<Smartphone size={18} />} title="Android app">
          You&apos;re using Sales X-Ray from Google Play. Updates come from
          Google Play.
        </Note>
      )}
      {/* Orchestrator, 24 Oct 2026: never reinstall to recover. */}
      <Note icon={<RefreshCw size={18} />} title="Refresh app data">
        If a screen hangs, this starts Sales X-Ray afresh. You stay signed in,
        and changes not sent yet are kept.
      </Note>
      <button
        type="button"
        className={styles.textButton}
        onClick={() => void refreshAppData()}
      >
        Refresh app data
      </button>
    </Panel>
  );
}

/**
 * Phone & alerts: what reaches this phone and when (owner, 24 Oct 2026:
 * "simpler least steps workflows"): lead alerts, reminders, vibration and
 * usage analytics. v1.96 (device polish): no Appearance and no app here; the
 * phone app, its setup and the look are Apps & devices.
 */
function PhoneAndAlerts() {
  return (
    <div className={styles.stack}>
      <AlertsCard />
      {/* What reaches this phone and when (competitor teardown 26). */}
      <NotificationPrefs />
      <VibrationPanel />
      <PrivacySettings />
      <p className={styles.hint}>
        Product updates show under the bell at the top of the app. Sign-in
        codes, new sign-in methods and invitations always come by email.
      </p>
    </div>
  );
}

/**
 * Apps & devices: the phone app, its setup and call recording, then this
 * device's own look and microphone (v1.96 device polish: it opened on the
 * same Appearance and Notifications as Phone & alerts).
 */
function AppsAndDevices() {
  return (
    <div className={styles.stack}>
      <AppPanel />
      <PhoneSetupPanel />
      <Panel title="Look on this device">
        <div className={styles.look}>
          <span id="device-look">Light or dark, on this device only.</span>
          <ThemePills labelledBy="device-look" />
        </div>
      </Panel>
      <MicrophoneCard />
    </div>
  );
}

/**
 * Plan & usage for whoever pays. A member of an organisation reads one calm
 * line instead: no plan, no price, no top-up (roles.ts "billing.view"). It
 * waits while your role is unknown, so a price never shows first. Plan &
 * billing alone: it already names the analysis time and the top-up, so the
 * usage pane's second copy of both and its call counts (the Dashboard's) are
 * gone (owner, production report 124, 3 Nov 2026).
 */
function PlanSection({ billing }: { billing?: SettingsBillingProps }) {
  const canHere = useCanHere();
  const pays = canHere("billing.view");
  if (pays === null) return null;
  if (!pays) return <p className={styles.hint}>{BILLING_WITH_OWNER}</p>;
  return <AccountSettings only={["billing"]} billing={billing} />;
}

export function SettingsSectionView({
  id,
  billing,
  headless = false,
}: {
  id: SettingsSectionId;
  /** Inside the organisation hub, which has the organisation's header. */
  headless?: boolean;
  /** Plan & usage's billing from elsewhere (review pages); else it reads its own. */
  billing?: SettingsBillingProps;
}) {
  switch (id) {
    case "profile":
      return (
        <>
          {/* One profile card with one status: name, email and phone are in
              it too (owner, 3 Nov 2026: "Your profile 2 of 6" beside
              "Profile: Complete" said two things). */}
          <ProfileDetailsPanel />
          <AccountSettings only={["general"]} />
        </>
      );
    case "selling":
      return <SellingSettings />;
    case "security":
      return <AccountSettings only={["security"]} />;
    case "ai-apps":
      return <AiAppsSection />;
    case "plan":
      return <PlanSection billing={billing} />;
    case "analysis-time":
      return <AnalysisTimeSection />;
    case "privacy":
      return <PrivacySettings />;
    case "sounds":
      return <MySounds />;
    case "team-sounds":
      return <TeamSounds />;
    case "help":
      return <AccountSettings only={["help"]} />;
    case "organisation":
      return (
        <OrganisationView embedded headless={headless} sections={["company"]} />
      );
    case "team":
      return (
        <OrganisationView embedded headless={headless} sections={["members"]} />
      );
    // The Leads setup the Organisation hub had, in Settings again (round-2
    // board 7, 20 Nov 2026): each part its own section, so no row of tabs.
    case "lead-rules":
      return <OrganisationRules />;
    case "stages":
      // The section's title names it: no second one (owner, bug 192).
      return <OrganisationStages bare />;
    case "sources":
      return <OrganisationSources />;
    case "phones":
      return <CaptureSetupPanel />;
    case "call-ai":
      return <CallAiSettingsSection />;
    case "apps":
      return <ConnectedApps />;
    case "ai-replies":
      return (
        <OrganisationView
          embedded
          sections={["integrations"]}
          integrationParts={["ai"]}
        />
      );
    case "developers":
      return <DevelopersSection />;
    case "pulse":
      return <PulsePanel />;
    case "notifications":
      return <PhoneAndAlerts />;
    case "call-uploads":
      return <CallUploads />;
    case "devices":
      return <AppsAndDevices />;
  }
}
