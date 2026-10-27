"use client";

/**
 * Settings → Selling → Calls from the company number (owner, 27 Oct 2026).
 *
 * Shows only where Sales X-Ray calls from a company number (the server says
 * `available`). Everyone sets the mobile we ring first; owners and admins turn
 * it on, set the number the lead sees, and choose which leads may be called
 * from it (those who asked to be contacted, recently). The recording notice is
 * always on; the words the lead hears are shown. No price, cost or minute count.
 */

import { PhoneCall, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import {
  readCalling,
  saveCalling,
  saveMyMobile,
  type Calling,
} from "../leads/company-call-client";
import { Button, Field, Panel, Segmented } from "../ui/kit";
import styles from "./company-calling.module.css";

type Read =
  | { status: "loading" }
  | { status: "ready"; value: Calling }
  | { status: "none" };

const WINDOWS = [
  { key: "7", label: "7 days" },
  { key: "14", label: "14 days" },
  { key: "30", label: "30 days" },
] as const;

export function CompanyCallingPanel() {
  const [read, setRead] = useState<Read>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    readCalling(controller.signal).then(
      (value) => setRead({ status: "ready", value }),
      () => {
        if (!controller.signal.aborted) setRead({ status: "none" });
      },
    );
    return () => controller.abort();
  }, []);

  // Nothing at all where the company number isn't offered (or while it loads).
  if (read.status !== "ready" || !read.value.available) return null;
  const value = read.value;
  const changed = (next: Calling) => setRead({ status: "ready", value: next });

  return (
    <Panel title="Calls from the company number" sub={value.on ? "On" : "Off"}>
      <Status value={value} />
      <MyMobile value={value} onSaved={changed} />
      {value.canManage ? <Setup value={value} onSaved={changed} /> : null}
    </Panel>
  );
}

function Status({ value }: { value: Calling }) {
  const lines: { icon: "ok" | "warn"; text: string }[] = [];
  if (value.ready)
    lines.push({
      icon: "ok",
      text: `Ready. Tap Call on a lead who asked to be contacted: we ring your phone first, then theirs. They see ${value.number ?? "the company number"}.`,
    });
  for (const blocker of value.blockers)
    lines.push({ icon: "warn", text: blocker });
  if (value.paused) lines.push({ icon: "warn", text: value.paused });
  if (value.testOnly)
    lines.push({
      icon: "warn",
      text: "This is a test site: company calls ring only the team's test phones.",
    });
  return (
    <ul className={styles.status}>
      {lines.map((line) => (
        <li key={line.text} data-tone={line.icon}>
          {line.icon === "ok" ? (
            <PhoneCall size={16} aria-hidden="true" />
          ) : (
            <TriangleAlert size={16} aria-hidden="true" />
          )}
          <span>{line.text}</span>
        </li>
      ))}
    </ul>
  );
}

function MyMobile({
  value,
  onSaved,
}: {
  value: Calling;
  onSaved: (next: Calling) => void;
}) {
  const [mobile, setMobile] = useState(value.myMobile ?? "");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setState("saving");
    setError(null);
    saveMyMobile(mobile.trim() || null).then(
      (next) => {
        setMobile(next.myMobile ?? "");
        setState("saved");
        onSaved(next);
      },
      (reason: unknown) => {
        setError(
          reason instanceof Error ? reason.message : "Not saved. Try again.",
        );
        setState("idle");
      },
    );
  };

  return (
    <form className={styles.form} onSubmit={submit}>
      <Field
        label="Your mobile"
        hint="We ring this phone first; when you pick up, we call the lead."
        error={error}
      >
        <input
          className={styles.input}
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          value={mobile}
          onChange={(event) => {
            setMobile(event.target.value);
            setState("idle");
          }}
          placeholder="98765 43210"
        />
      </Field>
      <div className={styles.actions}>
        <Button type="submit" disabled={state === "saving"}>
          {state === "saving"
            ? "Saving…"
            : state === "saved"
              ? "Saved"
              : "Save"}
        </Button>
      </div>
    </form>
  );
}

function Setup({
  value,
  onSaved,
}: {
  value: Calling;
  onSaved: (next: Calling) => void;
}) {
  const [on, setOn] = useState(value.on);
  const [number, setNumber] = useState(value.number ?? "");
  const [sources, setSources] = useState(
    value.sources.filter((source) => source.on).map((source) => source.key),
  );
  const [days, setDays] = useState(String(value.windowDays));
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const notice = value.notice ?? value.notices[0] ?? null;
  const windows = WINDOWS.some((item) => item.key === days)
    ? [...WINDOWS]
    : [...WINDOWS, { key: days, label: `${days} days` }];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setState("saving");
    setError(null);
    saveCalling({
      on,
      number: number.trim() || null,
      noticeVersion: notice?.version ?? "",
      windowDays: Number(days),
      sources,
    }).then(
      (next) => {
        setState("saved");
        onSaved(next);
      },
      (reason: unknown) => {
        setError(
          reason instanceof Error ? reason.message : "Not saved. Try again.",
        );
        setState("idle");
      },
    );
  };

  const touch = () => setState("idle");

  return (
    <form
      className={styles.form}
      onSubmit={submit}
      aria-label="Company calling setup"
    >
      <h3 className={styles.heading}>For your team (owners and admins)</h3>
      <label className={styles.switch}>
        <input
          type="checkbox"
          role="switch"
          checked={on}
          onChange={(event) => {
            setOn(event.target.checked);
            touch();
          }}
        />
        <span>
          <strong>Call leads from the company number</strong>
          <small>Call on a lead rings the seller, then the lead.</small>
        </span>
      </label>
      <Field
        label="Company number"
        hint="The number your leads see when you call."
      >
        <input
          className={styles.input}
          type="tel"
          inputMode="tel"
          value={number}
          onChange={(event) => {
            setNumber(event.target.value);
            touch();
          }}
          placeholder="020 4000 0000"
        />
      </Field>
      <fieldset className={styles.fieldset}>
        <legend>Leads who may be called from it</legend>
        <p className={styles.hint}>
          Only people who asked to be contacted. Everyone else is called from
          the seller&apos;s own phone.
        </p>
        {value.sources.map((source) => (
          <label key={source.key} className={styles.check}>
            <input
              type="checkbox"
              checked={sources.includes(source.key)}
              onChange={(event) => {
                setSources((now) =>
                  event.target.checked
                    ? [...now, source.key]
                    : now.filter((key) => key !== source.key),
                );
                touch();
              }}
            />
            <span>{source.label}</span>
          </label>
        ))}
      </fieldset>
      <div className={styles.window}>
        <span className={styles.label}>…who asked within</span>
        <Segmented
          label="Who asked within"
          items={windows}
          value={days}
          onChange={(next) => {
            setDays(next);
            touch();
          }}
        />
      </div>
      {notice ? (
        <p className={styles.notice}>
          <ShieldCheck size={16} aria-hidden="true" />
          <span>
            Before you&apos;re connected, the lead hears: &ldquo;{notice.text}
            &rdquo;
          </span>
        </p>
      ) : null}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.actions}>
        <Button type="submit" variant="primary" disabled={state === "saving"}>
          {state === "saving"
            ? "Saving…"
            : state === "saved"
              ? "Saved"
              : "Save"}
        </Button>
      </div>
    </form>
  );
}
