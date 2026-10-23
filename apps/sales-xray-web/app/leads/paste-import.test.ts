import { expect, it } from "vitest";

import { PASTE_LIMIT, pastedFile, readPasted } from "./paste-import";

// Leads pasted as text (owner P0, 23 Oct 2026): a sheet's rows, a CSV, a
// Markdown table or a ChatGPT block, read into headings and rows.

it("reads rows copied from Google Sheets or Excel, headings first", () => {
  expect(
    readPasted(
      "Name\tPhone\tStage\tOwner\nAsha Example\t98765 43210\tNew\tSwamini\nRavi Sample\t+91 91234 56789\tInterested\t\n",
    ),
  ).toEqual({
    headers: ["Name", "Phone", "Stage", "Owner"],
    rows: [
      ["Asha Example", "98765 43210", "New", "Swamini"],
      ["Ravi Sample", "+91 91234 56789", "Interested", ""],
    ],
    namedHeaders: false,
    dropped: 0,
  });
});

it("reads a CSV with quoted commas, quotes and line breaks", () => {
  const read = readPasted(
    'name,phone,notes\r\n"Example, Asha",9876543210,"said ""call later""\nafter 5"\r\nRavi,9123456789,\r\n',
  );
  expect(read?.headers).toEqual(["name", "phone", "notes"]);
  expect(read?.rows).toEqual([
    ["Example, Asha", "9876543210", 'said "call later"\nafter 5'],
    ["Ravi", "9123456789", ""],
  ]);
});

it("reads semicolons when a sheet saved them instead of commas", () => {
  expect(readPasted("Name;Phone\nAsha;9876543210")?.rows).toEqual([
    ["Asha", "9876543210"],
  ]);
});

it("reads a ChatGPT answer's Markdown table, leaving the words around it", () => {
  const read = readPasted(
    [
      "Here are your leads:",
      "",
      "```markdown",
      "| Name | Phone | City |",
      "|------|:-----:|------|",
      "| Asha Example | 98765 43210 | Pune |",
      "| Meera \\| Joshi | 91234 56789 | Nashik |",
      "```",
      "",
      "Let me know if you need more.",
    ].join("\n"),
  );
  expect(read).toEqual({
    headers: ["Name", "Phone", "City"],
    rows: [
      ["Asha Example", "98765 43210", "Pune"],
      ["Meera | Joshi", "91234 56789", "Nashik"],
    ],
    namedHeaders: false,
    dropped: 0,
  });
});

it("names the columns from the values when the first line is a lead", () => {
  const read = readPasted(
    "1\tAsha Example\t98765 43210\tasha@example.com\n2\tRavi Sample\t91234 56789\t",
  );
  expect(read?.namedHeaders).toBe(true);
  expect(read?.headers).toEqual(["Column 1", "Name", "Phone", "Email"]);
  expect(read?.rows).toHaveLength(2);
});

it("takes a single column of names or numbers", () => {
  expect(readPasted("98765 43210\n91234 56789\n")).toMatchObject({
    headers: ["Phone"],
    rows: [["98765 43210"], ["91234 56789"]],
  });
});

it("keeps headings unique and fills blank ones", () => {
  expect(
    readPasted("Name\tPhone\t\tPhone\nAsha\t9876543210\tx\t9123456789")
      ?.headers,
  ).toEqual(["Name", "Phone", "Column 3", "Phone 2"]);
});

it("keeps the first 2,000 rows and says how many were left out", () => {
  const lines = ["Name\tPhone"];
  for (let index = 0; index < PASTE_LIMIT + 5; index += 1)
    lines.push(`Lead ${index}\t98765${String(index).padStart(5, "0")}`);
  const read = readPasted(lines.join("\n"));
  expect(read?.rows).toHaveLength(PASTE_LIMIT);
  expect(read?.dropped).toBe(5);
});

it("finds no rows in blank text or headings alone", () => {
  expect(readPasted("  \n\n ")).toBeNull();
  expect(readPasted("Name\tPhone\n")).toBeNull();
});

it("hands the rows on as a CSV file the import reads", async () => {
  const file = pastedFile({
    headers: ["Name", "Notes"],
    rows: [["Example, Asha", 'said "hi"']],
    namedHeaders: false,
    dropped: 0,
  });
  expect(file.name).toBe("Pasted leads.csv");
  expect(file.type).toBe("text/csv");
  expect(await file.text()).toBe('Name,Notes\n"Example, Asha","said ""hi"""');
});
