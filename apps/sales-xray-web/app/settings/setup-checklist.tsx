"use client";

/**
 * What's left to set up, on top of Settings (owner's round-2 board 7, option
 * A with B's checklist, 20 Nov 2026; sx-redesign pick C, 21 Nov 2026: a ring,
 * "Your company is 4 of 5 set up", the next step and one button to it).
 * Owners, admins and managers of an organisation; read from what the app already reads (the company, seats,
 * connected apps, working hours, sellers' phones). A read that fails leaves
 * its line out rather than guessing.
 */
import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
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

/**
 * What the hub's cards say in one short line (sx-redesign pick C, 21 Nov
 * 2026: "Sellers' phones 4 of 6 ready"), from the same reads as the checklist.
 * A read that failed leaves its fact out; the card keeps its plain line.
 */
export type SetupFacts = {
  people?: number;
  invited?: number;
  phonesReady?: number;
  phonesTotal?: number;
  appsConnected?: number;
  companyDone?: boolean;
};

export type Setup = { items: SetupItem[]; facts: SetupFacts };

/** The checklist and the cards' facts from whatever answered. */
export async function readSetupFacts(
  tenantId: string,
  signal?: AbortSignal,
): Promise<Setup> {
  const [company, seats, health, notify, phones] = await Promise.allSettled([
    readOrganisationSettings(tenantId, signal),
    readSeats(signal),
    readHealth(signal),
    readNotify(signal),
    readCaptureTeam(signal),
  ]);
  const items: SetupItem[] = [];
  const facts: SetupFacts = {};
  if (company.status === "fulfilled") {
    const value = company.value;
    const done = Boolean(value.logo_url || value.legal_name || value.gstin);
    facts.companyDone = done;
    items.push({
      key: "company",
      done,
      todo: "Add your company's logo and details",
      name: "Company",
      href: "/settings/organisation",
    });
  }
  if (seats.status === "fulfilled") {
    facts.people = seats.value.activeMembers;
    facts.invited = seats.value.pendingInvites;
    items.push({
      key: "team",
      done: seats.value.activeMembers + seats.value.pendingInvites > 1,
      todo: "Invite your team",
      name: "Team",
      href: "/settings/team",
    });
  }
  if (health.status === "fulfilled") {
    const connected = health.value.apps.filter(
      (app) => app.state === "ready" || app.connections.length > 0,
    ).length;
    facts.appsConnected = connected;
    items.push({
      key: "sources",
      done: connected > 0,
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
    facts.phonesTotal = phones.value.people.length;
    facts.phonesReady = phones.value.people.length - waiting.length;
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
  return { items, facts };
}

/** The checklist alone; one rejected read leaves its line out. */
export async function readSetup(
  tenantId: string,
  signal?: AbortSignal,
): Promise<SetupItem[]> {
  return (await readSetupFacts(tenantId, signal)).items;
}

/** The one word on the hero's button for the next thing to do. */
const ACTION: Record<SetupItem["key"], string> = {
  company: "Add details",
  team: "Invite",
  sources: "Connect",
  hours: "Set hours",
  phones: "Set up phones",
};

/**
 * The setup and the cards' facts for an organisation's owners, admins and
 * managers; null for everyone else and until the reads answer.
 */
export function useSetup(): Setup | null {
  const canHere = useCanHere();
  const org = useOrgName();
  const tenantId = useWorkspaceAccess()?.context?.tenantId ?? null;
  const manages =
    org !== null && tenantId !== null && canHere("leads.manage") === true;
  const [setup, setSetup] = useState<{ tenant: string; value: Setup } | null>(
    null,
  );
  useEffect(() => {
    if (!manages || !tenantId) return;
    const controller = new AbortController();
    readSetupFacts(tenantId, controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setSetup({ tenant: tenantId, value });
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [manages, tenantId]);
  return manages && setup?.tenant === tenantId ? setup.value : null;
}

/** The ring: how many of the setup steps are done. */
function SetupRing({ done, total }: { done: number; total: number }) {
  const r = 34;
  const length = 2 * Math.PI * r;
  const part = total > 0 ? done / total : 0;
  return (
    <span
      className={styles.ring}
      role="progressbar"
      aria-label="Set up"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
    >
      <svg viewBox="0 0 80 80" width="80" height="80" aria-hidden="true">
        <circle className={styles.ringTrack} cx="40" cy="40" r={r} />
        <circle
          className={styles.ringFill}
          cx="40"
          cy="40"
          r={r}
          strokeDasharray={`${length * part} ${length}`}
        />
      </svg>
      <span className={styles.ringWords} aria-hidden="true">
        <b>
          {done} of {total}
        </b>
        <small>set up</small>
      </span>
    </span>
  );
}

/**
 * The hub's one hero (sx-redesign pick C, owner 21 Nov 2026): the ring, how
 * far the company is, the next step and one green button to it. The rest of
 * what's left is one tap away on the cards below.
 */
export function SetupHero({ setup }: { setup: Setup | null }) {
  const org = useOrgName();
  if (!setup || setup.items.length === 0) return null;
  const { items } = setup;
  const done = items.filter((item) => item.done);
  const left = items.filter((item) => !item.done);
  const next = left[0] ?? null;
  return (
    <section
      className={styles.card}
      aria-label="Setup"
      data-done={next ? undefined : ""}
    >
      <SetupRing done={done.length} total={items.length} />
      <div className={styles.words}>
        <h2>
          {next ? (
            <>
              Your company is {done.length} of {items.length} set up
            </>
          ) : (
            <>{org ?? "Your company"} is all set up</>
          )}
        </h2>
        {next ? (
          <p>
            <span className={styles.nextLabel}>Next step</span>
            <span className={styles.next}>{next.todo}</span>
          </p>
        ) : (
          <p>
            <CheckCircle2 size={16} aria-hidden="true" className={styles.ok} />
            <span className={styles.next}>Everything is ready.</span>
          </p>
        )}
      </div>
      {next ? (
        <Link
          href={next.href}
          className={styles.go}
          data-sx-feature={`setup_${next.key}`}
        >
          {ACTION[next.key]}
        </Link>
      ) : null}
    </section>
  );
}

/** The setup hero on its own, reading for itself. */
export function SetupChecklist() {
  return <SetupHero setup={useSetup()} />;
}
