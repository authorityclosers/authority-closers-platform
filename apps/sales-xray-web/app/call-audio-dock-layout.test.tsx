// @vitest-environment node
import { readFileSync } from "node:fs";
import { chromium, type Browser } from "playwright";
import { createRef } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { CallAudioDock } from "./call-audio-dock";
import styles from "./call-audio-dock.module.css";

// Opt in where Chromium is installed: AC_BROWSER_LAYOUT_CHECK=1 pnpm --filter
// @ac/sales-xray-web test app/call-audio-dock-layout.test.tsx
describe.skipIf(process.env.AC_BROWSER_LAYOUT_CHECK !== "1")(
  "audio dock browser layout",
  () => {
    let browser: Browser;
    const readCss = (path: string) =>
      readFileSync(new URL(path, import.meta.url), "utf8");
    const css =
      readCss("./lightbox/tokens.css") +
      readCss("./styles.css") +
      readCss("./call-audio-dock.module.css")
        .replace(/:global\(([^)]+)\)/g, "$1")
        .replace(/\.([a-z][\w-]*)/gi, (match, name) =>
          styles[name] ? `.${styles[name]}` : match,
        );

    beforeAll(async () => {
      browser = await chromium.launch();
    });
    afterAll(async () => {
      await browser?.close();
    });

    async function open(width: number, height: number, embedded = false) {
      const page = await browser.newPage({
        viewport: { width, height },
        reducedMotion: "reduce",
      });
      const markup = renderToStaticMarkup(
        <CallAudioDock
          audioRef={createRef<HTMLAudioElement>()}
          src=""
          durationMs={1253000}
          embedded={embedded}
        />,
      );
      await page.setContent(
        `<html data-lx-root data-theme="light"><style>${css}</style><body>${markup}</body></html>`,
      );
      const dock = page.getByRole("region", { name: "Call audio player" });
      await dock.evaluate((element) => {
        element.setAttribute("data-revealed", "true");
      });
      return { page, dock };
    }

    it.each([false, true])(
      "keeps short viewports in document flow (embedded=%s)",
      async (embedded) => {
        for (const height of [480, 560, 561]) {
          const { page, dock } = await open(760, height, embedded);
          try {
            expect(
              await dock.evaluate(
                (element) => getComputedStyle(element).position,
              ),
            ).toBe(height <= 560 ? "static" : embedded ? "fixed" : "sticky");
          } finally {
            await page.close();
          }
        }
      },
    );

    it.each([240, 320, 390, 760])(
      "places Hide player in the explicit mobile grid at %spx",
      async (width) => {
        const { page, dock } = await open(width, 844);
        try {
          expect(
            await dock.evaluate(
              (element) =>
                getComputedStyle(element).gridTemplateRows.split(" ").length,
            ),
          ).toBe(width < 280 ? 4 : 2);
          const hide = page.getByRole("button", { name: "Hide player" });
          expect(
            await hide.evaluate(
              (element) => getComputedStyle(element).gridArea,
            ),
          ).toBe("hide");
          const bounds = (await hide.boundingBox())!;
          const player = (await dock.boundingBox())!;
          expect(bounds.width).toBeGreaterThanOrEqual(44);
          expect(bounds.height).toBeGreaterThanOrEqual(44);
          expect(bounds.x).toBeGreaterThanOrEqual(player.x);
          expect(bounds.x + bounds.width).toBeLessThanOrEqual(
            player.x + player.width,
          );
          expect(bounds.y + bounds.height).toBeLessThanOrEqual(
            player.y + player.height,
          );
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth),
          ).toBe(width);
        } finally {
          await page.close();
        }
      },
    );
  },
);
