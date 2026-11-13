"use client";

/**
 * The team's next step for one tester (owner, 13 Nov 2026): approve or
 * decline an application; for an approved tester, add their Google account to
 * the Play group (the button copies the address and opens the group's members
 * page) and then "Added, send email"; send the welcome email again later. Each
 * click adds a row to the tester's history; nothing is overwritten.
 */
import { ExternalLink } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { send } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import { nextStep, type Tester } from "./testers-data";
import styles from "./testers.module.css";

type Command = { path: string; body: unknown };

export function TesterActions({
  tester,
  groupUrl,
}: {
  tester: Tester;
  groupUrl: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  const step = nextStep(tester);
  const hoursDue =
    tester.hours === "due" &&
    tester.stage !== "applied" &&
    tester.stage !== "declined";
  if (!step && !hoursDue && !said) return null;
  const base = `/v1/admin/testers/${tester.id}`;

  const run = async (command: Command) => {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const result = await send<{ hours_words?: unknown }>(
      "POST",
      command.path,
      command.body,
      null,
    );
    setBusy(false);
    if (!result.ok) {
      setProblem(result.message);
      return;
    }
    // What happened to their 3 hours of call analysis, in the server's words.
    const words = result.data?.hours_words;
    setSaid(typeof words === "string" ? words : null);
    router.refresh();
  };

  const openGroup = async () => {
    try {
      await navigator.clipboard.writeText(tester.email);
      setCopied(true);
    } catch {
      setCopied(false);
    }
    window.open(groupUrl, "_blank", "noopener,noreferrer");
  };

  const button = (label: string, command: Command, variant?: "primary") => (
    <button
      key={label}
      type="button"
      className={kitStyles.button}
      data-variant={variant}
      disabled={busy}
      onClick={() => void run(command)}
    >
      {label}
    </button>
  );

  let actions: ReactNode[] = [];
  if (step === "review")
    actions = [
      button(
        "Approve",
        { path: `${base}/decision`, body: { decision: "approve" } },
        "primary",
      ),
      button("Decline", {
        path: `${base}/decision`,
        body: { decision: "decline" },
      }),
    ];
  else if (step === "add_to_group")
    actions = [
      <button
        key="group"
        type="button"
        className={kitStyles.button}
        onClick={() => void openGroup()}
        title={`Copies ${tester.email} and opens the group's members page`}
      >
        Add to group
        <ExternalLink size={14} aria-hidden="true" />
      </button>,
      button(
        "Added, send email",
        { path: `${base}/group`, body: { send_email: true } },
        "primary",
      ),
    ];
  else if (step === "send_email")
    actions = [
      button("Send email", { path: `${base}/email`, body: {} }, "primary"),
    ];
  else if (step === "send_again")
    actions = [button("Send again", { path: `${base}/email`, body: {} })];
  else if (step === "reconsider")
    actions = [
      button("Approve", {
        path: `${base}/decision`,
        body: { decision: "approve" },
      }),
    ];

  if (hoursDue)
    actions.push(button("Give 3 hours", { path: `${base}/hours`, body: {} }));

  return (
    <span className={styles.actions}>
      {actions.length ? (
        <span className={styles.actionRow}>{actions}</span>
      ) : null}
      {said ? (
        <small className={kitStyles.muted} role="status">
          {said}
        </small>
      ) : null}
      {copied && step === "add_to_group" ? (
        <small className={kitStyles.muted} role="status">
          Address copied: paste it in Add members.
        </small>
      ) : null}
      {problem ? (
        <small className={kitStyles.fieldError} role="alert">
          {problem}
        </small>
      ) : null}
    </span>
  );
}
