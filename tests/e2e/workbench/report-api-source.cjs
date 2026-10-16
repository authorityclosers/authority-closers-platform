// Read the committed fictional source directly, without its UI reader/mapper.
const { createHash } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const app = path.resolve(__dirname, "../../../apps/sales-xray-web");
const ts = require(path.join(app, "node_modules/typescript"));
const sources = {};

require.extensions[".ts"] = (module, filename) => {
  if (!filename.startsWith(path.join(app, "app") + path.sep)) {
    throw new Error("Only local fictional Report source dependencies are allowed");
  }
  const source = fs.readFileSync(filename, "utf8");
  sources[path.relative(app, filename)] = createHash("sha256")
    .update(source)
    .digest("hex");
  module._compile(
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    }).outputText,
    filename,
  );
};

const fixture = path.join(app, "app/review-fixture/report/story");
const { AMIT_STRUCTURE } = require(path.join(fixture, "amit-structure.ts"));
const { amitTranscript } = require(path.join(fixture, "amit-call.ts"));
process.stdout.write(
  JSON.stringify({ structure: AMIT_STRUCTURE, transcript: amitTranscript, sources }),
);
