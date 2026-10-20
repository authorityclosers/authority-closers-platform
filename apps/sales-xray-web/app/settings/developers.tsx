"use client";

/**
 * Settings -> Developers (owner, 20 Oct: "the mcp server and api usage are not
 * clear ... we might need a documentation"): the documentation first, then API
 * keys and a real request to try, your AI assistant step by step, the webhook,
 * hand-over and your own apps. Owners and admins only, as before.
 */
import Link from "next/link";
import { useState } from "react";
import { BookOpen } from "lucide-react";

import { OrganisationView } from "../organisation/organisation-view";
import { AssistantSetup } from "./assistant-setup";
import { TryApi } from "./try-api";
import styles from "./developers.module.css";

export function DevelopersSection() {
  // A key made a moment ago, for Try it; kept in this tab's memory only.
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  return (
    <div className={styles.page}>
      <section className={styles.docs} aria-label="Documentation">
        <span className={styles.docsIcon} aria-hidden="true">
          <BookOpen size={20} />
        </span>
        <span className={styles.docsText}>
          <strong>Developer documentation</strong>
          <span>
            Quick start, every endpoint with curl and JavaScript examples,
            webhooks and their signatures, MCP, limits and errors.
          </span>
        </span>
        <Link href="/developers" className={styles.docsLink}>
          Read the docs
        </Link>
      </section>
      <OrganisationView
        embedded
        sections={["integrations"]}
        integrationParts={["keys", "webhook", "handover", "apps"]}
        integrationOptions={{
          onKeyMade: setFreshKey,
          refresh,
          extras: {
            keys: (
              <>
                <TryApi
                  freshKey={freshKey}
                  onUsed={() => setRefresh((value) => value + 1)}
                />
                <AssistantSetup />
              </>
            ),
          },
        }}
      />
    </div>
  );
}
