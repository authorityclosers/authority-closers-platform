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
import {
  LeadRulesPane,
  LeadSourcesPane,
  LeadStagesPane,
} from "../leads/settings-panes";
import { OrganisationView } from "../organisation/organisation-view";
import { useApkLinksAllowed } from "../purchase-policy";
import { Panel } from "../ui/kit";
import { AiAppsSection } from "./ai-apps";
import { ConnectedApps } from "./connected-apps";
import { DevelopersSection } from "./developers";
import { ThemeControl } from "../lightbox/theme-provider";
import { PhoneSetupPanel, VibrationPanel } from "./phone-panel";
import { PrivacySettings } from "./privacy";
import { ProfileDetailsPanel } from "./profile-details";
import { SellingSettings } from "./selling";
import type { SettingsSectionId } from "./settings-sections";
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
 * Phone & alerts: the person's own switches on one screen (owner, 24 Oct
 * 2026: "simpler least steps workflows"). What this phone still needs, each
 * line one tap from its fix; lead alerts; vibration; usage analytics. Privacy
 * and Apps & devices open here too, so no page holds a single switch.
 */
function PhoneAndAlerts() {
  return (
    <div className={styles.stack}>
      {/* Owner, 24 Oct 2026: the theme choice easy to find; System follows the phone. */}
      <Panel title="Appearance">
        <div className={styles.appearance}>
          <ThemeControl />
        </div>
      </Panel>
      <PhoneSetupPanel />
      <AlertsCard />
      <VibrationPanel />
      <PrivacySettings />
      <AppPanel />
      <p className={styles.hint}>
        Product updates show under the bell at the top of the app. Sign-in
        codes, new sign-in methods and invitations always come by email.
      </p>
    </div>
  );
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
          <ProfileDetailsPanel />
          <AccountSettings only={["profile", "general"]} />
        </>
      );
    case "selling":
      return <SellingSettings />;
    case "security":
      return <AccountSettings only={["security"]} />;
    case "ai-apps":
      return <AiAppsSection />;
    case "plan":
      return <AccountSettings only={["usage", "billing"]} billing={billing} />;
    case "privacy":
      return <PrivacySettings />;
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
    case "lead-rules":
      return <LeadRulesPane />;
    case "stages":
      return <LeadStagesPane />;
    case "sources":
      return <LeadSourcesPane />;
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
    case "notifications":
    case "devices":
      return <PhoneAndAlerts />;
  }
}
