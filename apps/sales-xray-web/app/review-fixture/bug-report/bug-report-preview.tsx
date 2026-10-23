"use client";

/**
 * Report a problem with a fictional organisation, for screenshots on GitHub
 * (wb-ci --visual). The real shell draws; its reads get "sample data only"
 * and a report "sends" to a stand-in, so nothing leaves the browser.
 *
 * `?view=sheet` (default): the reporter opened from You, with the picture it
 * took of this screen.
 * `?view=typed`: the same with words typed and "This stops my work" on.
 * `?view=card`: an error corner card with its Report button.
 * `?view=private`: opened on a call's Report: no picture is taken.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
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
    if (path.startsWith("/v1/bug-reports"))
      return new Response(
        JSON.stringify({ bug_id: "fixture", screenshot: "kept" }),
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
      await pause(400);
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
      // Two taps, as a person would: You, then Report a problem.
      document
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Account and log out"]',
        )
        ?.click();
      await pause(700);
      if (stopped) return;
      const row = Array.from(
        document.querySelectorAll<HTMLButtonElement>("button"),
      ).find((button) => button.textContent?.trim() === "Report a problem");
      row?.click();
      if (!row) {
        const { openBugReport } = await import("../../bug-report/open");
        openBugReport();
      }
      if (view !== "typed") return;
      await pause(900);
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
      Array.from(document.querySelectorAll<HTMLButtonElement>("dialog button"))
        .find((button) => button.textContent?.trim() === "This stops my work")
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
