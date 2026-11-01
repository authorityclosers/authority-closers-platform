// Calls into the matrix on ac: persona-qa's qa_matrix.py for result and bug, engine (b)'s matrix.py for claim,
// release and sweeps. execFile with an argument list, so no shell quoting touches the words.
const { execFile } = require("child_process");
const path = require("path");
const cfg = require("./config.cjs");

const QA = path.join(cfg.MATRIX_DIR, "qa_matrix.py");
const MINE = path.join(cfg.ROOT, "matrix.py");

function once(script, args) {
  return new Promise((resolve, reject) => {
    execFile("python3", [script, ...args], { maxBuffer: 16 * 1024 * 1024, timeout: 150000 }, (error, stdout, stderr) => {
      if (error) {
        const lastLine = String(stderr || "").trim().split("\n").pop() || String(error.message).split("\n")[0];
        return reject(new Error(`${path.basename(script)} ${args[0]}${error.killed ? " (timed out waiting for the matrix lock)" : ""}: ${lastLine.slice(0, 200)}`));
      }
      resolve(stdout);
    });
  });
}

// The matrix's file lock is held while the sheet is rebuilt, which is slow on a busy box: try again, a little apart.
async function run(script, args) {
  let last;
  for (const wait of [0, 4000, 12000]) {
    if (wait) await new Promise((resolve) => setTimeout(resolve, wait));
    try {
      return await once(script, args);
    } catch (error) {
      last = error;
    }
  }
  throw last;
}
const lines = (text) => text.split("\n").filter(Boolean).map((l) => JSON.parse(l));
const flags = (obj) => Object.entries(obj).flatMap(([k, v]) => (v === undefined || v === null || v === "" ? [] : [`--${k}`, String(v)]));

module.exports = {
  claim: async (o) => lines(await run(MINE, ["claim", ...flags(o)])),
  scope: async (o) => lines(await run(MINE, ["scope", ...flags(o)]))[0],
  release: (workflow) => run(MINE, ["release", "--workflow", workflow]),
  personas: async () => JSON.parse(await run(MINE, ["personas"])),
  list: async (o) => JSON.parse(await run(MINE, ["list", ...flags(o)])),
  personaDetail: async () => {
    if (!module.exports._detail) module.exports._detail = Object.fromEntries((await module.exports.personas()).map((p) => [p.id, p]));
    return module.exports._detail;
  },
  annotate: async (o) => lines(await run(MINE, ["annotate", ...flags(o)]))[0],
  sweep: async (o) => lines(await run(MINE, ["sweep", ...flags(o)]))[0],
  result: async (o) => lines(await run(QA, ["result", "--engine", "script", ...flags(o)]))[0],
  bug: async (o) => lines(await run(QA, ["bug", ...flags(o)]))[0],
  stats: async () => lines(await run(QA, ["stats"]))[0],
};
