import { readFileSync } from "node:fs";
import { createElement, Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import CatalogPage from "./catalog/page";
import AdminHome from "./page";
import ErrorBoundary from "./error";
import LearningOperationsPage from "./learning-operations/page";
import Loading from "./loading";
import NotFound from "./not-found";
import PeoplePage from "./people/page";
import CorrectionPage from "./people/corrections/page";
import GrantsPage from "./people/grants/page";
import {
  CorrectionForm,
  DIAGNOSIS_PURPOSES,
  guardPreviewEnter,
  guardPreviewSubmit,
  HeldJobRetryForm,
  isDiagnosisPurpose,
  isDiagnosisReviewReady,
  LearnerLookupForm,
  ManualGrantForm,
  ReconciliationForm,
} from "./components/admin-forms";
import { AuditPanel, CapabilityBoundary } from "./components/ops-primitives";

const previewForms = [
  createElement(LearnerLookupForm),
  createElement(CorrectionForm),
  createElement(ManualGrantForm),
  createElement(HeldJobRetryForm),
  createElement(ReconciliationForm),
];

function relativeLuminance(hex: string) {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    ?.map((channel) => Number.parseInt(channel, 16) / 255);

  if (!channels) throw new Error("Invalid color");

  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045
      ? channel / 12.92
      : Math.pow((channel + 0.055) / 1.055, 2.4),
  );

  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground: string, background: string) {
  const lighter = Math.max(
    relativeLuminance(foreground),
    relativeLuminance(background),
  );
  const darker = Math.min(
    relativeLuminance(foreground),
    relativeLuminance(background),
  );
  return (lighter + 0.05) / (darker + 0.05);
}

describe("G1 admin inert form seams", () => {
  it("prevents submit and Enter events while leaving unrelated keys alone", () => {
    const submitEvent = {
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    };
    const enterEvent = {
      key: "Enter",
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    };
    const tabEvent = {
      key: "Tab",
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    };

    guardPreviewSubmit(submitEvent);
    guardPreviewEnter(enterEvent);
    guardPreviewEnter(tabEvent);

    expect(submitEvent.preventDefault).toHaveBeenCalledOnce();
    expect(submitEvent.stopPropagation).toHaveBeenCalledOnce();
    expect(enterEvent.preventDefault).toHaveBeenCalledOnce();
    expect(enterEvent.stopPropagation).toHaveBeenCalledOnce();
    expect(tabEvent.preventDefault).not.toHaveBeenCalled();
    expect(tabEvent.stopPropagation).not.toHaveBeenCalled();
  });

  it("renders every command form fail-closed until a server target is resolved", () => {
    for (const form of previewForms) {
      const markup = renderToStaticMarkup(form);
      const formTag = markup.match(/<form\b[^>]*>/)?.[0] ?? "";
      const buttons = [...markup.matchAll(/<button\b[^>]*>/g)].map(
        (match) => match[0],
      );

      expect(formTag).toContain('data-preview-inert="true"');
      expect(formTag).not.toMatch(/\saction=/);
      expect(markup).toMatch(/<fieldset[^>]*disabled/);
      expect(markup).not.toMatch(/\sname=/);
      expect(markup).toContain('type="submit"');
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons.every((button) => button.includes("disabled"))).toBe(true);
      expect(markup).toContain("LOOKUP UNAVAILABLE");
      expect(markup).toContain("raw identifiers are never accepted");
    }
  });

  it("requires resolved summaries before review and exposes helper relationships", () => {
    const markup = renderToStaticMarkup(createElement(CorrectionForm));
    const controls = [
      ...markup.matchAll(/<(?:input|select|textarea)\b[^>]*>/g),
    ].map((match) => match[0]);

    expect(markup).toContain("Authorized lookup");
    expect(markup).toContain("Resolved summary");
    expect(markup).toContain("Operator review");
    expect(markup).toContain("No target resolved");
    expect(markup).not.toContain("Existing event identifier");
    expect(controls.length).toBeGreaterThan(0);
    expect(
      controls.every((control) => control.includes("aria-describedby")),
    ).toBe(true);
  });

  it("requires a bounded explicit diagnosis purpose and review confirmation", () => {
    const markup = renderToStaticMarkup(createElement(LearnerLookupForm));
    const formTag = markup.match(/<form\b[^>]*>/)?.[0] ?? "";

    expect(DIAGNOSIS_PURPOSES.map(({ value }) => value)).toEqual([
      "learner_support",
      "safeguarding_review",
      "accessibility_review",
    ]);
    expect(
      DIAGNOSIS_PURPOSES.every(({ value }) => isDiagnosisPurpose(value)),
    ).toBe(true);
    expect(isDiagnosisPurpose("custom-purpose")).toBe(false);
    expect(isDiagnosisPurpose("")).toBe(false);

    expect(markup).toContain("Diagnosis purpose");
    expect(markup).toContain("Select an explicit purpose");
    expect(markup).toContain("There is no default purpose");
    expect(markup).toMatch(/<select[^>]*required/);
    expect(markup).not.toContain('selected="learner_support"');
    expect(markup).toContain(
      "I confirm this authorized review has the required boundary.",
    );
    expect(markup).toContain(
      "permission, active tenant, the selected purpose, redaction",
    );
    expect(markup).toMatch(/<input[^>]*type="checkbox"[^>]*disabled/);
    expect(markup).toMatch(/<fieldset[^>]*disabled/);
    expect(markup).toMatch(/<button[^>]*disabled[^>]*>.*Run diagnosis/);
    expect(formTag).not.toMatch(/\s(?:action|method|name)=/);
    expect(markup).not.toMatch(
      /id="[^"]*(?:learner_support|safeguarding_review|accessibility_review)/,
    );
    expect(markup).not.toContain("?");
  });

  it("does not infer purpose or unlock diagnosis before every boundary is ready", () => {
    expect(
      isDiagnosisReviewReady({
        purpose: "",
        reviewConfirmed: true,
        targetResolved: true,
        serverContextVerified: true,
      }),
    ).toBe(false);
    expect(
      isDiagnosisReviewReady({
        purpose: "learner_support",
        reviewConfirmed: false,
        targetResolved: true,
        serverContextVerified: true,
      }),
    ).toBe(false);
    expect(
      isDiagnosisReviewReady({
        purpose: "learner_support",
        reviewConfirmed: true,
        targetResolved: false,
        serverContextVerified: true,
      }),
    ).toBe(false);
    expect(
      isDiagnosisReviewReady({
        purpose: "learner_support",
        reviewConfirmed: true,
        targetResolved: true,
        serverContextVerified: false,
      }),
    ).toBe(false);
    expect(
      isDiagnosisReviewReady({
        purpose: "learner_support",
        reviewConfirmed: true,
        targetResolved: true,
        serverContextVerified: true,
      }),
    ).toBe(true);
  });
});

describe("G1 admin permissions and semantic boundaries", () => {
  it("renders the Clarity Grid organization shell without asserting metrics", () => {
    const markup = renderToStaticMarkup(createElement(AdminHome));

    expect(markup).toContain("clarity-shell surface-organization");
    expect(markup).toContain("Organization overview");
    expect(markup).toContain("Tenant pending");
    expect(markup).toContain("Waiting for session verification");
    expect(markup).toContain("Active learners");
    expect(markup).toContain("Not connected");
    expect(markup).toContain(
      "No learner, catalog, job, or audit record is seeded here",
    );
    expect(markup).not.toContain(">248<");
    expect(markup).not.toContain(">68%<");
  });

  it("renders people as an empty, fail-closed directory with locked actions", () => {
    const markup = renderToStaticMarkup(createElement(PeoplePage));

    expect(markup).toContain("clarity-shell surface-people");
    expect(markup).toContain("No learner records available");
    expect(markup).toContain(
      "No names, assignments, or progress values are fabricated",
    );
    expect(markup).toContain("Create assignment (unavailable)");
    expect(markup).toMatch(/<button[^>]*disabled[^>]*>Create assignment/);
  });

  it("renders the studio outline as a truthful contract preview", () => {
    const markup = renderToStaticMarkup(createElement(CatalogPage));

    expect(markup).toContain("clarity-shell surface-studio");
    expect(markup).toContain('aria-label="Course studio preview"');
    expect(markup).toContain("Approved lesson asset pending");
    expect(markup).toContain("Media configuration is not connected");
    expect(markup).toContain("Learner visibility is determined by publication");
  });

  it("locks effectful controls and names permission, reason, and audit behavior", () => {
    const markup = renderToStaticMarkup(
      createElement(CapabilityBoundary, {
        title: "Promote immutable version",
        detail: "Version promotion is a server-authorized transition.",
        permission: "catalog_publish",
        reason: "No named admin actor is available in preview.",
        audit: "No transition is written.",
        actionLabel: "Publish version (locked)",
      }),
    );

    expect(markup).toContain("catalog_publish");
    expect(markup).toContain("No named admin actor is available in preview.");
    expect(markup).toContain("No transition is written.");
    expect(markup).toMatch(/<button[^>]*disabled/);
  });

  it("keeps all scoped route action buttons disabled", () => {
    const routes = [
      { Page: CatalogPage, permission: "catalog_publish" },
      { Page: CorrectionPage, permission: "learning_correct" },
      { Page: GrantsPage, permission: "enrollment_grant" },
      { Page: LearningOperationsPage, permission: "recovery_reconcile" },
    ];

    for (const { Page, permission } of routes) {
      const markup = renderToStaticMarkup(createElement(Page));
      const buttons = [...markup.matchAll(/<button\b[^>]*>/g)].map(
        (match) => match[0],
      );

      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons.every((button) => button.includes("disabled"))).toBe(true);
      expect(markup).toContain(permission);
      expect(markup).toContain("NOT WRITTEN");
    }
  });

  it("renders actual loading, error, and not-found route boundaries", () => {
    const loading = renderToStaticMarkup(createElement(Loading));
    const error = renderToStaticMarkup(
      createElement(ErrorBoundary, {
        error: Object.assign(new Error("hidden"), { digest: "trace-123" }),
        reset: vi.fn(),
      }),
    );
    const notFound = renderToStaticMarkup(createElement(NotFound));

    expect(loading).toContain('role="status"');
    expect(loading).toContain('id="route-loading-boundary"');
    expect(loading).not.toContain('id="admin-content"');
    expect(loading).toContain("No operational record is shown");
    expect(error).toContain("No action was performed");
    expect(error).not.toContain("hidden");
    expect(error).toContain("Trace trace-123");
    expect(notFound).toContain("outside the G1 surface");
    expect(notFound).toContain('href="/"');
  });

  it("uses one content landmark, a skip link, and exact support aria-current", () => {
    const people = renderToStaticMarkup(createElement(PeoplePage));
    const correction = renderToStaticMarkup(createElement(CorrectionPage));
    const layout = readFileSync(
      new URL("./layout.tsx", import.meta.url),
      "utf8",
    );

    expect(people).toMatch(/<div class="admin-shell(?: [^"]+)?">/);
    expect(people).toMatch(
      /<main[^>]*class="admin-content"[^>]*id="admin-content"/,
    );
    expect(layout).toContain('className="skip-link"');
    expect(layout).toContain('href="#admin-content"');
    expect(correction.match(/aria-current="page"/g)).toHaveLength(1);
    expect(correction).toMatch(
      /<a(?=[^>]*class="active")(?=[^>]*aria-current="page")(?=[^>]*href="\/people\/corrections")[^>]*>/,
    );
  });

  it("labels the keyboard-scrollable publish table region", () => {
    const markup = renderToStaticMarkup(createElement(CatalogPage));

    expect(markup).toContain('role="region"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain('aria-labelledby="publish-gate-caption"');
    expect(markup).toContain('aria-describedby="publish-gate-table-help"');
    expect(markup).toContain(
      '<caption id="publish-gate-caption">Publish transition gate contract</caption>',
    );
  });

  it("keeps audit heading IDs unique", () => {
    const markup = renderToStaticMarkup(
      createElement(
        Fragment,
        null,
        createElement(AuditPanel, {
          id: "first-audit",
          title: "First audit",
          body: "First boundary.",
        }),
        createElement(AuditPanel, {
          id: "second-audit",
          title: "Second audit",
          body: "Second boundary.",
        }),
      ),
    );
    const ids = [...markup.matchAll(/\sid="([^"]+)"/g)].map(
      (match) => match[1],
    );

    expect(ids).toContain("first-audit-title");
    expect(ids).toContain("second-audit-title");
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("does not advertise simulated universal, offline, or held states", () => {
    const markup = renderToStaticMarkup(
      createElement(
        Fragment,
        null,
        createElement(PeoplePage),
        createElement(LearningOperationsPage),
      ),
    );

    expect(markup).not.toContain("Universal state contract");
    expect(markup).not.toContain("ERROR_RETRYABLE");
    expect(markup).not.toContain(">OFFLINE<");
    expect(markup).not.toContain(">HELD<");
    expect(markup).toContain("No queue state is asserted.");
    expect(markup).toContain("Unknown — no response or record is asserted");
  });

  it("keeps quiet text above 4.5:1 on actual panel backgrounds", () => {
    const styles = readFileSync(
      new URL("./styles.css", import.meta.url),
      "utf8",
    );
    const quiet = "#aab3a4";

    expect(styles).toContain("--quiet: " + quiet);
    expect(contrastRatio(quiet, "#10130f")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(quiet, "#171b16")).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps Clarity Grid navigation touch targets at least 44px high", () => {
    const styles = readFileSync(
      new URL("./styles.css", import.meta.url),
      "utf8",
    );

    expect(styles).toMatch(
      /\.clarity-shell \.sidebar-nav a \{[^}]*min-height: 44px;/s,
    );
    expect(styles).toMatch(
      /\.clarity-shell \.sidebar-subnav a \{[^}]*min-height: 44px;/s,
    );
    expect(styles).toMatch(/\.brand \{[^}]*min-height: 44px;/s);
    expect(styles).toMatch(/\.back-link \{[^}]*min-height: 44px;/s);
    expect(styles).toMatch(
      /\.field input,\s*\.field select \{[^}]*min-height: 44px;/s,
    );
  });
});
