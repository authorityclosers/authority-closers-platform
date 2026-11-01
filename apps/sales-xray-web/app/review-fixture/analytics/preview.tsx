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
        // Today, 7 or 30 days: the last days of the fixture's month.
        const days = Math.min(
          30,
          Math.max(1, Number(url.searchParams.get("days")) || 30),
        );
        const cut = 30 - days;
        const none = {
          calls: 0,
          conversations: 0,
          notes: 0,
          moves: 0,
          work: 0,
        };
        const add = (sum: typeof none, day: typeof none) => ({
          calls: sum.calls + day.calls,
          conversations: sum.conversations + day.conversations,
          notes: sum.notes + day.notes,
          moves: sum.moves + day.moves,
          work: sum.work + day.work,
        });
        const people = data.people.map((person) => {
          const daily = person.daily.slice(cut).map((day) => day ?? none);
          return {
            ...person,
            current: daily.reduce(add, none),
            previous: { ...person.previous, work: 0 },
            daily: daily.map((day, i) => ({
              ...day,
              day: iso(data.start + cut + i),
            })),
          };
        });
        return json({
          schema: "lead-desk/1",
          days,
          now: FIXTURE_NOW,
          timezone: data.timezone,
          start: iso(data.start + cut),
          prior: iso(data.start + cut - days),
          today: iso(data.today),
          current: people.map((person) => person.current).reduce(add, none),
          previous: { ...data.previous, work: 0 },
          people,
        });
      }
      // The list behind a number: the fixture's events, newest first.
      if (url.pathname === "/v1/lead-desk/activity")
        return json({
          items: [...analyticsFixture.items].sort(
            (a, b) => Date.parse(b.event.at) - Date.parse(a.event.at),
          ),
          next_before: null,
          counts: {},
        });

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
