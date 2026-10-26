"use client";

/**
 * A brand-new workspace's Home (owner, #20, 26 Oct 2026: on the first sign-in
 * after install "an ugly screen of text blocks"): one welcome line and three
 * next steps, each one tap. No paragraphs.
 */

import { AudioLines, FileUp, PhoneCall, UsersRound } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { CREATE_ORGANISATION_EVENT } from "../shell/shell-store";
import styles from "./first-run.module.css";

/** The team step: invite sellers (an organisation's manager), create an
 *  organisation (your own workspace), or none (a seller: analyse a call). */
export type FirstRunTeam = "invite" | "create" | null;

function Step({
  icon,
  title,
  hint,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
}) {
  return (
    <>
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.words}>
        <strong>{title}</strong>
        <small>{hint}</small>
      </span>
    </>
  );
}

export function FirstRun({ team }: { team: FirstRunTeam }) {
  return (
    <section className={styles.firstRun} aria-labelledby="first-run-title">
      <h2 id="first-run-title">Welcome to Sales X-Ray. Start here.</h2>
      <ol className={styles.steps}>
        <li>
          <Link className={styles.step} href="/leads?import=file">
            <Step
              icon={<FileUp size={20} />}
              title="Add your leads"
              hint="Import a sheet or a lead form"
            />
          </Link>
        </li>
        <li>
          {team === "invite" ? (
            <Link className={styles.step} href="/organisation?tab=team">
              <Step
                icon={<UsersRound size={20} />}
                title="Add your team"
                hint="Invite your sellers"
              />
            </Link>
          ) : team === "create" ? (
            <button
              type="button"
              className={styles.step}
              onClick={() =>
                window.dispatchEvent(new Event(CREATE_ORGANISATION_EVENT))
              }
            >
              <Step
                icon={<UsersRound size={20} />}
                title="Add your team"
                hint="Create your organisation"
              />
            </button>
          ) : (
            <Link className={styles.step} href="/analysis/new">
              <Step
                icon={<AudioLines size={20} />}
                title="Analyse a call"
                hint="Upload a recording"
              />
            </Link>
          )}
        </li>
        <li>
          <Link className={styles.step} href="/leads">
            <Step
              icon={<PhoneCall size={20} />}
              title="Make your first call"
              hint="Call a lead from Leads"
            />
          </Link>
        </li>
      </ol>
    </section>
  );
}
