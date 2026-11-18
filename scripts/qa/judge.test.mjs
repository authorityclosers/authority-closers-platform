// node --test scripts/qa/judge.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT_MODEL,
  MODELS,
  cropOf,
  exitOf,
  fitBox,
  modelOf,
  parseArgs,
  promptOf,
  tokensOf,
  verdictOf,
} from "./judge.mjs";

test("the model flag: sonnet by default, short names, a full id passed through, anything else refused", () => {
  assert.equal(DEFAULT_MODEL, "sonnet");
  assert.equal(modelOf(), MODELS.sonnet);
  assert.equal(modelOf("Haiku"), MODELS.haiku);
  assert.equal(modelOf("claude-opus-5-5"), "claude-opus-5-5");
  assert.throws(() => modelOf("gpt"), /unknown model/);
});

test("pictures are sized before a model sees them", () => {
  assert.equal(tokensOf(363, 735), 356);
  assert.equal(tokensOf(1089, 2205), 3202);
  assert.deepEqual(fitBox(363, 735), { width: 363, height: 735 });
  assert.deepEqual(fitBox(1089, 2205, 1568), { width: 774, height: 1568 });
  assert.deepEqual(cropOf("0, 80,363,200"), { left: 0, top: 80, width: 363, height: 200 });
  assert.equal(cropOf(undefined), null);
  assert.throws(() => cropOf("1,2,3"), /--crop/);
});

test("arguments: a picture and one narrow question are required; a script's job is refused", () => {
  const ok = parseArgs(["--after", "a.png", "--question", "Is the primary action obvious in two seconds?"]);
  assert.equal(ok.modelId, MODELS.sonnet);
  assert.equal(ok.dry, false);
  assert.equal(parseArgs(["--after", "a.png", "--question", "Is the heading clear?", "--model", "haiku", "--dry"]).modelId, MODELS.haiku);
  assert.throws(() => parseArgs(["--question", "Is the heading clear?"]), /--after/);
  assert.throws(() => parseArgs(["--after", "a.png"]), /--question/);
  assert.throws(() => parseArgs(["--after", "a.png", "--question", "Does any text overlap here?"]), /script's job/);
  assert.throws(() => parseArgs(["--after", "a.png", "--question", "Is the contrast fine?"]), /script's job/);
  assert.throws(() => parseArgs(["--after", "a.png", "--question", "Is it clear?", "--nope"]), /unknown flag/);
});

test("the prompt keeps the judge on the question and off the scripts' checks", () => {
  const one = promptOf({ question: "Is the heading clear?" });
  assert.match(one, /after\.png/);
  assert.doesNotMatch(one, /before\.png/);
  assert.match(one, /Do not judge sideways overflow/);
  assert.match(promptOf({ question: "Is the heading clear?", before: "b.png" }), /before\.png/);
});

test("the verdict is read out of the model's words; no verdict is unsure", () => {
  const said = 'Here you go:\n{"verdict":"fail","reasons":["The button is below the fold"],"where":["footer"]}';
  assert.deepEqual(verdictOf(said), { verdict: "fail", reasons: ["The button is below the fold"], where: ["footer"] });
  assert.equal(verdictOf("I think it is fine"), null);
  assert.equal(verdictOf('{"verdict":"great"}'), null);
  assert.equal(exitOf({ verdict: "pass" }), 0);
  assert.equal(exitOf({ verdict: "fail" }), 1);
  assert.equal(exitOf(null), 2);
});
