"use client";

/**
 * Edit AC's cost register (owner, 30 Oct 2026): each cost with its vendor, amount (and the
 * currency it was charged in), cadence, category, cost centre and how it is split over the
 * products. One save is one new revision of the economics settings, checked against the
 * revision read and audited with old and new (PUT /v1/admin/economics/settings). People and
 * debt are one monthly total each, never one line per person. Pulse finance becomes the
 * source once it can be read.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { send } from "../lib/client-api";
import { Field, kitStyles } from "../ui/kit";
import {
  CADENCE_WORDS,
  CATEGORY_WORDS,
  CENTRE_WORDS,
  PRODUCT_WORDS,
  RULE_WORDS,
  type CostItem,
  type FixedItem,
} from "./economics-data";
import styles from "./economics.module.css";

export type RegisterRow = {
  key: string;
  vendor: string;
  label: string;
  category: string;
  centre: string;
  cadence: string;
  rupees: string;
  currency: string;
  original: string;
  started: string;
  ended: string;
  life: string;
  rule: string;
  product: string;
  tool: string;
  shares: Record<string, string>;
  source: string;
  evidence: string;
};

const PRODUCTS = Object.keys(PRODUCT_WORDS);

const blank = (key: string): RegisterRow => ({
  key,
  vendor: "",
  label: "",
  category: "tools",
  centre: "company",
  cadence: "monthly",
  rupees: "0",
  currency: "INR",
  original: "",
  started: "",
  ended: "",
  life: "24",
  rule: "direct",
  product: "company",
  tool: "all",
  shares: {},
  source: "invoice",
  evidence: "",
});

const fromItem = (item: CostItem): RegisterRow => {
  const rule = item.allocation;
  const shares =
    typeof rule.shares === "object" && rule.shares !== null
      ? Object.fromEntries(
          Object.entries(rule.shares as Record<string, unknown>).map(
            ([key, value]) => [key, String(value)],
          ),
        )
      : {};
  return {
    key: item.key,
    vendor: item.vendor,
    label: item.label,
    category: item.category,
    centre: item.centre,
    cadence: item.cadence,
    rupees: String(item.rupees),
    currency: item.currency,
    original: item.original === null ? "" : String(item.original),
    started: item.started ?? "",
    ended: item.ended ?? "",
    life: String(item.lifeMonths ?? 24),
    rule: String(rule.rule ?? "direct"),
    product: String(rule.product ?? "company"),
    tool: String(rule.tool ?? "all"),
    shares,
    source: item.source,
    evidence: item.evidence,
  };
};

/** The old fixed list as a first register: the agents' lines split by their work. */
const fromFixed = (item: FixedItem): RegisterRow => ({
  ...blank(item.key),
  vendor: item.label.split(/[ (]/)[0] || "Cost",
  label: item.label,
  category: item.kind === "building" ? "ai_subscriptions" : "other",
  centre: item.kind === "building" ? "agents" : "company",
  rupees: String(item.rupees),
  rule: item.kind === "building" ? "token_burn" : "direct",
  source: item.source === "invoice" ? "invoice" : "estimate",
});

const slug = (text: string, taken: Set<string>) => {
  const base =
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[^a-z]+/, "")
      .slice(0, 32) || "cost";
  let key = base.length > 1 ? base : `${base}_cost`;
  let n = 2;
  while (taken.has(key)) key = `${base}_${n++}`;
  return key;
};

function allocation(row: RegisterRow): Record<string, unknown> {
  if (row.rule === "direct") return { rule: "direct", product: row.product };
  if (row.rule === "token_burn") return { rule: "token_burn", tool: row.tool };
  if (row.rule === "fixed")
    return {
      rule: "fixed",
      shares: Object.fromEntries(
        Object.entries(row.shares)
          .filter(([, value]) => value.trim() !== "" && Number(value) > 0)
          .map(([key, value]) => [key, Number(value)]),
      ),
    };
  return { rule: row.rule };
}

/** The row as the API takes it, or the reason it can't be saved. */
export function toItem(row: RegisterRow): Record<string, unknown> | string {
  const name = row.label.trim() || row.vendor.trim() || "A cost";
  if (!row.vendor.trim() || !row.label.trim())
    return `${name}: give a vendor and an item.`;
  const amount = Number(row.rupees);
  if (row.rupees.trim() === "" || !Number.isFinite(amount) || amount < 0)
    return `${name}: the rupee amount is 0 or more.`;
  if (row.cadence === "one_time" && !row.started)
    return `${name}: a one-time cost needs the day it was bought.`;
  if (row.rule === "fixed") {
    const total = Object.values(row.shares).reduce(
      (sum, value) => sum + (Number(value) || 0),
      0,
    );
    if (Math.abs(total - 100) > 0.01)
      return `${name}: the shares add up to 100%.`;
  }
  const currency = row.currency.trim().toUpperCase() || "INR";
  const item: Record<string, unknown> = {
    key: row.key,
    vendor: row.vendor.trim(),
    label: row.label.trim(),
    category: row.category,
    centre: row.centre,
    cadence: row.cadence,
    rupees: amount,
    currency,
    allocation: allocation(row),
    source: row.source,
  };
  if (currency !== "INR" && row.original.trim() !== "")
    item.original = Number(row.original);
  if (row.started) item.started = row.started;
  if (row.ended) item.ended = row.ended;
  if (row.cadence === "one_time") item.life_months = Number(row.life) || 24;
  if (row.evidence.trim()) item.evidence = row.evidence.trim().slice(0, 200);
  return item;
}

const options = (words: Record<string, string>) =>
  Object.entries(words).map(([key, label]) => (
    <option key={key} value={key}>
      {label}
    </option>
  ));

export function CostRegisterEditor({
  revision,
  config,
  items,
  fixed,
  platformWork,
}: {
  revision: number | null;
  config: Record<string, unknown>;
  items: CostItem[];
  fixed: FixedItem[];
  platformWork: string;
}) {
  const router = useRouter();
  const [rows, setRows] = useState<RegisterRow[]>(
    items.length
      ? items.map(fromItem)
      : fixed.filter((item) => item.source !== "measured").map(fromFixed),
  );
  const [platform, setPlatform] = useState(platformWork);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  const change = (index: number, patch: Partial<RegisterRow>) =>
    setRows((current) =>
      current.map((row, at) => (at === index ? { ...row, ...patch } : row)),
    );

  async function save() {
    const checked = rows.map(toItem);
    const problem = checked.find((item) => typeof item === "string");
    if (typeof problem === "string") {
      setMessage({ ok: false, text: problem });
      return;
    }
    setBusy(true);
    setMessage(null);
    const result = await send(
      "PUT",
      "/v1/admin/economics/settings",
      {
        expected_revision: revision,
        config: {
          ...config,
          costs: checked,
          cost_rules: { platform_work: platform },
        },
        reason: reason.trim() || "Cost register edited in Admin",
      },
      null,
    );
    setBusy(false);
    if (!result.ok) {
      setMessage({ ok: false, text: result.message });
      return;
    }
    setMessage({
      ok: true,
      text: "Saved. The real month and break-even use these now.",
    });
    router.refresh();
  }

  return (
    <form
      className={styles.editor}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {rows.map((row, index) => (
        <fieldset key={row.key} className={styles.costRow}>
          <legend className={styles.srOnly}>{row.label || "New cost"}</legend>
          <Field label="Vendor">
            <input
              value={row.vendor}
              maxLength={80}
              onChange={(event) =>
                change(index, { vendor: event.target.value })
              }
            />
          </Field>
          <Field label="Item">
            <input
              value={row.label}
              maxLength={120}
              onChange={(event) => change(index, { label: event.target.value })}
            />
          </Field>
          <Field label="Category">
            <select
              value={row.category}
              onChange={(event) =>
                change(index, { category: event.target.value })
              }
            >
              {options(CATEGORY_WORDS)}
            </select>
          </Field>
          <Field label="Cost centre">
            <select
              value={row.centre}
              onChange={(event) =>
                change(index, { centre: event.target.value })
              }
            >
              {options(CENTRE_WORDS)}
            </select>
          </Field>
          <Field label="Repeats">
            <select
              value={row.cadence}
              onChange={(event) =>
                change(index, { cadence: event.target.value })
              }
            >
              {options(CADENCE_WORDS)}
            </select>
          </Field>
          <Field label="₹ each time">
            <input
              inputMode="decimal"
              value={row.rupees}
              onChange={(event) =>
                change(index, { rupees: event.target.value })
              }
            />
          </Field>
          <Field label="Paid in">
            <input
              value={row.currency}
              maxLength={3}
              onChange={(event) =>
                change(index, { currency: event.target.value })
              }
            />
          </Field>
          {row.currency.trim().toUpperCase() !== "INR" ? (
            <Field label={`${row.currency.toUpperCase() || "Original"} amount`}>
              <input
                inputMode="decimal"
                value={row.original}
                onChange={(event) =>
                  change(index, { original: event.target.value })
                }
              />
            </Field>
          ) : null}
          <Field label={row.cadence === "one_time" ? "Bought on" : "Started"}>
            <input
              type="date"
              value={row.started}
              onChange={(event) =>
                change(index, { started: event.target.value })
              }
            />
          </Field>
          {row.cadence === "one_time" ? (
            <Field label="Spread over (months)">
              <input
                inputMode="numeric"
                value={row.life}
                onChange={(event) =>
                  change(index, { life: event.target.value })
                }
              />
            </Field>
          ) : (
            <Field label="Ended">
              <input
                type="date"
                value={row.ended}
                onChange={(event) =>
                  change(index, { ended: event.target.value })
                }
              />
            </Field>
          )}
          <Field label="Split">
            <select
              value={row.rule}
              onChange={(event) => change(index, { rule: event.target.value })}
            >
              {options(RULE_WORDS)}
            </select>
          </Field>
          {row.rule === "direct" ? (
            <Field label="Product">
              <select
                value={row.product}
                onChange={(event) =>
                  change(index, { product: event.target.value })
                }
              >
                {options(PRODUCT_WORDS)}
              </select>
            </Field>
          ) : null}
          {row.rule === "token_burn" ? (
            <Field label="Agent tool">
              <select
                value={row.tool}
                onChange={(event) =>
                  change(index, { tool: event.target.value })
                }
              >
                <option value="all">Claude and Codex</option>
                <option value="claude">Claude</option>
                <option value="codex">Codex</option>
              </select>
            </Field>
          ) : null}
          {row.rule === "fixed"
            ? PRODUCTS.map((product) => (
                <Field key={product} label={`${PRODUCT_WORDS[product]} %`}>
                  <input
                    inputMode="decimal"
                    value={row.shares[product] ?? ""}
                    onChange={(event) =>
                      change(index, {
                        shares: {
                          ...row.shares,
                          [product]: event.target.value,
                        },
                      })
                    }
                  />
                </Field>
              ))
            : null}
          <Field label="From">
            <select
              value={row.source}
              onChange={(event) =>
                change(index, { source: event.target.value })
              }
            >
              <option value="invoice">Invoice</option>
              <option value="estimate">Estimate</option>
              <option value="pulse">Pulse</option>
            </select>
          </Field>
          <Field label="Evidence">
            <input
              value={row.evidence}
              maxLength={200}
              placeholder="Invoice number or email date"
              onChange={(event) =>
                change(index, { evidence: event.target.value })
              }
            />
          </Field>
          <button
            type="button"
            className={kitStyles.button}
            data-variant="ghost"
            aria-label={`Remove ${row.label || "this cost"}`}
            onClick={() =>
              setRows((current) => current.filter((_, at) => at !== index))
            }
          >
            Remove
          </button>
        </fieldset>
      ))}
      <div className={styles.editFoot}>
        <button
          type="button"
          className={kitStyles.button}
          data-variant="secondary"
          onClick={() =>
            setRows((current) => [
              ...current,
              blank(slug("cost", new Set(current.map((row) => row.key)))),
            ])
          }
        >
          Add a cost
        </button>
        <Field label="Shared platform work">
          <select
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
          >
            <option value="pro_rata">Spread over the products</option>
            <option value="company">Keep as a company cost</option>
          </select>
        </Field>
        <Field label="Why (kept in the audit log)" wide>
          <input
            value={reason}
            maxLength={200}
            placeholder="e.g. Hostinger invoice for October"
            onChange={(event) => setReason(event.target.value)}
          />
        </Field>
        <button
          type="submit"
          className={kitStyles.button}
          data-variant="primary"
          disabled={busy}
        >
          {busy ? "Saving…" : "Save the cost register"}
        </button>
        {message ? (
          <small
            className={message.ok ? styles.saved : kitStyles.fieldError}
            role={message.ok ? "status" : "alert"}
          >
            {message.text}
          </small>
        ) : null}
      </div>
    </form>
  );
}
