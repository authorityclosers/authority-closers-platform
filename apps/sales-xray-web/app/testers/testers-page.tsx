"use client";

/**
 * /testers (owner, 13 Nov 2026): testers couldn't install because nobody told
 * them, cleanly, to tap "Become a tester" with the same Google account. One
 * headline, one line, one button: sign in with Google, give the phone, role
 * and business, and wait for the team. Once the team has added the account to
 * the Play group, the same page shows Play's two steps at once. Public, phone
 * first; the first screen fits one phone view.
 */

import { Check, Clock, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";

import { BrandMark } from "../shell/brand-lockup";
import { COPY, withEmail } from "./testers-copy";
import {
  PLAY_STEPS,
  ROLES,
  SIGN_IN,
  joinTesters,
  phoneModelHint,
  readTesterMe,
  switchAccount,
  type TesterMe,
  type TesterRead,
  type TesterRole,
} from "./testers-client";
import styles from "./testers.module.css";

type Read = TesterRead | "checking";

function Begin() {
  return (
    <section className={styles.begin}>
      <a className={styles.cta} href={SIGN_IN} data-testers-cta="">
        {COPY.cta}
      </a>
      <p className={styles.note}>{COPY.ctaNote}</p>
    </section>
  );
}

function JoinForm({
  me,
  onJoined,
}: {
  me: TesterMe;
  onJoined: (me: TesterMe) => void;
}) {
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<TesterRole | null>(null);
  const [business, setBusiness] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void phoneModelHint().then((model) => {
      if (live && model) setPhone((typed) => typed || model);
    });
    return () => {
      live = false;
    };
  }, []);

  const ready =
    phone.trim().length >= 2 && role !== null && business.trim().length >= 2;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || busy || role === null) return;
    setBusy(true);
    setProblem(null);
    const result = await joinTesters({
      phone_model: phone.trim(),
      role,
      business: business.trim(),
    });
    setBusy(false);
    if (result.ok) onJoined(result.me);
    else setProblem(result.message);
  };

  return (
    <form className={styles.card} onSubmit={(event) => void submit(event)}>
      <div className={styles.account}>
        <span>
          {COPY.joiningAs} <strong>{me.email}</strong>
        </span>
        <button
          type="button"
          className={styles.link}
          onClick={() => void switchAccount()}
        >
          {COPY.notYou}
        </button>
      </div>
      <p className={styles.hint}>{COPY.playAccount}</p>
      <label className={styles.field}>
        <span>{COPY.phone}</span>
        <input
          name="phone_model"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          placeholder={COPY.phoneHint}
          maxLength={80}
          autoComplete="off"
          required
        />
      </label>
      <fieldset className={styles.roles}>
        <legend>{COPY.role}</legend>
        <div className={styles.chips}>
          {ROLES.map((item) => (
            <label
              key={item.key}
              className={styles.chip}
              data-on={role === item.key ? "" : undefined}
            >
              <input
                type="radio"
                name="role"
                value={item.key}
                checked={role === item.key}
                onChange={() => setRole(item.key)}
              />
              {item.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className={styles.field}>
        <span>{COPY.business}</span>
        <input
          name="business"
          value={business}
          onChange={(event) => setBusiness(event.target.value)}
          placeholder={COPY.businessHint}
          maxLength={120}
          autoComplete="organization"
          required
        />
      </label>
      {problem ? (
        <p className={styles.problem} role="alert">
          {problem}
        </p>
      ) : null}
      <button
        type="submit"
        className={styles.cta}
        disabled={!ready || busy}
        aria-busy={busy || undefined}
      >
        {busy ? COPY.joining : COPY.join}
      </button>
    </form>
  );
}

function Status({
  icon,
  title,
  text,
}: {
  icon: "wait" | "done";
  title: string;
  text: string;
}) {
  return (
    <section className={styles.card} role="status">
      <span className={styles.badge} data-tone={icon} aria-hidden="true">
        {icon === "done" ? (
          <Check size={20} strokeWidth={2.5} />
        ) : (
          <Clock size={20} strokeWidth={2.25} />
        )}
      </span>
      <h2>{title}</h2>
      <p>{text}</p>
    </section>
  );
}

export function PlaySteps({ email }: { email: string }) {
  const steps = [
    {
      n: 1,
      title: COPY.stepOneTitle,
      text: COPY.stepOneText,
      button: COPY.stepOneButton,
      href: PLAY_STEPS.optIn,
    },
    {
      n: 2,
      title: COPY.stepTwoTitle,
      text: COPY.stepTwoText,
      button: COPY.stepTwoButton,
      href: PLAY_STEPS.play,
    },
  ];
  return (
    <>
      <ol className={styles.steps}>
        {steps.map((step) => (
          <li key={step.n} className={styles.step}>
            <span className={styles.number} aria-hidden="true">
              {step.n}
            </span>
            <div className={styles.stepBody}>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
              <a
                className={step.n === 1 ? styles.cta : styles.secondary}
                href={step.href}
                target="_blank"
                rel="noopener noreferrer"
                data-step={step.n}
              >
                {step.button}
                <ExternalLink size={16} aria-hidden="true" />
              </a>
            </div>
          </li>
        ))}
      </ol>
      <details className={styles.help}>
        <summary>{COPY.notFoundTitle}</summary>
        <p>{withEmail(COPY.notFoundText, email)}</p>
      </details>
    </>
  );
}

function Body({
  read,
  onJoined,
}: {
  read: Read;
  onJoined: (me: TesterMe) => void;
}) {
  if (read === "checking" || read === "signed_out" || read === "unavailable")
    return <Begin />;
  if (read.state === "none") return <JoinForm me={read} onJoined={onJoined} />;
  if (read.state === "waiting")
    return (
      <Status
        icon="wait"
        title={COPY.waitingTitle}
        text={withEmail(COPY.waitingText, read.email)}
      />
    );
  if (read.state === "approved")
    return (
      <Status
        icon="done"
        title={COPY.approvedTitle}
        text={withEmail(COPY.approvedText, read.email)}
      />
    );
  if (read.state === "declined")
    return (
      <Status
        icon="wait"
        title={COPY.declinedTitle}
        text={withEmail(COPY.declinedText, read.email)}
      />
    );
  return (
    <section className={styles.card}>
      <h2>{COPY.readyTitle}</h2>
      <p>{withEmail(COPY.readyText, read.email)}</p>
      <PlaySteps email={read.email} />
    </section>
  );
}

export function TestersPage({ initial = "checking" }: { initial?: Read }) {
  const [read, setRead] = useState<Read>(initial);

  useEffect(() => {
    if (initial !== "checking") return;
    const controller = new AbortController();
    void readTesterMe(controller.signal).then((answer) => {
      if (!controller.signal.aborted) setRead(answer);
    });
    return () => controller.abort();
  }, [initial]);

  return (
    <main className={styles.page}>
      <header className={styles.top}>
        <span className={styles.brand}>
          <BrandMark markOnly />
          Sales X-Ray
        </span>
      </header>
      <div className={styles.middle}>
        <section className={styles.hero}>
          <span className={styles.eyebrow}>Early access · Android</span>
          <h1>{COPY.title}</h1>
          <p>{COPY.lead}</p>
        </section>
        <Body read={read} onJoined={setRead} />
      </div>
      <footer className={styles.footer}>
        <span>{COPY.footer}</span>
        <Link href="/privacy" prefetch={false}>
          {COPY.privacy}
        </Link>
      </footer>
    </main>
  );
}
