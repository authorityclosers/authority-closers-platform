/** Independent credit reads: exact ledger quantities, never minute conversions. */
import { ContractError, type Account } from "./contract";

export type CreditBalance = {
  account: Account;
  accountId: string | null;
  balance: string;
};

export type CreditEntry = {
  entryId: string;
  quantity: string;
  createdAt: string;
  correctedEntryId: string | null;
};

export type CreditHistory = {
  account: Account;
  accountId: string | null;
  entries: CreditEntry[];
  nextBefore: string | null;
};

function object(
  value: unknown,
  path: string,
  keys: readonly string[],
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ContractError(path, "expected an object");
  const raw = value as Record<string, unknown>;
  for (const key of Object.keys(raw))
    if (!keys.includes(key))
      throw new ContractError(`${path}.${key}`, "unknown field");
  for (const key of keys)
    if (!Object.prototype.hasOwnProperty.call(raw, key))
      throw new ContractError(`${path}.${key}`, "missing field");
  return raw;
}

function matchingText(value: unknown, path: string, pattern: RegExp): string {
  // Compare the whole match: JavaScript's $ also matches before a final newline.
  if (typeof value !== "string" || pattern.exec(value)?.[0] !== value)
    throw new ContractError(path, "invalid text");
  return value;
}

export function parseCreditAccount(value: unknown, path: string): Account {
  if (value !== "personal" && value !== "organisation")
    throw new ContractError(path, "expected personal or organisation");
  return value;
}

export function parseCreditId(value: unknown, path: string): string {
  return matchingText(
    value,
    path,
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  );
}

function nullableId(value: unknown, path: string): string | null {
  return value === null ? null : parseCreditId(value, path);
}

function quantity(value: unknown, path: string): string {
  return matchingText(value, path, /^[+-]?\d+(?:\.\d+)?$/);
}

function utcTime(value: unknown, path: string): string {
  const text = matchingText(
    value,
    path,
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/,
  );
  // Check calendar/time validity without changing the original fractional text.
  const seconds = text.slice(0, 19);
  if (new Date(`${seconds}Z`).toJSON()?.slice(0, 19) !== seconds)
    throw new ContractError(path, "expected a valid UTC date-time");
  return text;
}

export function parseCreditBalance(value: unknown): CreditBalance {
  const path = "credits";
  const raw = object(value, path, ["account", "account_id", "balance"]);
  return {
    account: parseCreditAccount(raw.account, `${path}.account`),
    accountId: nullableId(raw.account_id, `${path}.account_id`),
    balance: quantity(raw.balance, `${path}.balance`),
  };
}

export function parseCreditHistory(value: unknown): CreditHistory {
  const path = "credits.history";
  const raw = object(value, path, [
    "account",
    "account_id",
    "entries",
    "next_before",
  ]);
  if (!Array.isArray(raw.entries))
    throw new ContractError(`${path}.entries`, "expected a list");
  return {
    account: parseCreditAccount(raw.account, `${path}.account`),
    accountId: nullableId(raw.account_id, `${path}.account_id`),
    entries: raw.entries.map((value, index) => {
      const entryPath = `${path}.entries[${index}]`;
      const entry = object(value, entryPath, [
        "entry_id",
        "quantity",
        "created_at",
        "corrected_entry_id",
      ]);
      return {
        entryId: parseCreditId(entry.entry_id, `${entryPath}.entry_id`),
        quantity: quantity(entry.quantity, `${entryPath}.quantity`),
        createdAt: utcTime(entry.created_at, `${entryPath}.created_at`),
        correctedEntryId: nullableId(
          entry.corrected_entry_id,
          `${entryPath}.corrected_entry_id`,
        ),
      };
    }),
    nextBefore: nullableId(raw.next_before, `${path}.next_before`),
  };
}
