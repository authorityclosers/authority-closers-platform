import { readFileSync } from "node:fs";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ActivityRow,
  ModuleCard,
  NextActionCard,
  ProgramCard,
  RouteHeader,
  StatusBanner,
} from "@ac/ui";
import { loadDiscoverData } from "../components/discover-runtime";
import DiscoverPage from "../discover/page";
import LearningPage from "../learning/page";
import { ApiError } from "./learner-api";

describe("learner course surface primitives", () => {
  it("keeps route headers semantic and card titles scoped", () => {
    const header = renderToStaticMarkup(
      createElement(RouteHeader, {
        title: "Discover Programs",
        titleId: "discover-title",
        breadcrumbs: createElement("span", null, "Dashboard / Discover"),
        description: "Published programs from the catalog.",
      }),
    );
    const card = renderToStaticMarkup(
      createElement(ProgramCard, {
        title: "Published course",
        titleId: "published-course",
        titleAs: "h3",
        description: "Published 9/1/2026 · Version 1",
        action: createElement(
          "a",
          { href: "/programs/published-course" },
          "View program",
        ),
      }),
    );

    expect(header).toContain('<h1 id="discover-title"');
    expect(header).toContain("Published programs from the catalog.");
    expect(card).toContain('<h3 id="published-course"');
    expect(card).toContain('href="/programs/published-course"');
  });

  it("makes state, next-action, module, and activity boundaries explicit", () => {
    const errorProps = {
      state: "error" as const,
      title: "Catalog unavailable",
    } as ComponentProps<typeof StatusBanner>;
    errorProps.children = createElement("p", null, "Retry the catalog read.");
    const error = renderToStaticMarkup(createElement(StatusBanner, errorProps));
    const next = renderToStaticMarkup(
      createElement(NextActionCard, {
        eyebrow: "Next action",
        title: "Reflect on the signal",
        detail: "Open the server-authorized activity.",
        action: createElement(
          "a",
          { href: "/activity/reflection-1" },
          "Open activity",
        ),
      }),
    );
    const moduleCard = renderToStaticMarkup(
      createElement(
        ModuleCard,
        {
          title: "Module 1",
          titleId: "module-1-title",
          position: "Module 1",
          status: "Available",
        },
        createElement("p", null, "Ordered activities"),
      ),
    );
    const activeRow = renderToStaticMarkup(
      createElement(ActivityRow, {
        position: "01",
        title: "Reflect on the signal",
        href: "/activity/reflection-1",
        ariaLabel: "1. Reflect on the signal, Available",
        status: "Available",
      }),
    );
    const lockedRow = renderToStaticMarkup(
      createElement(ActivityRow, {
        position: "02",
        title: "Locked review",
        href: "/activity/locked-review",
        ariaLabel: "2. Locked review, Locked",
        disabled: true,
        status: "Locked",
      }),
    );

    expect(error).toContain('role="alert"');
    expect(error).toContain("Catalog unavailable");
    expect(next).toContain("Next action");
    expect(next).toContain('href="/activity/reflection-1"');
    expect(moduleCard).toContain('aria-labelledby="module-1-title"');
    expect(activeRow).toContain('href="/activity/reflection-1"');
    expect(lockedRow).toContain('aria-disabled="true"');
    expect(lockedRow).not.toContain('href="/activity/locked-review"');
  });
});

describe("learner course route wiring", () => {
  it("keeps Discover read-only and leaves free enrollment on Home", async () => {
    const calls: string[] = [];
    const api = {
      me: async () => {
        calls.push("me");
        return {
          person_id: "person-1",
          email: "learner@example.com",
          display_name: "Learner",
          email_verified_at: "2026-09-01T00:00:00Z",
          selected_tenant_id: "tenant-1",
          membership_role: "learner",
          permissions: [],
        };
      },
      listPrograms: async () => {
        calls.push("programs");
        return {
          items: [
            {
              id: "program-1",
              slug: "authority-closers-free-course",
              title: "Authority Closers Free Course",
              program_version_id: "version-1",
              version_number: 1,
              published_at: "2026-09-01T00:00:00Z",
            },
          ],
          next_cursor: null,
        };
      },
      learning: async () => {
        calls.push("learning");
        throw new ApiError(404, "No enrollment");
      },
      enrollFree: async () => {
        calls.push("enroll");
        throw new Error("Discover must not call enrollment");
      },
    } as unknown as Parameters<typeof loadDiscoverData>[0];

    const result = await loadDiscoverData(api, undefined, false);

    expect(result.programs).toHaveLength(1);
    expect(result.learning).toBeNull();
    expect(calls).toEqual(["me", "programs", "learning"]);
    expect(calls).not.toContain("enroll");
  });

  it("keeps the bounded loading routes route-shaped", async () => {
    const discover = renderToStaticMarkup(
      await DiscoverPage({
        searchParams: Promise.resolve({ state: "LOADING" }),
      }),
    );
    const learning = renderToStaticMarkup(
      await LearningPage({
        searchParams: Promise.resolve({ state: "LOADING" }),
      }),
    );

    expect(discover).toContain("discover-skeleton");
    expect(discover).toContain("Discover Programs");
    expect(learning).toContain("learning-skeleton");
    expect(learning).toContain("My Learning");
  });

  it("keeps responsive/PWA and reduced-motion contracts in the surface layer", () => {
    const css = readFileSync(
      new URL("../course-surfaces.css", import.meta.url),
      "utf8",
    );

    expect(css).toContain("@media (max-width: 900px)");
    expect(css).toContain("@media (max-width: 560px)");
    expect(css).toContain("@media (display-mode: standalone)");
    expect(css).toContain("env(safe-area-inset-bottom)");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    expect(css).toContain("min-height: 44px");
  });
});
