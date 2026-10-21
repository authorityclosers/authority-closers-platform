"use client";

/**
 * Cold-calling mode, a proposal mock for the owner (22 Oct 2026): one screen
 * per call, phone first. Fictional leads; nothing is called or saved.
 * `?step=card` (default): the next lead, its opener and objection prompts.
 * `?step=outcome`: after the call, one-tap outcomes that set the next step.
 */

import {
  CalendarClock,
  Clock3,
  MessageSquareQuote,
  PhoneCall,
  PhoneOff,
  ShieldAlert,
  Sparkles,
  UserRoundX,
  XCircle,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { WorkspaceAccessContext } from "../../workspace-access";
import styles from "./cold-calling.module.css";

const OBJECTIONS: [string, string][] = [
  [
    "We already have a tool",
    "Example reply: makes sense. Can I show you in 10 minutes how it fits next to it?",
  ],
  [
    "Send me details",
    "Example reply: sure, I'll WhatsApp a short note now. Which day suits a 10-minute call?",
  ],
  [
    "No budget now",
    "Example reply: understood. Can I call back next month, after your budget planning?",
  ],
];

const OUTCOMES: {
  label: string;
  next: string;
  icon: ReactNode;
  tone?: string;
}[] = [
  {
    label: "Didn't pick",
    next: "Try again in 2 h (try 2 of 6)",
    icon: <PhoneOff size={18} />,
  },
  { label: "Busy", next: "Try again this evening", icon: <Clock3 size={18} /> },
  {
    label: "Gatekeeper",
    next: "Ask for the owner's number",
    icon: <UserRoundX size={18} />,
  },
  {
    label: "Not now",
    next: "Pick a call-back date",
    icon: <CalendarClock size={18} />,
  },
  {
    label: "Interested",
    next: "Send the deck on WhatsApp",
    icon: <Sparkles size={18} />,
    tone: "good",
  },
  {
    label: "Meeting booked",
    next: "Pick the date",
    icon: <CalendarClock size={18} />,
    tone: "good",
  },
  { label: "Not a fit", next: "Pick a reason", icon: <XCircle size={18} /> },
  {
    label: "Do not call",
    next: "Never in the queue again",
    icon: <ShieldAlert size={18} />,
    tone: "bad",
  },
];

function Card() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <>
      <section className={styles.lead} aria-label="Next lead">
        <div className={styles.leadTop}>
          <span className={styles.avatar} aria-hidden="true">
            PS
          </span>
          <span className={styles.leadWords}>
            <strong>Priya Sample</strong>
            <small>Sample Digital Studio · Pune</small>
          </span>
        </div>
        <div className={styles.chips}>
          <span>Digital agency</span>
          <span>Never called</span>
          <span>Best 11 am–1 pm</span>
        </div>
      </section>
      <section className={styles.script} aria-label="Opener">
        <h2>
          <MessageSquareQuote size={16} aria-hidden="true" />
          Opener for agencies
          <span className={styles.example}>
            Example · the owner writes these
          </span>
        </h2>
        <p>
          Hi Priya, this is Asha from Fictional Homes. I&apos;m calling Sample
          Digital Studio about [the owner&apos;s one-line reason]. Do you have
          two minutes?
        </p>
      </section>
      <section className={styles.objections} aria-label="If they say">
        <h2>If they say</h2>
        {OBJECTIONS.map(([said, reply], index) => (
          <div key={said} className={styles.objection}>
            <button
              type="button"
              aria-expanded={open === index}
              onClick={() => setOpen(open === index ? null : index)}
            >
              “{said}”
            </button>
            {open === index ? <p>{reply}</p> : null}
          </div>
        ))}
      </section>
      <div className={styles.callBar}>
        <button type="button" className={styles.call}>
          <PhoneCall size={18} aria-hidden="true" />
          Call Priya
        </button>
      </div>
    </>
  );
}

function Outcome() {
  return (
    <>
      <section className={styles.lead} aria-label="Just called">
        <div className={styles.leadTop}>
          <span className={styles.avatar} aria-hidden="true">
            PS
          </span>
          <span className={styles.leadWords}>
            <strong>How did it go with Priya?</strong>
            <small>Called 2:14 · 1 min 20 s</small>
          </span>
        </div>
      </section>
      <ul className={styles.outcomes} aria-label="Outcome">
        {OUTCOMES.map((item) => (
          <li key={item.label}>
            <button type="button" data-tone={item.tone}>
              <span aria-hidden="true">{item.icon}</span>
              <strong>{item.label}</strong>
              <small>{item.next}</small>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

function Preview() {
  const step = useSearchParams().get("step") === "outcome" ? "outcome" : "card";
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: {
          personId: "00000000-0000-4000-8000-000000000002",
          sessionId: "00000000-0000-4000-8000-000000000005",
          tenantId: "00000000-0000-4000-8000-000000000004",
        },
        workspaces: [
          {
            tenant_id: "00000000-0000-4000-8000-000000000004",
            kind: "organisation",
            name: "Fictional Homes",
            role: "member",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="leads" pageName="Cold calling">
        <div className={styles.page}>
          <header className={styles.queue}>
            <strong>Partner outreach</strong>
            <span>37 to call · 4 retries due · 9 am–9 pm only</span>
          </header>
          {step === "outcome" ? <Outcome /> : <Card />}
        </div>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function ColdCallingPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
