type CsvValue = string | number | null | undefined;

export function csvCell(value: CsvValue): string {
  const text = value == null ? "" : String(value);
  const safe = /^[\t\r]|^\s*[=+\-@＝＋－＠]/u.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function csvRows(rows: readonly (readonly CsvValue[])[]): string {
  return rows.map((row) => row.map(csvCell).join(",")).join("\n");
}
