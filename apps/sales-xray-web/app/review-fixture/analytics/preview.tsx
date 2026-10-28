"use client";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { OrganisationHub } from "../../organisation/org-hub";
import { OrganisationFixture } from "../_fixtures/organisation-fixture";
import { FixtureWorkspace } from "../leads/leads-preview";
import { activitySummary } from "../../organisation/analytics-data";
import { analyticsFixture, FIXTURE_NOW } from "./fixture";

/** Route all activity reads to fictional events; exercise the real hub and reader. */
function Answers({ children }: { children: ReactNode }) {
  const query = useSearchParams();
  const state = query.get("state");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const original = window.fetch;
    const originalNow = Date.now;
    Date.now = () => Date.parse(FIXTURE_NOW);
    window.fetch = async (input, init) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        location.href,
      );
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "content-type": "application/json" },
        });
      if (url.pathname === "/v1/organisation/members")
        return json({
          members: analyticsFixture.members.map((member) => ({
            person_id: member.personId,
            invite_id: null,
            name: member.name,
            email: "fictional@example.invalid",
            role: "member",
            status: "active",
            joined_at: null,
            last_active_at: null,
            minutes_used_30d: 0,
            calls_30d: 0,
          })),
        });
      if (url.pathname === "/v1/lead-desk/activity/summary") {
        if (state === "loading") return new Promise<Response>(() => {});
        if (state === "error") return json({}, 503);
        const history = {
          ...analyticsFixture,
          items:
            state === "empty"
              ? []
              : state === "messages"
                ? [
                    {
                      ...analyticsFixture.items[0],
                      event: {
                        ...analyticsFixture.items[0].event,
                        kind: "message" as const,
                      },
                    },
                  ]
                : analyticsFixture.items,
        };
        const data = activitySummary(history);
        const iso = (day: number) =>
          new Date(day * 86400000).toISOString().slice(0, 10);
        return json({
          schema: "lead-desk/1",
          days: 30,
          now: FIXTURE_NOW,
          timezone: data.timezone,
          start: iso(data.start),
          prior: iso(data.prior),
          today: iso(data.today),
          current: { ...data.current, work: data.currentWork },
          previous: { ...data.previous, work: 0 },
          people: data.people.map((person) => ({
            ...person,
            current: { ...person.current, work: person.work },
            previous: { ...person.previous, work: 0 },
            daily: person.daily.map((day, i) => ({
              ...day,
              day: iso(data.start + i),
            })),
          })),
        });
      }

      return original(input, init);
    };
    const frame = requestAnimationFrame(() => setReady(true));
    return () => {
      cancelAnimationFrame(frame);
      window.fetch = original;
      Date.now = originalNow;
    };
  }, [state]);
  return ready ? children : null;
}
export function AnalyticsPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          <Answers>
            <OrganisationHub base="/review-fixture/analytics" />
          </Answers>
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
