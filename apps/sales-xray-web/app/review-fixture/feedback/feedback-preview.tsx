"use client";

/**
 * The feedback prompts with a fictional organisation, for screenshots on
 * GitHub (wb-ci --visual). The real shell draws; answers "send" to a stand-in,
 * so nothing leaves the browser.
 *
 * `?view=card` (default): "How useful was this Report?" with three faces.
 * `?view=words`: after "Not good": what would make it better.
 * `?view=thanks`: after "Great".
 * `?view=update`: the rating under the newest update in What's new.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { FeedbackCard } from "../../feedback/feedback-prompt";
import styles from "../../feedback/feedback.module.css";
import { UpdateRating } from "../../feedback/update-rating";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path.startsWith("/v1/feedback"))
      return new Response(JSON.stringify({ feedback_id: "fixture" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

const pause = (ms: number) =>
  new Promise((resolve) => window.setTimeout(resolve, ms));

function Preview() {
  useState(install);
  const view = useSearchParams().get("view") ?? "card";
  useEffect(() => {
    let stopped = false;
    void (async () => {
      await pause(200);
      if (stopped || (view !== "words" && view !== "thanks")) return;
      Array.from(document.querySelectorAll<HTMLButtonElement>("button"))
        .find(
          (button) =>
            button.textContent?.trim() ===
            (view === "words" ? "Not good" : "Great"),
        )
        ?.click();
    })();
    return () => {
      stopped = true;
    };
  }, [view]);
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: OWNER, sessionId: SESSION, tenantId: TENANT },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="dashboard">
        <PageHeader title="Home" titleInBar />
        {view === "update" ? (
          <section aria-label="What's new" style={{ maxWidth: 420 }}>
            <h2>Report a problem, in two taps</h2>
            <ul>
              <li>
                Report a problem from the You menu, or shake the phone in the
                app.
              </li>
              <li>Mark up or blur the picture, and add a voice note.</li>
              <li>We tell you when your report is fixed.</li>
            </ul>
            <UpdateRating update="fixture-update" />
          </section>
        ) : null}
      </AcquisitionShell>
      {view !== "update" ? (
        <div className={styles.stack}>
          <FeedbackCard
            ask={{ moment: "report_read", subject: "call:fixture" }}
            onDone={() => {}}
          />
        </div>
      ) : null}
    </WorkspaceAccessContext.Provider>
  );
}

export function FeedbackPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
