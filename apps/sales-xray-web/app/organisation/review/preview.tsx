"use client";
import { Suspense, useEffect, useState } from "react";
import { OrganisationHub } from "../org-hub";
import { FixtureWorkspace } from "../../review-fixture/leads/leads-preview";
import { OrganisationFixture } from "../../review-fixture/_fixtures/organisation-fixture";
import { DevelopersAnswers } from "../../review-fixture/developers/developers-preview";
import type { MetaPage } from "../../leads/sources-view";
import { pulseFixture } from "./pulse-fixture";
import type { Routing } from "../../leads/routing-client";
import { brandingKey, updateBranding } from "../../shell/branding-store";
const context = {
  personId: "00000000-0000-4000-8000-000000000001",
  sessionId: "00000000-0000-4000-8000-000000000005",
  tenantId: "00000000-0000-4000-8000-000000000004",
};
const pages: MetaPage[] = [
  {
    pageId: "sample-one",
    name: "Sample Homes",
    account: { name: "Mira Fictional" },
    active: true,
    received: 18,
    forms: "all",
    formsOnPage: [
      { id: "visit", name: "Book a visit", status: "ACTIVE", leads: 12 },
    ],
    backfill: { state: "done", seen: 18, created: 2, known: 16 },
  },
  {
    pageId: "sample-two",
    name: "Sample Learning",
    account: { name: "Tali Example" },
    active: true,
    received: 4,
    forms: ["course"],
    formsOnPage: [
      { id: "course", name: "Course enquiry", status: "ACTIVE", leads: 4 },
    ],
  },
];
function install() {
  if (typeof window === "undefined") return;
  const real = window.fetch.bind(window);
  const query = new URLSearchParams(window.location.search);
  const pulse = pulseFixture(
    query.get("pulse") === "connected",
    window.location.origin,
  );
  window.fetch = async (input, init) => {
    const url = new URL(
      String(input instanceof Request ? input.url : input),
      window.location.origin,
    );
    const method = init?.method ?? "GET";
    const answer = (body: unknown) => Response.json(body);
    const pulseAnswer = pulse(url.pathname, init);
    if (pulseAnswer !== undefined) return answer(pulseAnswer);
    if (
      method === "GET" &&
      url.pathname === "/v1/organisation/members" &&
      query.get("long") === "1"
    ) {
      const data = (await (await real(input, init)).json()) as {
        members: { name: string | null }[];
      };
      if (data.members[0])
        data.members[0].name = "Alexandria Fictional Longfamilyname";
      if (data.members[1])
        data.members[1].name = "Maximilian Example Longsurname";
      return answer(data);
    }
    if (method === "GET" && url.pathname === "/v1/lead-desk/routing-rules") {
      const data = (await (await real(input, init)).json()) as Routing;
      return answer({
        ...data,
        rules: data.rules.map((rule, index) => ({
          ...rule,
          name: index === 0 ? "Pune enquiries" : rule.name,
          when: rule.when.filter((condition) => condition.field !== "value"),
        })),
      });
    }
    if (url.pathname === "/v1/lead-desk/meta/status") {
      if (query.get("state") === "loading")
        return await new Promise<Response>((resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        });
      return answer({
        configured: true,
        pages: query.get("state") === "empty" ? [] : pages,
      });
    }
    if (
      url.pathname.endsWith("/forms") &&
      url.pathname.includes("/meta/pages/")
    ) {
      if (
        query.get("state") === "partial" &&
        url.pathname.includes("sample-two")
      )
        return new Response(
          '{"detail":"Sign in again to restore Page access."}',
          { status: 403 },
        );
      return answer(
        url.pathname.includes("sample-one")
          ? [
              {
                id: "visit",
                name: "Book a visit",
                status: "ACTIVE",
                leads: 12,
              },
              {
                id: "old",
                name: "Previous campaign",
                status: "ARCHIVED",
                leads: 28,
              },
            ]
          : [
              {
                id: "course",
                name: "Course enquiry",
                status: "ACTIVE",
                leads: 4,
              },
              { id: "camp", name: "Open day", status: "ARCHIVED", leads: 7 },
            ],
      );
    }
    if (method === "POST" && url.pathname.includes("/meta/pages/")) {
      const page = pages.find((item) => url.pathname.includes(item.pageId));
      if (!page) return new Response("{}", { status: 404 });
      const body = JSON.parse(String(init?.body ?? "{}"));
      if (url.pathname.endsWith("/disconnect")) page.active = false;
      else if (url.pathname.endsWith("/backfill"))
        page.backfill = { state: "done", seen: 28, created: 3, known: 25 };
      else {
        page.active = true;
        page.forms = body.forms ?? "all";
      }
      return answer({ page, imported: 3, linked: 25 });
    }
    return real(input, init);
  };
}
function Answers() {
  useState(install);
  useEffect(() => {
    // Fictional artwork only; private production logos still use the normal authenticated route.
    const timer = setTimeout(
      () =>
        updateBranding(brandingKey(context)!, {
          tenantId: context.tenantId,
          name: "Fictional Homes",
          logoUrl: `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80"><rect width="80" height="80" rx="16" fill="teal"/><path d="M18 40L40 20L62 40V62H46V46H34V62H18Z" fill="white"/></svg>')}`,
        }),
      100,
    );
    return () => clearTimeout(timer);
  }, []);
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const setup = query.get("setup");
    let phase = 0,
      attempts = 0;
    if (!setup) return;
    const timer = setInterval(() => {
      if (++attempts > 35) {
        clearInterval(timer);
        return;
      }
      const buttons = [
        ...document.querySelectorAll<HTMLButtonElement>("button"),
      ];
      if (setup === "other") {
        const summary = [...document.querySelectorAll("summary")].find((item) =>
          item.textContent?.includes("Other lead sources"),
        );
        if (summary) {
          summary.click();
          clearInterval(timer);
        }
        return;
      }
      if (setup === "rename") {
        const stage = buttons.find((button) => button.title === "Call back");
        if (stage) {
          stage.click();
          clearInterval(timer);
        }
        return;
      }
      if (setup === "microphone") {
        const summary = [...document.querySelectorAll("summary")].find((item) =>
          item.textContent?.includes("Microphone access"),
        );
        if (summary) {
          summary.click();
          clearInterval(timer);
        }
        return;
      }
      if (phase === 0) {
        const tab = buttons.find(
          (button) =>
            button.textContent?.trim() ===
            (setup === "limits" ? "Limits" : "Seller rules"),
        );
        if (tab) {
          tab.click();
          phase = 1;
          if (setup === "limits") clearInterval(timer);
        }
        return;
      }
      if (phase === 1) {
        const seller = buttons.find((button) =>
          button.textContent?.includes("Taking leads"),
        );
        if (seller) {
          seller.click();
          phase = 2;
          if (setup === "seller") clearInterval(timer);
        }
        return;
      }
      if (phase === 2) {
        const edit = buttons.find((button) =>
          button.getAttribute("aria-label")?.startsWith("Edit who "),
        );
        if (edit) {
          edit.click();
          phase = 3;
        }
        return;
      }
      if (phase === 3) {
        const area = buttons.find((button) =>
          button.textContent?.trim().startsWith("Areas"),
        );
        if (area) {
          area.click();
          clearInterval(timer);
        }
      }
    }, 100);
    return () => clearInterval(timer);
  }, []);
  return (
    <>
      <DevelopersAnswers />
      <OrganisationHub base="/organisation/review" />
    </>
  );
}
export function OrganisationReview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          <Answers />
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
