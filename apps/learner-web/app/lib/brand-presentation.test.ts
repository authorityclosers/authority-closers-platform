import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  ACADEMY_ARTWORK,
  AcademyMark,
  BrandMark,
  COMPANY_BRAND,
  FIRST_ACADEMY_BRAND,
  PLATFORM_BRAND,
  PlatformMark,
} from "@ac/ui";
import { describe, expect, it } from "vitest";

const learnerBrandRoot = new URL("../../public/brand/", import.meta.url);
const adminBrandRoot = new URL(
  "../../../admin-web/public/brand/",
  import.meta.url,
);
const sourceHashes: Record<string, string> = {
  "ac-v0.1/horizontal.svg":
    "ca8e5107c1eeb40887fd4b583e528c3d33cf4311340930255843d9ae8f9cad81",
  "ac-v0.1/symbol.svg":
    "27ca4a9480a179517095630766ce232f8c6f5033658ba93a1723e7007b13c7fb",
  "ac-v0.1/icon.svg":
    "65fdb71975218df44800e1a4cb4a08dd8940c9af5bd53e11baeeedf06fceb215",
  "closers-academy-v0.1/horizontal.svg":
    "a9173b6c8586fee76f2420e343edae847ad793f5d7f24f570eda41bad71be5a8",
  "closers-academy-v0.1/symbol.svg":
    "c7cad953f39cfeac6cc8f2ee051e6fad2a2cf0fa3f1275a423db6d804ee4625e",
  "closers-academy-v0.1/icon.svg":
    "75a931a8a308e8524b7c32d9dff7ce9b8811faf32622576e4464dcfe4ef0d1d9",
  "cohorva-v0.1/horizontal.svg":
    "249b562eebbc3540ac94657c1e472af74111650a96558daeb94edc48e15430f1",
  "cohorva-v0.1/symbol.svg":
    "d5e2b9e1b4b9f980dc70638c6870f9afec767d3f3bcdc76d41507fa8bd41faa2",
  "cohorva-v0.1/icon.svg":
    "75d1b7beeeb554dfc8ce50bc6acaa6ac5fe620011246930fb637059b40d761f4",
};
const portraitHashes: Record<string, string> = {
  "instructor-v2/front-facing.jpeg":
    "659f4ae78271e97962d2e4c2b0120a3d191facd0bf9eca3f140bb3ef126d6c68",
  "instructor-v1/editorial.webp":
    "44d6ab558a9980db63bf42b8a0142a094ac4aedf123a876881c188b1c1a6effe",
  "instructor-v1/avatar.webp":
    "feaeb766fa03d771d5d5647553ab83752a7cee34efd0dca35a433f2a8c02607b",
};

const learningArtworkHashes: Record<string, string> = {
  "learning-art-v1/discovery.webp":
    "7672d4cba35748fe60aa0c6777fdf010a57d2f6548444bbb52abdc2c74f21882",
  "learning-art-v1/reflection.webp":
    "9b640d53ad2c951d0884d037b26983a03a845e34374e9655a3f97cc29c644a90",
  "learning-art-v1/next-move.webp":
    "df451fd23e75c27c7932bc71c8cb95c6543c3414ca3a44f6bf973185496e84e7",
};

const academyIconHashes: Record<string, string> = {
  "closers-academy-v0.1/icon-180.png":
    "fda4867411d5d71c8d6af35384bc9167685c66dd07637a6ae210a400d0cbf0b0",
  "closers-academy-v0.1/icon-192.png":
    "fc10e52eed1d810b01eb47f2240ae58cfcc2dd514a10086d32f5cfc72aa4b30f",
  "closers-academy-v0.1/icon-512.png":
    "9bd2911772a274c3b5e996da98b45a0bd8515907687e61551e37f144e563f57d",
};
const platformIconHashes: Record<string, string> = {
  "cohorva-v0.1/icon-180.png":
    "45fae2a38afe571d705739dd6ca6043918192236281dd37820eeb889722b5cbe",
};

function polygonPoints(svg: string) {
  return [...svg.matchAll(/<polygon\b[^>]*\bpoints="([^"]+)"/g)].map(
    (match) => match[1],
  );
}

describe("brand presentation boundary", () => {
  it("keeps decorative artwork serializable and independent from course identity or state", () => {
    expect(JSON.parse(JSON.stringify(ACADEMY_ARTWORK))).toEqual(
      ACADEMY_ARTWORK,
    );
    for (const artwork of Object.values(ACADEMY_ARTWORK)) {
      expect(Object.keys(artwork).sort()).toEqual(["height", "src", "width"]);
      expect(artwork.width).toBe(960);
      expect(artwork.height).toBe(840);
      expect(artwork.src).toMatch(/^\/brand\/learning-art-v1\/[a-z-]+\.webp$/);
    }
  });
  it("keeps company, academy and provisional platform identities distinct in serializable data", () => {
    const brands = [COMPANY_BRAND, FIRST_ACADEMY_BRAND, PLATFORM_BRAND];
    expect(brands.map(({ name, role }) => [name, role])).toEqual([
      ["Authority Closers", "company"],
      ["Closers Academy", "academy"],
      ["Cohorva", "platform"],
    ]);
    expect(PLATFORM_BRAND.releaseStatus).toBe("provisional-name");
    expect(JSON.parse(JSON.stringify(brands))).toEqual(brands);
    for (const brand of brands) {
      expect(Object.keys(brand).sort()).toEqual([
        "assets",
        "color",
        "name",
        "releaseStatus",
        "role",
      ]);
      for (const asset of Object.values(brand.assets)) {
        expect(asset).toMatch(/^\/brand\/[a-z-]+-v0\.1\/[a-z]+\.svg$/);
        expect(
          readFileSync(new URL(asset.slice(7), learnerBrandRoot)).length,
        ).toBeGreaterThan(0);
        expect(
          readFileSync(new URL(asset.slice(7), adminBrandRoot)).length,
        ).toBeGreaterThan(0);
      }
    }
  });
});

describe.each([
  ["company", BrandMark, COMPANY_BRAND],
  ["academy", AcademyMark, FIRST_ACADEMY_BRAND],
  ["platform", PlatformMark, PLATFORM_BRAND],
] as const)("%s identity mark", (_role, Mark, brand) => {
  it("renders the supplied symbol geometry with inherited color and no background mask", () => {
    const rendered = renderToStaticMarkup(createElement(Mark));
    const source = readFileSync(
      new URL(brand.assets.symbol.slice(7), learnerBrandRoot),
      "utf8",
    );
    expect(polygonPoints(rendered)).toEqual(polygonPoints(source));
    expect(rendered).toContain('viewBox="0 0 512 512"');
    expect(rendered).toContain('fill="currentColor"');
    expect(rendered).not.toMatch(/<rect\b|<image\b|ac-mark-cut/);
  });

  it("avoids duplicate announcements beside visible brand text", () => {
    const rendered = renderToStaticMarkup(createElement(Mark));
    expect(rendered).toContain('aria-hidden="true"');
    expect(rendered).toContain('focusable="false"');
    expect(rendered).not.toContain('role="img"');
  });

  it("exposes a named image when the mark is used without visible text", () => {
    const rendered = renderToStaticMarkup(
      createElement(Mark, {
        "aria-label": brand.name,
        className: "shell-brand-mark",
        width: 32,
        height: 32,
        style: { color: "#ffffff" },
      }),
    );
    expect(rendered).toContain(`aria-label="${brand.name}"`);
    expect(rendered).toContain('role="img"');
    expect(rendered).not.toContain("aria-hidden=");
    expect(rendered).toContain('class="shell-brand-mark"');
    expect(rendered).toContain('width="32" height="32"');
    expect(rendered).toContain('style="color:#ffffff"');
  });

  it("supports an external accessible label and explicit decorative overrides", () => {
    const labelled = renderToStaticMarkup(
      createElement(Mark, { "aria-labelledby": "identity-label" }),
    );
    expect(labelled).toContain('aria-labelledby="identity-label"');
    expect(labelled).toContain('role="img"');
    expect(labelled).not.toContain("aria-hidden=");
    const decorative = renderToStaticMarkup(
      createElement(Mark, {
        "aria-label": brand.name,
        "aria-hidden": true,
      }),
    );
    expect(decorative).toContain('aria-hidden="true"');
  });
});

describe("public brand asset allowlist", () => {
  it.each([
    [
      "learner",
      learnerBrandRoot,
      {
        ...sourceHashes,
        ...portraitHashes,
        ...academyIconHashes,
        ...learningArtworkHashes,
      },
    ],
    ["admin", adminBrandRoot, { ...sourceHashes, ...platformIconHashes }],
  ] as const)(
    "%s ships only verified assets, without prototype code or source media",
    (_app, root, hashes) => {
      const files = readdirSync(root, { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) =>
          relative(fileURLToPath(root), join(entry.parentPath, entry.name))
            .split(sep)
            .join("/"),
        );
      expect(files.sort()).toEqual(Object.keys(hashes).sort());
      for (const [path, hash] of Object.entries(hashes)) {
        const bytes = readFileSync(new URL(path, root));
        expect(createHash("sha256").update(bytes).digest("hex"), path).toBe(
          hash,
        );
        if (path.endsWith(".svg")) {
          const svg = bytes.toString("utf8");
          expect(svg).not.toMatch(
            /<script\b|<foreignObject\b|\son[a-z]+\s*=|<!DOCTYPE|<!ENTITY|javascript:/i,
          );
          expect(svg).not.toMatch(/(?:href|src)\s*=|url\(\s*["']?[^#]/i);
          expect(svg).not.toContain("<text");
        }
      }
    },
  );

  it.each([
    [learnerBrandRoot, "closers-academy-v0.1/icon-180.png", 180],
    [learnerBrandRoot, "closers-academy-v0.1/icon-192.png", 192],
    [learnerBrandRoot, "closers-academy-v0.1/icon-512.png", 512],
    [adminBrandRoot, "cohorva-v0.1/icon-180.png", 180],
  ] as const)(
    "retains supplied square PNG dimensions for %s %s",
    (root, path, size) => {
      const bytes = readFileSync(new URL(path, root));
      expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
      expect(bytes.readUInt32BE(16)).toBe(size);
      expect(bytes.readUInt32BE(20)).toBe(size);
    },
  );
});
