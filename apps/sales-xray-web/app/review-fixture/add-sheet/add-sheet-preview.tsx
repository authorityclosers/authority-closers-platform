"use client";

/**
 * The tab bar's + with a fictional organisation, for screenshots on GitHub
 * (wb-ci --visual). The real shell draws; its reads get "sample data only"
 * and nothing leaves the browser. The page taps the + by itself.
 *
 * `?view=sheet` (default): the Add sheet, Add lead and Add a call.
 * `?view=lead`: then Add lead: the quick form.
 * `?view=personal`: the Add sheet in a personal workspace (no lead desk).
 * `?view=duplicate`: Add lead with a number that is already a lead.
 * `?view=discard`: Add lead with a name typed, then Cancel: "Discard this lead?".
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const PERSONAL = "00000000-0000-4000-8000-000000000006";
const SESSION = "00000000-0000-4000-8000-000000000005";

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path.startsWith("/v1/lead-desk/leads/match"))
      return new Response(
        JSON.stringify({
          found: true,
          lead_id: "00000000-0000-4000-8000-000000000300",
          name: "Asha Fictional",
          stage_label: "Call back",
          owner_name: "Rahul Example",
          yours: false,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
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

/** Types into a field the way a keyboard would, so React hears it. */
function typeInto(input: HTMLInputElement | undefined, value: string) {
  if (!input) return;
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function Preview() {
  useState(install);
  const view = useSearchParams().get("view") ?? "sheet";
  const personal = view === "personal";
  useEffect(() => {
    let stopped = false;
    void (async () => {
      await pause(300);
      if (stopped) return;
      document
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Add a lead or a call"]',
        )
        ?.click();
      if (view !== "lead" && view !== "duplicate" && view !== "discard") return;
      // The sheet ignores taps while it settles, as a finger's echo.
      await pause(700);
      if (stopped) return;
      Array.from(document.querySelectorAll<HTMLButtonElement>("dialog button"))
        .find((button) => button.textContent?.includes("Add lead"))
        ?.click();
      if (view === "lead") return;
      await pause(500);
      if (stopped) return;
      const inputs = Array.from(
        document.querySelectorAll<HTMLInputElement>("dialog input"),
      );
      if (view === "duplicate") {
        typeInto(inputs[0], "Asha");
        typeInto(inputs[1], "98765 43210");
        return;
      }
      typeInto(inputs[0], "Meera Sample");
      await pause(200);
      Array.from(document.querySelectorAll<HTMLButtonElement>("dialog button"))
        .find((button) => button.textContent?.trim() === "Cancel")
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
        context: {
          personId: OWNER,
          sessionId: SESSION,
          tenantId: personal ? PERSONAL : TENANT,
        },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: "owner",
            sales_xray_enabled: true,
          },
          {
            tenant_id: PERSONAL,
            kind: "personal",
            name: "Personal",
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

export function AddSheetPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
