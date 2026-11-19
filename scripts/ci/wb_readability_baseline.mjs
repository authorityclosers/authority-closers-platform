// Builds the Readability Gate's baseline from one or more hosted recording runs (wb_readability.mjs; see
// scripts/qa/README.md, "A new baseline"). A finding any of the runs saw is known.
//
//   node scripts/ci/wb_readability_baseline.mjs <baseline.json> <readability.json> [<readability.json> ...]
import { readFile, writeFile } from "node:fs/promises";
import { baselineFrom } from "./wb_readability_lib.mjs";

const [out, ...inputs] = process.argv.slice(2);
if (!out || !inputs.length) {
  console.error("usage: wb_readability_baseline.mjs <baseline.json> <readability.json> [...]");
  process.exit(2);
}
const runs = [];
for (const path of inputs) runs.push(JSON.parse(await readFile(path, "utf8")).rows);
const { cells, errors } = baselineFrom(runs);
await writeFile(out, `${JSON.stringify({ schema: "ac.wb-readability-baseline/1", cells }, null, 1)}\n`);
const total = Object.values(cells).reduce((sum, names) => sum + names.length, 0);
console.log(`${Object.keys(cells).length} states, ${total} findings from ${inputs.length} run(s)`);
for (const error of errors) console.log(`could not measure: ${error}`);
process.exit(errors.length ? 1 : 0);
