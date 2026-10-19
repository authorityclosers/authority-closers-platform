"use client";

/**
 * One setting, changed in place from All settings (owner 19 Oct: "every
 * setting changeable in one click"). An on/off setting flips in one click;
 * a choice, a number or an amount opens a small field with Save. The change
 * goes to the area's own route, with the revision read with the value, so
 * validation, audit and "changed meanwhile" stay the area's.
 */
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { keyFor, send, type Intent } from "../lib/client-api";
import { kitStyles } from "../ui/kit";
import {
  ChangeRefused,
  currentValue,
  maximumFor,
  optionsFor,
  requestBody,
  type RegistrySetting,
} from "./registry-data";
import styles from "./settings.module.css";

export function SettingControl({
  setting,
  answer,
}: {
  setting: RegistrySetting;
  answer: unknown;
}) {
  const router = useRouter();
  const now = currentValue(setting, answer);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() =>
    setting.kind === "money_paise" && typeof now === "number"
      ? String(now / 100)
      : now === undefined || now === null
        ? ""
        : String(now),
  );
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );
  const intent = useRef<Intent | null>(null);

  if (!setting.write) return null;
  const write = setting.write;

  const change = async (value: unknown) => {
    setMessage(null);
    let body: Record<string, unknown>;
    try {
      body = requestBody(setting, answer, value, reason);
    } catch (error) {
      setMessage({
        ok: false,
        text:
          error instanceof ChangeRefused
            ? error.message
            : "This change can't be made here.",
      });
      return;
    }
    intent.current = keyFor(intent.current, body);
    setBusy(true);
    const result = await send(
      write.method,
      write.path,
      body,
      write.idempotencyKey ? intent.current.key : null,
    );
    setBusy(false);
    if (!result.ok) {
      setMessage({ ok: false, text: result.message });
      return;
    }
    setOpen(false);
    setReason("");
    setMessage({ ok: true, text: "Changed" });
    router.refresh();
  };

  const feedback = message ? (
    <small
      className={message.ok ? styles.changed : kitStyles.fieldError}
      role={message.ok ? "status" : "alert"}
    >
      {message.text}
    </small>
  ) : null;

  if (setting.kind === "bool" && typeof now === "boolean") {
    const next = !now;
    const label = setting.labels?.[String(next)];
    const verb =
      setting.id === "execution.paused" ? (next ? "Pause" : "Resume") : null;
    return (
      <span className={styles.control}>
        <button
          type="button"
          className={kitStyles.button}
          data-variant="ghost"
          disabled={busy}
          aria-label={`${setting.label}: ${verb ?? `set to ${label ?? (next ? "on" : "off")}`}`}
          onClick={() => change(next)}
        >
          {busy ? "Saving…" : (verb ?? `Turn ${next ? "on" : "off"}`)}
        </button>
        {feedback}
      </span>
    );
  }

  if (!open)
    return (
      <span className={styles.control}>
        <button
          type="button"
          className={kitStyles.button}
          data-variant="ghost"
          aria-label={`Change ${setting.label}`}
          onClick={() => setOpen(true)}
        >
          Change
        </button>
        {feedback}
      </span>
    );

  const menu = setting.kind === "enum" ? optionsFor(setting, answer) : [];
  const maximum = maximumFor(setting, answer);
  const money = setting.kind === "money_paise";
  const parsed = (): unknown => {
    if (setting.kind === "enum" || setting.kind === "text") return draft;
    const number = Number(draft);
    if (!draft.trim() || !Number.isFinite(number)) return null;
    return money ? Math.round(number * 100) : Math.round(number);
  };
  const value = parsed();
  const outside =
    typeof value === "number" &&
    ((setting.minimum !== null && value < setting.minimum) ||
      (maximum !== null && value > maximum));
  const invalid = value === null || value === "" || outside;

  return (
    <form
      className={styles.control}
      onSubmit={(event) => {
        event.preventDefault();
        if (!invalid && !busy) void change(value);
      }}
    >
      {setting.kind === "enum" ? (
        <select
          aria-label={setting.label}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        >
          {menu.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          aria-label={money ? `${setting.label} in rupees` : setting.label}
          type="number"
          inputMode="numeric"
          min={
            setting.minimum === null
              ? undefined
              : money
                ? setting.minimum / 100
                : setting.minimum
          }
          max={maximum === null ? undefined : money ? maximum / 100 : maximum}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      )}
      {write.needsReason ? (
        <input
          aria-label="Why"
          placeholder="Why (required)"
          maxLength={300}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      ) : null}
      <button
        type="submit"
        className={kitStyles.button}
        data-variant="primary"
        disabled={busy || invalid || (write.needsReason && !reason.trim())}
      >
        {busy ? "Saving…" : "Save"}
      </button>
      <button
        type="button"
        className={kitStyles.button}
        data-variant="ghost"
        onClick={() => {
          setOpen(false);
          setMessage(null);
        }}
      >
        Cancel
      </button>
      {outside ? (
        <small className={kitStyles.fieldError}>
          {money ? "Between ₹" : "Between "}
          {money ? (setting.minimum ?? 0) / 100 : setting.minimum} and{" "}
          {money ? `₹${(maximum ?? 0) / 100}` : maximum}
        </small>
      ) : null}
      {feedback}
    </form>
  );
}
