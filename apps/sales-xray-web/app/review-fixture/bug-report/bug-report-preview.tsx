"use client";

/**
 * Report a problem with a fictional organisation, for screenshots on GitHub
 * (wb-ci --visual). The real shell draws; its reads get "sample data only"
 * and a report "sends" to a stand-in, so nothing leaves the browser.
 *
 * `?view=sheet` (default): the reporter, with the picture it took of this screen.
 * `?view=you`: the You menu with its Report a problem row.
 * `?view=typed`: the same with words typed and "This stops my work" on.
 * `?view=card`: an error corner card with its Report button.
 * `?view=private`: opened on a call's Report: no picture is taken.
 * `?view=sent`: after Send report: "We'll tell you when it's fixed".
 * `?view=mine`: Your reports, one being fixed and one fixed.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { openBugReport } from "../../bug-report/open";
import { notify } from "../../notice-center";
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
    if (path.startsWith("/v1/bug-reports/mine"))
      return new Response(
        JSON.stringify({
          items: [
            {
              bug_id: "00000000-0000-4000-8000-000000000701",
              created_at: new Date(Date.now() - 3600_000).toISOString(),
              words: "Tapped Call on Asha Fictional and nothing happened.",
              status: "in_progress",
              status_at: new Date(Date.now() - 1800_000).toISOString(),
            },
            {
              bug_id: "00000000-0000-4000-8000-000000000702",
              created_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
              words: "The Leads list was empty after signing in.",
              status: "fixed",
              status_at: new Date(Date.now() - 86_400_000).toISOString(),
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    if (path.startsWith("/v1/bug-reports"))
      return new Response(
        JSON.stringify({
          bug_id: "fixture",
          screenshot: "kept",
          voice: "none",
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      );
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
  const view = useSearchParams().get("view") ?? "sheet";
  useEffect(() => {
    let stopped = false;
    if (view === "private") {
      window.history.replaceState(
        window.history.state,
        "",
        "/analysis/calls/00000000-0000-4000-8000-000000000400",
      );
    }
    void (async () => {
      await pause(300);
      if (stopped) return;
      if (view === "card") {
        notify({
          id: "fixture-error",
          tone: "error",
          title: "Couldn't save the note",
          message: "Your note is still here. Try again.",
          reference: "req-7f3a91c2",
        });
        return;
      }
      if (view === "you") {
        // The You menu, scrolled to its Report a problem row.
        document
          .querySelector<HTMLButtonElement>(
            'button[aria-label="Account and log out"]',
          )
          ?.click();
        await pause(500);
        Array.from(document.querySelectorAll<HTMLButtonElement>("button"))
          .find((button) => button.textContent?.trim() === "Report a problem")
          ?.scrollIntoView({ block: "center" });
        return;
      }
      // Screenshots come soon after load, so the reporter opens at once here;
      // the two taps (You, then Report a problem) have their own unit test.
      // The frame mounts the reporter a moment after the page; ask until it opens.
      for (let tries = 0; tries < 40 && !stopped; tries += 1) {
        if (document.querySelector("dialog[open] textarea")) break;
        openBugReport();
        await pause(100);
      }
      const press = (label: string) =>
        Array.from(
          document.querySelectorAll<HTMLButtonElement>("dialog button"),
        )
          .find((button) => button.textContent?.trim() === label)
          ?.click();
      if (view === "mine") {
        await pause(400);
        press("Your reports");
        return;
      }
      if (view !== "typed" && view !== "sent") return;
      await pause(300);
      if (stopped) return;
      const area =
        document.querySelector<HTMLTextAreaElement>("dialog textarea");
      if (area) {
        Object.getOwnPropertyDescriptor(
          HTMLTextAreaElement.prototype,
          "value",
        )!.set!.call(
          area,
          "Tapped Call on Asha Fictional and nothing happened. The button went grey.",
        );
        area.dispatchEvent(new Event("input", { bubbles: true }));
      }
      press("This stops my work");
      if (view !== "sent") return;
      await pause(400);
      document.querySelector<HTMLFormElement>("dialog form")?.requestSubmit();
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
        {/* Something on the screen, so its picture shows something. */}
        <section
          aria-label="Today"
          style={{ display: "grid", gap: 12, padding: 16 }}
        >
          <h2>Today</h2>
          {[
            ["Asha Fictional", "Call back · 4:30 pm"],
            ["Rahul Example", "New lead · Website"],
            ["Meera Sample", "Interested · Site visit"],
            ["Kabir Demo", "No answer · try again"],
          ].map(([name, line]) => (
            <p key={name} style={{ margin: 0 }}>
              <b>{name}</b>
              <br />
              <small>{line}</small>
            </p>
          ))}
        </section>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function BugReportPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
