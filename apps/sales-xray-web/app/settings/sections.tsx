"use client";

/**
 * What each Settings section holds. The account, organisation and connection
 * screens already exist; Settings gathers them (owner, 20 Oct), each in its own
 * section, and adds what had no home (notifications, apps and devices).
 */
import Link from "next/link";
import type { ReactNode } from "react";
import {
  BellRing,
  Download,
  Megaphone,
  PhoneCall,
  Smartphone,
} from "lucide-react";

import {
  AccountSettings,
  type SettingsBillingProps,
} from "../account-settings";
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
import { ConnectedApps } from "./connected-apps";
import { DevelopersSection } from "./developers";
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

function Notifications() {
  return (
    <div className={styles.stack}>
      <AlertsCard />
      <Panel title="Where you hear from Sales X-Ray">
        <Note icon={<BellRing size={18} />} title="Lead alerts on your phone">
          A new lead or a call that is due shows on your phone. Turn them on in
          the Sales X-Ray phone app; your phone&rsquo;s settings can turn them
          off.
        </Note>
        <Note icon={<Megaphone size={18} />} title="What's new">
          Product updates show under the bell at the top of the app.
        </Note>
        <Note icon={<Smartphone size={18} />} title="Account emails">
          Sign-in codes, new sign-in methods and invitations always come by
          email, so you know when your account changes.
        </Note>
      </Panel>
    </div>
  );
}

function Devices() {
  // The Google Play app updates only through Play: no APK link there (Play policy).
  const apkLinks = useApkLinksAllowed();
  return (
    <div className={styles.stack}>
      <Panel title="Sales X-Ray on your phone">
        {apkLinks ? (
          <>
            <Note
              icon={<Download size={18} />}
              title="Android app"
              href="/apps"
              action="Get the app"
            >
              Calls, leads and alerts on your phone. It can also pick up your
              call recordings for analysis.
            </Note>
            <a
              className={styles.download}
              href={ANDROID_APK_URL}
              rel="noopener"
            >
              Download for Android
            </a>
          </>
        ) : (
          <Note icon={<Smartphone size={18} />} title="Android app">
            You&apos;re using Sales X-Ray from Google Play. Updates come from
            Google Play.
          </Note>
        )}
      </Panel>
      <Panel title="Call recording">
        <Note
          icon={<PhoneCall size={18} />}
          title="Phone setup"
          href="/leads#phone-setup"
          action="Set up this phone"
        >
          Let the app find your call recordings so every sales call can be
          analysed.
        </Note>
      </Panel>
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
      return <AccountSettings only={["profile", "general"]} />;
    case "selling":
      return <SellingSettings />;
    case "security":
      return <AccountSettings only={["security"]} />;
    case "plan":
      return <AccountSettings only={["usage", "billing"]} billing={billing} />;
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
      return <Notifications />;
    case "devices":
      return <Devices />;
  }
}
