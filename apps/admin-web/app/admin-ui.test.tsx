import { readFileSync } from "node:fs";
import { createElement, Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import ErrorBoundary from "./error";
import LearningOperationsPage from "./(console)/learning-operations/page";
import Loading from "./loading";
import NotFound from "./not-found";
import PeoplePage from "./(console)/people/page";
import CorrectionPage from "./(console)/people/corrections/page";
import GrantsPage from "./(console)/people/grants/page";
import { DevAdminLoginForm } from "./components/dev-admin-login-form";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

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

describe("G1 admin permissions and semantic boundaries", () => {
  it("labels a local sandbox and requests its real tenant without embedding account defaults", () => {
    const markup = renderToStaticMarkup(
      createElement(DevAdminLoginForm, { mode: "local-sandbox" }),
    );
    expect(markup).toContain("Local sandbox session");
    expect(markup).toContain('name="tenant_id"');
    expect(markup).toContain("No staging account or remote data is used");
    expect(markup).not.toContain("Cloudflare Access");
    expect(markup).not.toContain('value="');
    expect(markup).toContain('method="post"');
    expect(
      [...markup.matchAll(/<(?:input|button)\b[^>]*>/g)].every(([tag]) =>
        tag.includes("disabled"),
      ),
    ).toBe(true);
  });
  it("renders a password-only local bridge login without embedding credentials", () => {
    const markup = renderToStaticMarkup(createElement(DevAdminLoginForm));

    expect(markup).toContain("Sign in to the local admin workspace");
    expect(markup).toContain('name="email"');
    expect(markup).toContain('name="password"');
    expect(markup).toContain("Cloudflare Access stays server-side");
    expect(markup).not.toContain("admin@authorityclosers.com");
    expect(markup).not.toContain("CF_Authorization");
  });

  it("renders people as an empty, fail-closed directory with locked actions", () => {
    const markup = renderToStaticMarkup(createElement(PeoplePage));

    expect(markup).toContain("<h1");
    expect(markup).toContain("Checking workspace access");
    expect(markup).toContain('aria-busy="true"');
    expect(markup).not.toContain("No learner records available");
    expect(markup).not.toContain("Create assignment");
  });

  it("leaves Studio and the former catalog URL to the coach workspace", () => {
    const proxy = readFileSync(new URL("../proxy.ts", import.meta.url), "utf8");

    expect(proxy).toContain('request.nextUrl.pathname === "/catalog"');
    expect(proxy).toContain('"/studio/programs"');
  });

  it("keeps scoped mutation forms unavailable while navigation controls remain usable", () => {
    const routes = [
      { Page: CorrectionPage, permission: "learning_correct" },
      { Page: GrantsPage, permission: "enrollment_grant" },
      { Page: LearningOperationsPage, permission: "recovery_reconcile" },
    ];

    for (const { Page, permission } of routes) {
      const markup = renderToStaticMarkup(createElement(Page));
      const buttons = [...markup.matchAll(/<button\b[^>]*>/g)].map(
        (match) => match[0],
      );
      const enabled = buttons.filter((button) => !/\bdisabled\b/.test(button));
      // The console shell (layout) owns navigation; the page body has no live controls.
      expect(enabled).toEqual([]);
      expect(
        buttons.filter((button) => /type="submit"/.test(button)),
      ).toHaveLength(0);
      expect(markup).not.toContain(permission);
      expect(markup).toContain("Checking workspace access");
      expect(markup).not.toContain("<form");
    }
  });

  it("renders actual loading, error, and not-found route boundaries", () => {
    const loading = renderToStaticMarkup(createElement(Loading));
    const error = renderToStaticMarkup(
      createElement(ErrorBoundary, {
        error: Object.assign(new Error("internal secret detail"), {
          digest: "trace-123",
        }),
        reset: vi.fn(),
      }),
    );
    const notFound = renderToStaticMarkup(createElement(NotFound));

    expect(loading).toContain('role="status"');
    expect(loading).toContain('aria-busy="true"');
    expect(loading).toContain('id="route-loading-boundary"');
    expect(loading).not.toContain('id="admin-content"');
    expect(loading).toContain("No operational record is shown");
    expect(error).toContain("No action was performed");
    expect(error).not.toContain("internal secret detail");
    expect(error).toContain("Trace trace-123");
    expect(error).toContain("Try again");
    expect(notFound).toContain("no admin page here");
    expect(notFound).toContain('href="/"');
  });

  it("keeps one content landmark in the shell, a skip link, and permission-gated navigation", () => {
    const people = renderToStaticMarkup(createElement(PeoplePage));
    const correction = renderToStaticMarkup(createElement(CorrectionPage));
    const layout = readFileSync(
      new URL("./layout.tsx", import.meta.url),
      "utf8",
    );
    const shell = readFileSync(
      new URL("./ui/shell.tsx", import.meta.url),
      "utf8",
    );
    const nav = readFileSync(new URL("./lib/nav.ts", import.meta.url), "utf8");

    // Pages render inside the shell's single <main>; they never add their own.
    expect(people).not.toContain("<main");
    expect(shell.match(/<main\b/g)).toHaveLength(1);
    expect(shell).toContain('id="admin-content"');
    expect(layout).toContain('className="skip-link"');
    expect(layout).toContain('href="#admin-content"');
    expect(correction).not.toContain('href="/people/corrections"');
    expect(nav).toContain(
      'any: ["catalog_read", "catalog_write", "catalog_publish"]',
    );
    expect(nav).toContain('any: ["learner_diagnose"]');
    expect(nav).toContain('any: ["job_retry", "recovery_reconcile"]');
  });

  it("keeps Studio capacity metrics explicitly unavailable", () => {
    const runtime = readFileSync(
      new URL(
        "../../../packages/typescript/operations-web/src/studio/studio-runtime.tsx",
        import.meta.url,
      ),
      "utf8",
    );

    expect(runtime).toContain(
      '"Arrival rate", "Service rate", "Planned capacity"',
    );
    expect(runtime).toContain("metric.reason");
    expect(runtime).not.toContain("432");
    expect(runtime).not.toContain("99.7");
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
    expect(markup).toContain("Checking workspace access");
    expect(markup).not.toContain("No queue state is asserted.");
  });

  it("keeps quiet text above 4.5:1 on actual panel backgrounds", () => {
    const styles = readFileSync(
      new URL(
        "../../../packages/typescript/operations-web/src/styles.css",
        import.meta.url,
      ),
      "utf8",
    );
    const pair = (name: string) => {
      const values = styles.match(
        new RegExp(`--${name}: light-dark\\((#[a-f0-9]{6}), (#[a-f0-9]{6})\\)`),
      );
      if (!values) throw new Error("Missing shared light/dark token");
      return values.slice(1);
    };
    for (const mode of [0, 1]) {
      for (const surface of ["bg", "panel", "panel-soft"]) {
        expect(
          contrastRatio(pair("quiet")[mode], pair(surface)[mode]),
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps console navigation targets at the 32 px floor, 44 px in the phone sheet", () => {
    const styles = readFileSync(
      new URL("./ui/shell.module.css", import.meta.url),
      "utf8",
    );

    expect(styles).toMatch(/\.navLink \{[^}]*min-height: 32px;/s);
    expect(styles).toMatch(
      /\.shell \.rail \.navLink \{[^}]*min-height: 44px;/s,
    );
  });
});
