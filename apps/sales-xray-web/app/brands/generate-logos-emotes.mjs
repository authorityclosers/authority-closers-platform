#!/usr/bin/env node
// Builds the colour brand logos for the web app.
//
//   node app/brands/generate-logos-emotes.mjs <iconify dir> <app dir>
//
// <iconify dir> holds the unpacked npm packages @iconify-json/logos (CC0-1.0,
// full-colour logos by Gil Barbara), @iconify-json/cib (CC0-1.0, CoreUI
// brands),
// as logos/, cib/ and emo/. Only what the app uses is copied:
//   public/brands/color.json  logos for our curated brands (app/brands/brand-registry.ts)
// and the registry rows gain `logo: true` where a colour logo exists, so the
// app knows to wait for it instead of flashing the one-colour icon first.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [iconDir, appDir] = process.argv.slice(2);
if (!iconDir || !appDir) {
  console.error("usage: generate-logos-emotes.mjs <iconify dir> <app dir>");
  process.exit(2);
}
const read = (path) => JSON.parse(readFileSync(path, "utf8"));
const logos = read(join(iconDir, "logos/package/icons.json"));
const cib = read(join(iconDir, "cib/package/icons.json"));

// Our brand key → the logo to use, when the names differ.
const ALIAS = {
  chatgpt: "openai",
  teams: "microsoft-teams",
  gemini: "google-gemini",
  x: "x",
  apple: "apple",
  chrome: "chrome",
  googlemeet: "google-meet",
  googledrive: "google-drive",
  googlecalendar: "google-calendar",
  googlemaps: "google-maps",
  googleads: "google-ads",
  googlepay: "google-pay",
  googleplay: "google-play",
  googlesheets: "google-sheets",
  googledocs: "google-docs",
  googleforms: "google-forms",
  primevideo: "prime-video",
};

const DARK =
  /#(?:0{3}|0{6}|1[0-9a-f]1[0-9a-f]1[0-9a-f]|2[0-2]2[0-2]2[0-2]|191919|1a1a1a|181717|231f20|222|333|303030)\b/gi;

function shape(set, name) {
  const icon = set.icons[name];
  if (!icon) return null;
  const w = icon.width ?? set.width ?? 16;
  const h = icon.height ?? set.height ?? 16;
  if (w / h > 1.35 || h / w > 1.35) return null; // wordmarks do not fit a chip
  let body = icon.body;
  if (/<script|\son\w+=/i.test(body)) return null;
  const fills = body.match(/#[0-9a-f]{3,6}\b/gi) ?? [];
  // All-black logos follow the text colour so they show in dark mode.
  const ink = fills.length > 0 && fills.every((fill) => fill.match(DARK));
  if (ink) body = body.replace(DARK, "currentColor");
  return { w, h, body, ...(ink ? { ink: true } : {}) };
}

const registryPath = join(appDir, "app/brands/brand-registry.ts");
let registry = readFileSync(registryPath, "utf8");
const rows = [
  ...registry.matchAll(
    /key: "([^"]+)",\s*name: "([^"]+)",\s*slug: (null|"[^"]*"),/g,
  ),
];
const color = {};
const found = [];
const missing = [];
for (const [, key, name, slugRaw] of rows) {
  const slug = slugRaw === "null" ? null : slugRaw.slice(1, -1);
  const dashed = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const candidates = [ALIAS[key], key, slug, dashed].filter(Boolean);
  let got = null;
  for (const base of candidates) {
    got = shape(logos, `${base}-icon`) ?? shape(logos, base);
    if (got) break;
  }
  if (!got)
    for (const base of candidates) {
      got = shape(cib, base);
      if (got) {
        got = { ...got, mono: true };
        break;
      }
    }
  if (got) {
    color[key] = got;
    found.push(key);
  } else missing.push(key);
}

registry = registry.replace(
  /(key: "([^"]+)",\s*name: "[^"]+",\s*slug: (?:null|"[^"]*"),\s*hex: "[^"]+",)(\s*logo: true,)?/g,
  (_all, head, key) => `${head}${color[key] ? "\n    logo: true," : ""}`,
);
if (!registry.includes("logo?: boolean"))
  registry = registry.replace(
    "  hex: string;\n",
    "  hex: string;\n  /** A colour logo exists in public/brands/color.json. */\n  logo?: boolean;\n",
  );
writeFileSync(registryPath, registry);

mkdirSync(join(appDir, "public/brands"), { recursive: true });
writeFileSync(
  join(appDir, "public/brands/color.json"),
  JSON.stringify({
    source: "@iconify-json/logos (CC0-1.0), @iconify-json/cib (CC0-1.0)",
    icons: color,
  }),
);

console.log(`colour logos: ${found.length} (${found.join(" ")})`);
console.log(`no colour logo: ${missing.join(" ")}`);
console.log(
  `emotes: ${Object.keys(emotes).length}; not found: ${noEmote.join(" ") || "none"}`,
);
