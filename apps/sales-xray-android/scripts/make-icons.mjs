// Draws the Sales Xray launcher icons and splash screens (teal audio bars on
// navy, matching the app's sidebar mark). Run once on the dev server with the
// web app's sharp: node scripts/make-icons.mjs <path-to-sharp>
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const sharp = require(process.argv[2] ?? "sharp");
const res = path.resolve("android/app/src/main/res");
const NAVY = "#0b1220";
const TEAL = "#2dd4bf";

// Five rounded bars inside a 108-unit adaptive-icon canvas (safe zone 66).
const bars = (scale, x0, y0) =>
  [
    [0, 44, 20],
    [12, 32, 44],
    [24, 24, 60],
    [36, 36, 36],
    [48, 30, 48],
  ]
    .map(
      ([x, y, h]) =>
        `<rect x="${x0 + x * scale}" y="${y0 + (y - 24) * scale}" width="${7 * scale}" height="${h * scale}" rx="${3.5 * scale}" fill="${TEAL}"/>`,
    )
    .join("");

const foreground = (size) => {
  const s = size / 108;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">${bars(s, 26.5 * s, 24 * s)}</svg>`;
};
const legacy = (size, round) => {
  const s = size / 108;
  const shape = round
    ? `<circle cx="${size / 2}" cy="${size / 2}" r="${size / 2}" fill="${NAVY}"/>`
    : `<rect width="${size}" height="${size}" rx="${size * 0.22}" fill="${NAVY}"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">${shape}${bars(s, 26.5 * s, 24 * s)}</svg>`;
};
const splash = (w, h) => {
  const size = Math.min(w, h) * 0.42;
  const s = size / 108;
  const x = (w - size) / 2;
  const y = (h - size) / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="${NAVY}"/>${bars(s, x + 26.5 * s, y + 24 * s)}</svg>`;
};

async function write(svg, file) {
  mkdirSync(path.dirname(file), { recursive: true });
  await sharp(Buffer.from(svg)).png().toFile(file);
}

const densities = { mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 };
for (const [name, k] of Object.entries(densities)) {
  await write(legacy(48 * k, false), `${res}/mipmap-${name}/ic_launcher.png`);
  await write(legacy(48 * k, true), `${res}/mipmap-${name}/ic_launcher_round.png`);
  await write(foreground(108 * k), `${res}/mipmap-${name}/ic_launcher_foreground.png`);
  await write(splash(320 * k, 480 * k), `${res}/drawable-port-${name}/splash.png`);
  await write(splash(480 * k, 320 * k), `${res}/drawable-land-${name}/splash.png`);
}
await write(splash(480, 800), `${res}/drawable/splash.png`);
console.log("icons written");
