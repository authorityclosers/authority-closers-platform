/**
 * Leads pasted as text (owner P0, 23 Oct 2026: "paste from Sheets/Excel, CSV,
 * Markdown or a ChatGPT block"): rows copied from a sheet (tab-separated), a
 * CSV, a Markdown table, or any of these inside a ChatGPT code block. Read into
 * headings and rows, then handed to the file import's own preview as a CSV, so
 * the columns are matched, counted and added exactly as a file's are.
 */

/** The import takes this many rows at once. */
export const PASTE_LIMIT = 2000;

/** The name the pasted rows travel under, and how the preview knows them. */
export const PASTED_FILE = "Pasted leads.csv";

export type Pasted = {
  headers: string[];
  rows: string[][];
  /** The first line was a lead, not headings: these were named from the values. */
  namedHeaders: boolean;
  /** Rows past the limit, left out. */
  dropped: number;
};

const FENCE = /^\s*(```|~~~)/;
const RULE = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
/** Headings a sheet of leads usually has (any one marks the first line). */
const HEADING =
  /^(s\.?\s?no\.?|sr\.?\s?no\.?|#|name|full name|first name|last name|lead|lead name|customer|client|contact|phone|phone number|mobile|mobile number|number|whatsapp|contact number|email|e-mail|mail|company|business|organisation|organization|city|location|area|place|language|interest|course|product|requirement|stage|status|lead stage|owner|assigned to|assignee|sales rep|rep|source|notes?|remarks?|comments?|date|created)$/i;

/** Only the code block, when the text is a chat answer with one in it. */
function insideFence(text: string): string {
  const lines = text.split("\n");
  const open = lines.findIndex((line) => FENCE.test(line));
  if (open < 0) return text;
  const close = lines.findIndex(
    (line, index) => index > open && FENCE.test(line),
  );
  return lines.slice(open + 1, close < 0 ? undefined : close).join("\n");
}

/** Delimited text with quotes ("a, b" and "" inside), as sheets and CSV write it. */
function splitDelimited(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"' && cell.trim() === "") {
      quoted = true;
      cell = "";
    } else if (char === delimiter) {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += char;
  }
  row.push(cell);
  rows.push(row);
  return rows;
}

function splitMarkdown(lines: string[]): {
  rows: string[][];
  headed: boolean;
} {
  const cells = (line: string) =>
    line
      .trim()
      .replace(/^\|/, "")
      .replace(/(?<!\\)\|$/, "")
      .split(/(?<!\\)\|/)
      .map((cell) => cell.replace(/\\\|/g, "|"));
  const headed = lines.length > 1 && RULE.test(lines[1]);
  return {
    rows: lines.filter((line) => !RULE.test(line)).map(cells),
    headed,
  };
}

const digits = (cell: string) => cell.replace(/\D/g, "").length;
const isPhone = (cell: string) =>
  digits(cell) >= 7 && /^[\d\s()+.-]+$/.test(cell);
const isEmail = (cell: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cell);
const isLead = (row: string[]) =>
  row.some((cell) => isPhone(cell) || isEmail(cell));

/** Headings from the values when the first line is a lead already. */
function nameColumns(rows: string[][], width: number): string[] {
  const share = (column: number, test: (cell: string) => boolean) => {
    const filled = rows.filter((row) => row[column]);
    return filled.length
      ? filled.filter((row) => test(row[column])).length / filled.length
      : 0;
  };
  const names = Array.from({ length: width }, (_, column): string =>
    share(column, isPhone) >= 0.6
      ? "Phone"
      : share(column, isEmail) >= 0.6
        ? "Email"
        : "",
  );
  const text = names.findIndex(
    (name, column) =>
      !name && share(column, (cell) => /[^\W\d_]/u.test(cell)) >= 0.6,
  );
  if (text >= 0) names[text] = "Name";
  return names;
}

/** Headings that are each there once and never blank. */
function uniqueHeadings(headers: string[]): string[] {
  const seen = new Map<string, number>();
  return headers.map((header, index) => {
    const base = header.trim() || `Column ${index + 1}`;
    const count = (seen.get(base.toLowerCase()) ?? 0) + 1;
    seen.set(base.toLowerCase(), count);
    return count === 1 ? base : `${base} ${count}`;
  });
}

/** The rows in pasted text, or null when it holds no rows at all. */
export function readPasted(text: string): Pasted | null {
  const body = insideFence(text.replace(/\r\n?/g, "\n"));
  const lines = body.split("\n").filter((line) => line.trim());
  if (!lines.length) return null;
  let rows: string[][];
  let headed: boolean | null = null;
  if (lines.filter((line) => line.trim().startsWith("|")).length >= 2) {
    const table = splitMarkdown(
      lines.filter((line) => line.trim().startsWith("|")),
    );
    rows = table.rows;
    if (table.headed) headed = true;
  } else {
    const first = lines[0];
    const delimiter = first.includes("\t")
      ? "\t"
      : (first.match(/;/g)?.length ?? 0) > (first.match(/,/g)?.length ?? 0)
        ? ";"
        : ",";
    rows = splitDelimited(lines.join("\n"), delimiter);
  }
  rows = rows
    .map((row) => row.map((cell) => cell.trim()))
    .filter((row) => row.some(Boolean));
  if (!rows.length) return null;
  const width = Math.max(...rows.map((row) => row.length));
  rows = rows.map((row) =>
    row.length < width ? [...row, ...Array(width - row.length).fill("")] : row,
  );
  headed ??=
    rows[0].some((cell) => HEADING.test(cell)) ||
    (!isLead(rows[0]) && rows.slice(1).some(isLead));
  const data = headed ? rows.slice(1) : rows;
  if (!data.length) return null;
  const kept = data.slice(0, PASTE_LIMIT);
  return {
    headers: uniqueHeadings(headed ? rows[0] : nameColumns(kept, width)),
    rows: kept,
    namedHeaders: !headed,
    dropped: data.length - kept.length,
  };
}

const csvCell = (cell: string) =>
  /[",\n\r]|^\s|\s$/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;

/** The pasted rows as a CSV file for the import's preview. */
export function pastedFile(pasted: Pasted): File {
  const text = [pasted.headers, ...pasted.rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\n");
  return new File([text], PASTED_FILE, { type: "text/csv" });
}
