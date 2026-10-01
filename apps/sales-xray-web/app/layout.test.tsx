import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

import Layout from "./layout";
import { themeInitScript } from "./lightbox/theme";

afterEach(() => vi.unstubAllEnvs());

it("marks the standalone document, starts light and runs the theme script first", () => {
  vi.stubEnv("NODE_ENV", "development");
  const markup = renderToStaticMarkup(
    <Layout>
      <p>Workspace</p>
    </Layout>,
  );
  expect(markup).toMatch(
    /^<html lang="en" data-lx-root="" data-theme="light">/,
  );
  expect(markup).toContain(
    `<body class="sales-xray-document"><script id="sales-xray-theme-init">${themeInitScript()}</script>`,
  );
  expect(markup).toContain("<p>Workspace</p>");
});

it("keeps production light, with no theme script, until the theme is released", () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("AC_SALES_XRAY_THEME_PREVIEW", "");
  const production = renderToStaticMarkup(
    <Layout>
      <p>Workspace</p>
    </Layout>,
  );
  expect(production).toContain('data-theme="light"');
  expect(production).not.toContain("sales-xray-theme-init");

  vi.stubEnv("AC_SALES_XRAY_THEME_PREVIEW", "1");
  expect(
    renderToStaticMarkup(
      <Layout>
        <p>Workspace</p>
      </Layout>,
    ),
  ).toContain('<script id="sales-xray-theme-init">');
});

it("draws under phone notches and keeps zoom allowed (native-wrapper ready)", async () => {
  const { viewport } = await import("./layout");
  expect(viewport).toMatchObject({
    width: "device-width",
    initialScale: 1,
    viewportFit: "cover",
    interactiveWidget: "resizes-content",
  });
  // Pinch zoom stays available: no maximumScale or userScalable lock.
  expect(viewport).not.toHaveProperty("maximumScale");
  expect(viewport).not.toHaveProperty("userScalable");
  expect(viewport.themeColor).toEqual([
    { media: "(prefers-color-scheme: light)", color: "#f4f6fb" },
    { media: "(prefers-color-scheme: dark)", color: "#060a14" },
  ]);
});
