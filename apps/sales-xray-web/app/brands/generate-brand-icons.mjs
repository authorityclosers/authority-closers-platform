#!/usr/bin/env node
// Builds public/brands/ from the Simple Icons package (CC0-1.0).
//
//   node app/brands/generate-brand-icons.mjs <simple-icons package dir> <out dir>
//
// Writes index.json (every icon's title, slug and colour, used to find the
// icon for any brand name) and one file per first letter of the slug holding
// the SVG paths, so a page loads only the letters it needs. Icons whose own
// licence is not CC0 are left out, and so are very large paths; those brands
// show a monogram in their colour instead.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [pkgDir, outDir] = process.argv.slice(2);
if (!pkgDir || !outDir) {
  console.error("usage: generate-brand-icons.mjs <simple-icons dir> <out dir>");
  process.exit(2);
}

const MAX_PATH = 12_000;
const pkg = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
const data = JSON.parse(
  readFileSync(join(pkgDir, "data", "simple-icons.json"), "utf8"),
);
const licence = new Map(data.map((icon) => [icon.slug, icon.license]));
const aliases = new Map(data.map((icon) => [icon.slug, icon.aliases]));
const all = await import(pathToFileURL(join(pkgDir, "index.mjs")).href);

const icons = Object.values(all)
  .filter((icon) => icon && icon.slug && icon.path)
  .filter((icon) => {
    const own = licence.get(icon.slug);
    return !own || own.type === "CC0-1.0";
  })
  .filter((icon) => icon.path.length <= MAX_PATH)
  .sort((a, b) => a.slug.localeCompare(b.slug));

const shards = {};
const index = [];
for (const icon of icons) {
  const key = /^[a-z]/.test(icon.slug) ? icon.slug[0] : "0";
  (shards[key] ??= {})[icon.slug] = icon.path;
  const names = [icon.title];
  const own = aliases.get(icon.slug);
  for (const name of [...(own?.aka ?? []), ...Object.values(own?.loc ?? {})])
    if (!names.includes(name)) names.push(name);
  index.push([names, icon.slug, icon.hex]);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(
  join(outDir, "index.json"),
  JSON.stringify({
    source: `simple-icons@${pkg.version}`,
    licence: "CC0-1.0",
    icons: index,
  }),
);
for (const [key, paths] of Object.entries(shards))
  writeFileSync(join(outDir, `${key}.json`), JSON.stringify(paths));

console.log(
  `simple-icons@${pkg.version}: ${icons.length} icons, ${Object.keys(shards).length} files`,
);
