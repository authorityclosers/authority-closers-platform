import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const errors = [];

function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(absolute) : [absolute];
  });
}

function relativeToRoot(file) {
  return path.relative(root, file).replaceAll("\\", "/");
}

function frontmatterValue(frontmatter, key) {
  return frontmatter.match(new RegExp(`^${key}:\\s*(.+?)\\s*$`, "m"))?.[1];
}

function frontmatterArray(frontmatter, key) {
  const inline = frontmatter.match(
    new RegExp(`^${key}:[ \\t]+(.+?)[ \\t]*$`, "m"),
  )?.[1];
  const raw =
    inline ??
    frontmatter.match(
      new RegExp(
        `^${key}:[ \\t]*\\r?\\n[ \\t]*\\[([\\s\\S]*?)^[ \\t]*\\]`,
        "m",
      ),
    )?.[1];
  return raw
    ?.replace(/^\[/, "")
    .replace(/\]$/, "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

const allFiles = walk(root).sort();
const markdownFiles = allFiles.filter((file) => file.endsWith(".md"));
const jsonFiles = allFiles.filter((file) => file.endsWith(".json"));
const byStem = new Map(
  markdownFiles.map((file) => [path.basename(file, ".md"), file]),
);
const ids = new Map();
const titles = new Map();
const byType = {};
const visualBoards = [];
const visualSlotOwners = new Map();
let wikilinkCount = 0;
let imageEmbedCount = 0;
let fileLinkCount = 0;

for (const file of markdownFiles) {
  const relative = relativeToRoot(file);
  const content = fs.readFileSync(file, "utf8");
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!match) {
    errors.push(`${relative}: missing YAML frontmatter`);
    continue;
  }

  const frontmatter = match[1];
  const id = frontmatterValue(frontmatter, "id");
  const type = frontmatterValue(frontmatter, "type");
  const title = frontmatterValue(frontmatter, "title");
  const status = frontmatterValue(frontmatter, "status");
  const version = frontmatterValue(frontmatter, "version");
  const updated = frontmatterValue(frontmatter, "updated");

  for (const [key, value] of Object.entries({
    id,
    type,
    title,
    status,
    version,
    updated,
  })) {
    if (!value) errors.push(`${relative}: missing frontmatter ${key}`);
  }
  if (id && !/^[A-Z][A-Z0-9-]*$/.test(id)) {
    errors.push(`${relative}: unstable ID format ${id}`);
  }
  if (version !== "v0.1-alpha") {
    errors.push(`${relative}: unexpected version ${version}`);
  }
  if (id) {
    if (ids.has(id))
      errors.push(`${relative}: duplicate ID ${id} (${ids.get(id)})`);
    ids.set(id, relative);
  }
  if (title) {
    if (titles.has(title)) {
      errors.push(
        `${relative}: duplicate title ${title} (${titles.get(title)})`,
      );
    }
    titles.set(title, relative);
  }
  if (type) byType[type] = (byType[type] ?? 0) + 1;

  const obsidianLinks = [...content.matchAll(/(!?)\[\[([^\]]+)\]\]/g)];
  const ordinaryWikilinks = obsidianLinks.filter((link) => link[1] !== "!");
  wikilinkCount += ordinaryWikilinks.length;
  if (path.basename(file) !== "README.md" && ordinaryWikilinks.length === 0) {
    errors.push(`${relative}: node has no wikilinks`);
  }
  for (const link of obsidianLinks) {
    const target = link[2].split("|")[0].split("#")[0].trim();
    if (link[1] === "!") {
      imageEmbedCount += 1;
      if (path.isAbsolute(target)) {
        errors.push(`${relative}: Obsidian embed must be relative (${target})`);
        continue;
      }
      if (!/\.(?:gif|jpe?g|png|svg|webp)$/i.test(target)) {
        errors.push(`${relative}: unsupported Obsidian embed target ${target}`);
        continue;
      }
      if (!fs.existsSync(path.resolve(path.dirname(file), target))) {
        errors.push(`${relative}: missing Obsidian embed target ${target}`);
      }
      continue;
    }

    const stem = path.basename(target, ".md");
    if (!byStem.has(stem)) {
      errors.push(`${relative}: unresolved wikilink [[${link[2]}]]`);
    }
  }

  for (const link of content.matchAll(/!?\[[^\]]*\]\(([^)]+)\)/g)) {
    let target = link[1].trim();
    if (target.startsWith("<") && target.endsWith(">")) {
      target = target.slice(1, -1);
    }
    if (/^(https?:|mailto:|#)/i.test(target)) continue;
    target = target.split("#")[0];
    fileLinkCount += 1;
    if (path.isAbsolute(target)) {
      errors.push(`${relative}: repository link must be relative (${target})`);
      continue;
    }
    if (!fs.existsSync(path.resolve(path.dirname(file), target))) {
      errors.push(`${relative}: missing Markdown link target ${target}`);
    }
  }

  if (type === "visual-board") {
    const journeyId = frontmatterValue(frontmatter, "journey_id");
    const viewport = frontmatterValue(frontmatter, "viewport");
    const slots = frontmatterArray(frontmatter, "slot_ids");
    visualBoards.push({ file, id, journeyId, viewport, slots: slots ?? [] });

    if (!/^JRN-0[1-6]$/.test(journeyId ?? "")) {
      errors.push(`${relative}: invalid visual-board journey_id ${journeyId}`);
    }
    if (!/^(desktop|mobile)$/.test(viewport ?? "")) {
      errors.push(`${relative}: invalid visual-board viewport ${viewport}`);
    }
    if (!slots?.length)
      errors.push(`${relative}: missing visual-board slot_ids`);

    const expectedPrefix = journeyId
      ? `VJS-${journeyId.replace("JRN-", "J")}-${viewport === "desktop" ? "D" : "M"}-`
      : "";
    const bodySlots = new Set(content.match(/VJS-J\d{2}-[DM]-\d{2}/g) ?? []);
    for (const [index, slot] of (slots ?? []).entries()) {
      const expectedSlot = `${expectedPrefix}${String(index + 1).padStart(2, "0")}`;
      if (slot !== expectedSlot) {
        errors.push(
          `${relative}: slot ${slot} is not ordered as ${expectedSlot}`,
        );
      }
      if (!bodySlots.has(slot)) {
        errors.push(
          `${relative}: frontmatter slot ${slot} missing from board body`,
        );
      }
      if (visualSlotOwners.has(slot)) {
        errors.push(
          `${relative}: duplicate visual slot ${slot} (${visualSlotOwners.get(slot)})`,
        );
      }
      visualSlotOwners.set(slot, relative);
    }
    for (const slot of bodySlots) {
      if (!(slots ?? []).includes(slot)) {
        errors.push(
          `${relative}: body slot ${slot} missing from frontmatter slot_ids`,
        );
      }
    }
    if (
      !content.includes("Expected route/state") ||
      !content.includes("Source reference")
    ) {
      errors.push(`${relative}: visual-board traceability columns missing`);
    }
  }
}

const parsedJson = new Map();
for (const file of jsonFiles) {
  try {
    parsedJson.set(
      relativeToRoot(file),
      JSON.parse(fs.readFileSync(file, "utf8")),
    );
  } catch (error) {
    errors.push(`${relativeToRoot(file)}: invalid JSON (${error.message})`);
  }
}

const graphConfig = parsedJson.get(".obsidian/graph.json");
const graphColorGroups = graphConfig?.colorGroups;
if (!graphConfig) {
  errors.push(".obsidian/graph.json: missing or invalid graph configuration");
} else {
  if (!Array.isArray(graphColorGroups) || graphColorGroups.length !== 13) {
    errors.push(".obsidian/graph.json: expected 13 graph color groups");
  }
  const queries = (graphColorGroups ?? []).map((group) => group.query);
  if (new Set(queries).size !== queries.length) {
    errors.push(".obsidian/graph.json: duplicate graph color-group queries");
  }
  if (
    !graphConfig.hideUnresolved ||
    graphConfig.showOrphans ||
    !graphConfig.showArrow
  ) {
    errors.push(
      ".obsidian/graph.json: traceability display settings are not active",
    );
  }
}

const requiredIds = [
  "MOC-AC-V01A",
  "META-001",
  "META-002",
  "META-003",
  "META-004",
  "JRN-01",
  "JRN-02",
  "JRN-03",
  "JRN-04",
  "JRN-05",
  "JRN-06",
  "SF-AUTH-001",
  "ONB-01",
  "HOME-01",
  "SF-COURSE-001",
  "MOD-01",
  "ACT-01",
  "ACT-02",
  "SF-EVIDENCE-001",
  "PROG-01",
  "SF-SET-001",
  "SF-SYS-001",
  "VAR-RESP-001",
  "VAR-THEME-001",
  "VJB-MOC-001",
  "WKS-001",
];
for (let journey = 1; journey <= 6; journey += 1) {
  for (const viewport of ["D", "M"]) {
    requiredIds.push(`VJB-JRN-0${journey}-${viewport}`);
  }
}
for (const id of requiredIds) {
  if (!ids.has(id)) errors.push(`required node ID missing: ${id}`);
}

if (visualBoards.length !== 12) {
  errors.push(`expected 12 visual boards, found ${visualBoards.length}`);
}
const visualMoc = fs.readFileSync(
  path.join(root, "VJB-MOC-001-visual-journey-boards.md"),
  "utf8",
);
for (const board of visualBoards) {
  const stem = path.basename(board.file, ".md");
  if (!visualMoc.includes(`[[${stem}]]`)) {
    errors.push(
      `VJB-MOC-001-visual-journey-boards.md: missing board link [[${stem}]]`,
    );
  }
}

const report = {
  status: errors.length === 0 ? "PASS" : "FAIL",
  files_checked: allFiles.length,
  markdown_nodes: markdownFiles.length,
  json_files: jsonFiles.length,
  unique_ids: ids.size,
  unique_titles: titles.size,
  wikilinks: wikilinkCount,
  repository_file_links: fileLinkCount,
  obsidian_image_embeds: imageEmbedCount,
  visual_boards: visualBoards.length,
  visual_slots: visualSlotOwners.size,
  graph_color_groups: graphColorGroups?.length ?? 0,
  nodes_by_type: Object.fromEntries(
    Object.entries(byType).sort(([a], [b]) => a.localeCompare(b)),
  ),
  errors,
};

console.log(JSON.stringify(report, null, 2));
if (errors.length > 0) process.exitCode = 1;
