import { expect, it } from "vitest";
import { csvCell, csvRows } from "./csv-export";

it.each([
  "=1+1",
  " @SUM(A1)",
  "-2+3",
  "+cmd|' /C calc'!A0",
  "\ttext",
  "\rtext",
  "＝1",
  "＋1",
  "－1",
  "＠SUM(A1)",
  " \t=1",
])("neutralises formula prefix %j", (value) => {
  expect(csvCell(value)).toBe(`"'${value}"`);
});

it.each([
  "Plain title",
  "inside\ttab",
  "inside\rCR",
  "line\nline",
  "",
  0,
  null,
  undefined,
])("quotes ordinary cells %j", (value) => {
  expect(csvCell(value)).toBe(`"${value ?? ""}"`);
});

it("escapes whole rows with LF separators and preserves the Link column", () => {
  expect(
    csvRows([
      ["Call", "Assessment", "Link"],
      [
        "=1+1",
        '-Assessment says "yes",\nthen\rno',
        "https://example.test/calls/1",
      ],
    ]),
  ).toBe(
    '"Call","Assessment","Link"\n"\'=1+1","\'-Assessment says ""yes"",\nthen\rno","https://example.test/calls/1"',
  );
});
