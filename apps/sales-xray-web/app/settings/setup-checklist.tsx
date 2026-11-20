"use client";

/**
 * What's left to set up, on top of Settings (owner's round-2 board 7, option
 * A with B's checklist, 20 Nov 2026): "Your organisation is 4 of 5 set up",
 * each thing still to do one tap from its page. Owners, admins and managers of
 * an organisation; read from what the app already reads (the company, seats,
 * connected apps, working hours, sellers' phones). A read that fails leaves
 * its line out rather than guessing.
 */
import Link from "next/link";
import { CheckCircle2, ChevronRight, Circle } from "lucide-react";
import { useEffect, useState } from "react";

import { readCaptureTeam } from "../capture-setup/capture-setup-client";
import {
  readOrganisationSettings,
  readSeats,
} from "../organisation/organisation-api";
import { useWorkspaceAccess } from "../workspace-access";
import { useCanHere } from "../workspace-role";
import { readHealth } from "./connected-apps-client";
import { readNotify } from "./notifications-client";
import { useOrgName } from "./scope-chip";
import styles from "./setup-checklist.module.css";

export type SetupItem = {
  key: "company" | "team" | "sources" | "hours" | "phones";
  done: boolean;
  /** What to do, said as the action. */
  todo: string;
  /** Its name once done. */
  name: string;
  href: string;
};

/** The checklist from whatever answered; one rejected read leaves its line out. */
export async function readSetup(
  tenantId: string,
  signal?: AbortSignal,
): Promise<SetupItem[]> {
  const [company, seats, health, notify, phones] = await Promise.allSettled([
    readOrganisationSettings(tenantId, signal),
    readSeats(signal),
    readHealth(signal),
    readNotify(signal),
    readCaptureTeam(signal),
  ]);
  const items: SetupItem[] = [];
  if (company.status === "fulfilled") {
    const value = company.value;
    items.push({
      key: "company",
      done: Boolean(value.logo_url || value.legal_name || value.gstin),
      todo: "Add your company's logo and details",
      name: "Company",
      href: "/settings/organisation",
    });
  }
  if (seats.status === "fulfilled") {
    items.push({
      key: "team",
      done: seats.value.activeMembers + seats.value.pendingInvites > 1,
      todo: "Invite your team",
      name: "Team",
      href: "/settings/team",
    });
  }
  if (health.status === "fulfilled") {
    items.push({
      key: "sources",
      done: health.value.apps.some(
        (app) => app.state === "ready" || app.connections.length > 0,
      ),
      todo: "Connect where your leads come from",
      name: "Lead sources",
      href: "/settings/apps",
    });
  }
  if (notify.status === "fulfilled") {
    items.push({
      key: "hours",
      done: notify.value.working_hours !== null,
      todo: "Set your team's working hours",
      name: "Working hours",
      href: "/settings/lead-rules",
    });
  }
  if (phones.status === "fulfilled") {
    const waiting = phones.value.people.filter(
      (person) => person.state !== "set_up",
    );
    items.push({
      key: "phones",
      done: waiting.length === 0,
      todo:
        waiting.length === 1
          ? `Turn on phone setup for ${waiting[0].name}`
          : `Turn on phone setup for ${waiting.length} sellers`,
      name: "Sellers' phones",
      href: "/settings/phones",
    });
  }
  return items;
}

export function SetupChecklist() {
  const canHere = useCanHere();
  const org = useOrgName();
  const tenantId = useWorkspaceAccess()?.context?.tenantId ?? null;
  const manages =
    org !== null && tenantId !== null && canHere("leads.manage") === true;
  const [items, setItems] = useState<SetupItem[] | null>(null);
  useEffect(() => {
    if (!manages || !tenantId) return;
    const controller = new AbortController();
    readSetup(tenantId, controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setItems(value);
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [manages, tenantId]);
  if (!manages || !items || items.length === 0) return null;
  const done = items.filter((item) => item.done);
  const left = items.filter((item) => !item.done);
  return (
    <section className={styles.card} aria-label="Setup">
      <div className={styles.head}>
        {left.length === 0 ? (
          <CheckCircle2 size={20} aria-hidden="true" className={styles.ok} />
        ) : null}
        <h2>
          {left.length === 0 ? (
            <>{org} is all set up</>
          ) : (
            <>
              Your organisation is{" "}
              <b>
                {done.length} of {items.length} set up
              </b>
            </>
          )}
        </h2>
      </div>
      <div
        className={styles.bar}
        role="progressbar"
        aria-label="Set up"
        aria-valuemin={0}
        aria-valuemax={items.length}
        aria-valuenow={done.length}
      >
        <span style={{ width: `${(done.length / items.length) * 100}%` }} />
      </div>
      {left.length > 0 ? (
        <ul className={styles.todos}>
          {left.map((item) => (
            <li key={item.key}>
              <Link
                href={item.href}
                className={styles.todo}
                data-sx-feature={`setup_${item.key}`}
              >
                <Circle size={18} aria-hidden="true" />
                <span>{item.todo}</span>
                <ChevronRight size={16} aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {done.length > 0 && left.length > 0 ? (
        <p className={styles.done}>
          Done: {done.map((item) => item.name).join(", ")}
        </p>
      ) : null}
    </section>
  );
}
