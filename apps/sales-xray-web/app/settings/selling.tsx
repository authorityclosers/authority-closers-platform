"use client";

/**
 * Settings → Selling (owner, 22 Oct 2026: salespeople need "much more
 * settings"). What a salesperson sets for their own selling, in one place:
 * whether new leads come to them, calling and call logging from this phone,
 * lead alerts, and what AI does with their calls. Managers set the team's
 * rules on Leads → Team and in AI on calls; here each person sees their own.
 */

import {
  BellRing,
  Building2,
  PhoneCall,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { readCallAi, type CallAiSettings } from "../call-ai/call-ai-client";
import { AlertsCard } from "../leads/alerts-card";
import { readMe, type Desk } from "../leads/leads-client";
import { PhoneLogCard } from "../leads/phone-log-card";
import { TakingSwitch } from "../leads/taking-switch";
import { Panel, Skeleton } from "../ui/kit";
import styles from "./sections.module.css";

function Line({
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

type Read<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | {
      status: "none";
    };

export function SellingSettings() {
  const [me, setMe] = useState<Read<Desk["me"]>>({ status: "loading" });
  const [ai, setAi] = useState<Read<CallAiSettings>>({ status: "loading" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    readMe(controller.signal)
      .then((value) => setMe({ status: "ready", value }))
      .catch(() => {
        // Outside an organisation there is no lead desk: no leads to take.
        if (!controller.signal.aborted) setMe({ status: "none" });
      });
    readCallAi(controller.signal)
      .then((value) => setAi({ status: "ready", value }))
      .catch(() => {
        if (!controller.signal.aborted) setAi({ status: "none" });
      });
    return () => controller.abort();
  }, [version]);

  if (me.status === "none")
    return (
      <div className={styles.stack}>
        <Panel title="Selling">
          <Line
            icon={<Building2 size={18} />}
            title="Leads work inside an organisation"
            href="/leads"
            action="Open Leads"
          >
            Switch to your organisation to take leads, call them and see your
            selling settings.
          </Line>
        </Panel>
      </div>
    );

  const level =
    ai.status === "ready"
      ? ai.value.levels.find((item) => item.id === ai.value.you.level)
      : null;

  return (
    <div className={styles.stack}>
      <Panel title="New leads">
        {me.status === "loading" ? (
          <Skeleton height={56} />
        ) : (
          <TakingSwitch
            key={`taking-${me.value.taking_leads !== false}`}
            initial={me.value.taking_leads !== false}
            place="row"
            pausedUntil={me.value.paused_until ?? null}
            onChanged={() => setVersion((value) => value + 1)}
          />
        )}
        <p className={styles.hint}>
          Your languages, areas and how many open leads you hold are set by your
          owner or admin in Leads → Team.
        </p>
      </Panel>

      <Panel title="Calling from this phone">
        {/* Inside the Sales Xray phone app only; nothing shows in a browser. */}
        <PhoneLogCard />
        <Line
          icon={<PhoneCall size={18} />}
          title="Phone setup"
          href="/leads#phone-setup"
          action="Set up"
        >
          Calls, recordings, alerts and battery, checked once so every call
          lands on its lead.
        </Line>
        <Line icon={<ShieldCheck size={18} />} title="Private calls">
          Only calls with your leads are logged; every other number stays on
          your phone. A logged call you mark private shows to you alone.
        </Line>
      </Panel>

      <Panel title="Lead alerts">
        <AlertsCard />
        <Line
          icon={<BellRing size={18} />}
          title="New leads and calls due"
          href="/settings/notifications"
          action="Notifications"
        >
          Your phone tells you when a new lead comes in or a call is due.
        </Line>
      </Panel>

      <Panel title="AI on your calls">
        {ai.status === "loading" ? (
          <Skeleton height={56} />
        ) : level ? (
          <Line
            icon={<Sparkles size={18} />}
            title={level.name}
            href={
              ai.status === "ready" && ai.value.can_edit
                ? "/settings/call-ai"
                : undefined
            }
            action={
              ai.status === "ready" && ai.value.can_edit ? "Change" : undefined
            }
          >
            {level.hint}
            {ai.status === "ready" && !ai.value.can_edit
              ? " Your owner or admin chooses this."
              : ""}
          </Line>
        ) : (
          <p className={styles.hint}>
            Your organisation chooses what AI does with recorded calls.
          </p>
        )}
      </Panel>
    </div>
  );
}
