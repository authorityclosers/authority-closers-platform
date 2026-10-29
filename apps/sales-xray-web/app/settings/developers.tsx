"use client";

/**
 * Settings -> Developers (owner, 20 Oct: "the mcp server and api usage are not
 * clear ... we might need a documentation"): the documentation first, then API
 * keys and a real request to try, your AI assistant step by step, the webhook,
 * hand-over and your own apps. Owners and admins only, as before.
 * 24 Oct 2026 (orchestrator: "redo Settings → Connections / Developers"): the
 * AI assistant comes first, ChatGPT included, and the docs are one quiet
 * line, so "New key" is the screen's one filled button.
 * 29 Oct 2026 (owner bugs #103-#105: "the developers section is very niche and
 * needs to have its own personality", "information could be under tooltip"):
 * a dark console card with the two addresses to copy and the docs, then one
 * card per part in its own colour, each with its explanation behind an (i).
 * Try the API folds under the keys until it's wanted.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  BookOpen,
  Check,
  ChevronRight,
  Copy,
  FlaskConical,
  Terminal,
} from "lucide-react";

import { notify } from "../notice-center";
import { OrganisationView } from "../organisation/organisation-view";
import { AssistantSetup } from "./assistant-setup";
import { DevFold } from "./dev-card";
import { TryApi } from "./try-api";
import { useOrigin } from "./use-origin";
import styles from "./developers.module.css";

const PRODUCTION = "https://salesxray.authorityclosers.com";

/** Copies an address on the console card, and says so for two seconds. */
function CopyAddress({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  const failed = () =>
    notify({
      id: "copy",
      tone: "error",
      title: "Couldn’t copy",
      message: "Select the text and copy it yourself.",
    });
  return (
    <button
      type="button"
      className={styles.consoleCopy}
      data-copied={copied ? "" : undefined}
      aria-label={copied ? `${label}: copied` : label}
      onClick={() => {
        const done = navigator.clipboard?.writeText(text);
        if (!done) return failed();
        void done.then(() => setCopied(true), failed);
      }}
    >
      {copied ? (
        <Check size={16} aria-hidden="true" />
      ) : (
        <Copy size={16} aria-hidden="true" />
      )}
    </button>
  );
}

/** The two addresses a developer needs, on a card that looks like a console. */
function Console() {
  const origin = useOrigin() || PRODUCTION;
  const host = origin.replace(/^https?:\/\//, "");
  const addresses = [
    { tag: "MCP", path: "/v1/mcp", label: "Copy the MCP address" },
    { tag: "API", path: "/v1/api", label: "Copy the API address" },
  ];
  return (
    <section className={styles.console} aria-label="Developers">
      <div className={styles.consoleHead}>
        <span className={styles.consoleMark} aria-hidden="true">
          <Terminal size={20} strokeWidth={2.2} />
        </span>
        <span className={styles.consoleText}>
          <strong>Build on Sales X-Ray</strong>
          <span>Your AI assistant, your apps and webhooks</span>
        </span>
      </div>
      <ul className={styles.addresses} aria-label="Addresses">
        {addresses.map((item) => (
          <li key={item.tag}>
            <span className={styles.tag}>{item.tag}</span>
            <code className={styles.address}>
              <span className={styles.host}>{host}</span>
              <span className={styles.path}>{item.path}</span>
            </code>
            <CopyAddress text={`${origin}${item.path}`} label={item.label} />
          </li>
        ))}
      </ul>
      <Link href="/developers" className={styles.consoleDocs}>
        <BookOpen size={16} aria-hidden="true" />
        <span>Read the docs</span>
        <ChevronRight size={16} aria-hidden="true" />
      </Link>
    </section>
  );
}

export function DevelopersSection() {
  // A key made a moment ago, for Try it; kept in this tab's memory only.
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  return (
    <div className={styles.page}>
      <Console />
      <AssistantSetup />
      <OrganisationView
        embedded
        sections={["integrations"]}
        integrationParts={["keys", "webhook", "handover", "apps"]}
        integrationOptions={{
          onKeyMade: setFreshKey,
          refresh,
          extras: {
            keys: (
              // Folded until wanted; a key made a moment ago opens it.
              <DevFold
                key={freshKey ? "fresh" : "folded"}
                icon={<FlaskConical />}
                tone="blue"
                title="Try the API"
                note="A real request with your key"
                open={freshKey !== null}
              >
                <TryApi
                  freshKey={freshKey}
                  onUsed={() => setRefresh((value) => value + 1)}
                />
              </DevFold>
            ),
          },
        }}
      />
    </div>
  );
}
