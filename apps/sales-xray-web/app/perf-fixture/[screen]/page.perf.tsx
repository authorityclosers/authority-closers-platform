import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { EXAMPLE_KINDS } from "../../xray-report/example";
import type { OutcomeKind } from "../../xray-report/model";
import { CallsPreview } from "../../review-fixture/calls/calls-preview";
import { ChatsPreview } from "../../review-fixture/chats/chats-preview";
import { HomePreview } from "../../review-fixture/home/home-preview";
import { HubPreview } from "../../review-fixture/hub/hub-preview";
import { LeadsPreview } from "../../review-fixture/leads/leads-preview";
import { NotificationsPreview } from "../../review-fixture/notifications/notifications-preview";
import { StoryShellPreview } from "../../review-fixture/report/story/preview";
import { SettingsPreview } from "../../review-fixture/settings/settings-preview";

/**
 * The speed check's screens (wb-ci --speed; the owner, 27 Oct 2026: "on low-end devices with the worst
 * processors this app might be slow"): the review fixtures' fictional screens in a production build, so a
 * throttled CPU is timed against production React, not development React. This file is a page only when the
 * build sets AC_SALES_XRAY_PERF_FIXTURES=1 (next.config.ts pageExtensions); every other build leaves it out.
 */
export const dynamic = "force-dynamic";

const SCREENS: Record<string, () => ReactNode> = {
  leads: () => <LeadsPreview />,
  home: () => <HomePreview />,
  calls: () => <CallsPreview />,
  chats: () => <ChatsPreview />,
  hub: () => <HubPreview />,
  settings: () => <SettingsPreview />,
  notifications: () => <NotificationsPreview />,
};

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ screen: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (process.env.AC_SALES_XRAY_PERF_FIXTURES !== "1") notFound();
  const { screen } = await params;
  if (screen === "report") {
    // As /review-fixture/report/story: ?example= picks the illustrative call (default follow_up).
    const { example } = await searchParams;
    const kind = EXAMPLE_KINDS.includes(example as OutcomeKind)
      ? (example as OutcomeKind)
      : "follow_up";
    return <StoryShellPreview key={kind} example={kind} clean />;
  }
  const render = SCREENS[screen];
  if (!render) notFound();
  return render();
}
