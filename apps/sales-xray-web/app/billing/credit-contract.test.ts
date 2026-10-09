import { describe, expect, it } from "vitest";
import { ContractError } from "./contract";
import { parseCreditBalance, parseCreditHistory } from "./credit-contract";

const ACCOUNT_ID = "11111111-1111-4111-8111-111111111111";
const ENTRY_ID = "22222222-2222-4222-8222-222222222222";
const CORRECTED_ID = "33333333-3333-4333-8333-333333333333";
const BALANCE = {
  account: "personal",
  account_id: ACCOUNT_ID,
  balance: "1.250000",
};
const ENTRY = {
  entry_id: ENTRY_ID,
  quantity: "-0.250000",
  created_at: "2026-10-05T09:00:00Z",
  corrected_entry_id: null,
};
const HISTORY = {
  account: "personal",
  account_id: ACCOUNT_ID,
  entries: [ENTRY],
  next_before: null,
};

describe("independent exact credit quantities", () => {
  it.each([
    "1.250000",
    "-0.250000",
    "9007199254740993123456789.123456",
    "0.000000000000000000000000001",
    "-9007199254740993123456789.000000",
    "0",
    "-0.000000",
    "+1.250000",
    "001.250000",
  ])("preserves balance and entry text %s exactly", (quantity) => {
    expect(parseCreditBalance({ ...BALANCE, balance: quantity }).balance).toBe(
      quantity,
    );
    expect(
      parseCreditHistory({ ...HISTORY, entries: [{ ...ENTRY, quantity }] })
        .entries[0].quantity,
    ).toBe(quantity);
  });

  it.each([
    1.25,
    null,
    undefined,
    true,
    {},
    [],
    "",
    "1e6",
    "1E-6",
    "NaN",
    "Infinity",
    "-Infinity",
    " 1",
    "1 ",
    "1\n",
    "1\r\n",
    "1\t",
    "1\u00a0",
    ".25",
    "1.",
    "--1",
    "+-1",
    "1,000",
    "₹1",
    "1_000",
    "1.2.3",
  ])("rejects malformed quantity %j in both reads", (quantity) => {
    expect(() => parseCreditBalance({ ...BALANCE, balance: quantity })).toThrow(
      ContractError,
    );
    expect(() =>
      parseCreditHistory({ ...HISTORY, entries: [{ ...ENTRY, quantity }] }),
    ).toThrow(ContractError);
  });
});

it.each(["personal", "organisation"])(
  "parses authorized empty %s responses without inventing an account",
  (account) => {
    expect(
      parseCreditBalance({ account, account_id: null, balance: "0" }),
    ).toEqual({ account, accountId: null, balance: "0" });
    expect(
      parseCreditHistory({
        account,
        account_id: null,
        entries: [],
        next_before: null,
      }),
    ).toEqual({ account, accountId: null, entries: [], nextBefore: null });
  },
);

it("preserves same-time server ordering, corrections, timestamps and pagination", () => {
  expect(
    parseCreditHistory({
      ...HISTORY,
      account: "organisation",
      entries: [
        {
          ...ENTRY,
          corrected_entry_id: CORRECTED_ID,
          created_at: "2026-10-05T09:00:00.123456Z",
        },
        {
          ...ENTRY,
          entry_id: CORRECTED_ID,
          quantity: "1.500000",
          created_at: "2026-10-05T09:00:00.123456Z",
        },
      ],
      next_before: CORRECTED_ID,
    }),
  ).toEqual({
    account: "organisation",
    accountId: ACCOUNT_ID,
    entries: [
      {
        entryId: ENTRY_ID,
        quantity: "-0.250000",
        createdAt: "2026-10-05T09:00:00.123456Z",
        correctedEntryId: CORRECTED_ID,
      },
      {
        entryId: CORRECTED_ID,
        quantity: "1.500000",
        createdAt: "2026-10-05T09:00:00.123456Z",
        correctedEntryId: null,
      },
    ],
    nextBefore: CORRECTED_ID,
  });
  expect(parseCreditBalance(BALANCE).balance).toBe("1.250000");
});

it.each([null, [], "credits", 0])(
  "rejects non-object responses %j",
  (value) => {
    expect(() => parseCreditBalance(value)).toThrow(ContractError);
    expect(() => parseCreditHistory(value)).toThrow(ContractError);
  },
);

it("requires every published field and refuses extra fields at every level", () => {
  for (const [parse, shape] of [
    [parseCreditBalance, BALANCE],
    [parseCreditHistory, HISTORY],
  ] as const) {
    for (const key of Object.keys(shape)) {
      const missing: Record<string, unknown> = { ...shape };
      delete missing[key];
      expect(() => parse(missing)).toThrow(ContractError);
    }
    expect(() => parse({ ...shape, minutes: 60 })).toThrow(ContractError);
  }
  for (const key of Object.keys(ENTRY)) {
    const missing: Record<string, unknown> = { ...ENTRY };
    delete missing[key];
    expect(() =>
      parseCreditHistory({ ...HISTORY, entries: [missing] }),
    ).toThrow(ContractError);
  }
  expect(() =>
    parseCreditHistory({
      ...HISTORY,
      entries: [{ ...ENTRY, provider: "fake" }],
    }),
  ).toThrow(ContractError);
});

it.each(["Personal", "organization", "enterprise", "", null, 1])(
  "rejects account selector %j",
  (account) => {
    expect(() => parseCreditBalance({ ...BALANCE, account })).toThrow(
      ContractError,
    );
    expect(() => parseCreditHistory({ ...HISTORY, account })).toThrow(
      ContractError,
    );
  },
);

it.each([
  "",
  "account",
  1,
  {},
  undefined,
  `${ACCOUNT_ID}\n`,
  "11111111-1111-4111-8111-11111111111g",
])("rejects invalid UUID fields %j", (id) => {
  expect(() => parseCreditBalance({ ...BALANCE, account_id: id })).toThrow(
    ContractError,
  );
  expect(() => parseCreditHistory({ ...HISTORY, account_id: id })).toThrow(
    ContractError,
  );
  expect(() => parseCreditHistory({ ...HISTORY, next_before: id })).toThrow(
    ContractError,
  );
  for (const key of ["entry_id", "corrected_entry_id"])
    expect(() =>
      parseCreditHistory({ ...HISTORY, entries: [{ ...ENTRY, [key]: id }] }),
    ).toThrow(ContractError);
});

it("requires a non-null entry UUID and a list of objects", () => {
  expect(() =>
    parseCreditHistory({ ...HISTORY, entries: [{ ...ENTRY, entry_id: null }] }),
  ).toThrow(ContractError);
  for (const entries of [null, {}, "entries", [null], [[]], [1]])
    expect(() => parseCreditHistory({ ...HISTORY, entries })).toThrow(
      ContractError,
    );
});

it.each([
  null,
  1,
  "",
  "2026-10-05",
  "2026-10-05T09:00:00",
  "2026-10-05T09:00:00+00:00",
  "2026-10-05T09:00:00z",
  "2026-10-05T09:00:00Z\n",
  "2026-02-29T09:00:00Z",
  "2026-04-31T09:00:00Z",
  "2026-13-05T09:00:00Z",
  "2026-10-00T09:00:00Z",
  "2026-10-05T24:00:00Z",
  "2026-10-05T09:60:00Z",
  "2026-10-05T09:00:60Z",
  "2026-10-05T09:00:00.Z",
])("rejects invalid UTC date-time %j", (created_at) => {
  expect(() =>
    parseCreditHistory({ ...HISTORY, entries: [{ ...ENTRY, created_at }] }),
  ).toThrow(ContractError);
});

it("accepts a leap day and keeps fractional UTC text", () => {
  const created_at = "2024-02-29T23:59:59.000001Z";
  expect(
    parseCreditHistory({ ...HISTORY, entries: [{ ...ENTRY, created_at }] })
      .entries[0].createdAt,
  ).toBe(created_at);
});
