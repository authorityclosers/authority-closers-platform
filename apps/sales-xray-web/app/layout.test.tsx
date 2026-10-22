import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

import Layout from "./layout";
import { themeInitScript } from "./lightbox/theme";
import { lookInitScript } from "./ui/look";

afterEach(() => vi.unstubAllEnvs());

// The layout is async: where the server can read the API it reads the session
// first. Without an API origin (here) it reads nothing.
async function markup() {
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "");
  return renderToStaticMarkup(await Layout({ children: <p>Workspace</p> }));
}

it("marks the standalone document, starts light and runs the look switch, then the theme script, first", async () => {
  vi.stubEnv("NODE_ENV", "development");
  const html = await markup();
  expect(html).toMatch(/^<html lang="en" data-lx-root="" data-theme="light">/);
  expect(html).toContain(
    `<body class="sales-xray-document"><script id="sales-xray-look-init">${lookInitScript()}</script><script id="sales-xray-theme-init">${themeInitScript()}</script>`,
  );
  expect(html).toContain("<p>Workspace</p>");
});

it("keeps production light, with no theme script, until the theme is released", async () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("AC_SALES_XRAY_THEME_PREVIEW", "");
  const production = await markup();
  expect(production).toContain('data-theme="light"');
  expect(production).not.toContain("sales-xray-theme-init");
  // The design-direction switch (?look=, ?theme=) is the dev server's only.
  expect(production).not.toContain("sales-xray-look-init");

  vi.stubEnv("AC_SALES_XRAY_THEME_PREVIEW", "1");
  expect(await markup()).toContain('<script id="sales-xray-theme-init">');
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
    { media: "(prefers-color-scheme: dark)", color: "#0b0c0e" },
  ]);
});
