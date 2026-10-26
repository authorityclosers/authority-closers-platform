"use client";

/**
 * /testers: three steps to join the Play closed test (owner, 26 Oct 2026:
 * testers start tomorrow; tester programme kit note 01). Public, no sign-in,
 * phone first, in English, Hindi and Marathi. The links come from
 * testers-config.ts; a step's "Done" tick is only a reminder kept on this
 * device.
 */

import { Check } from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { BrandMark } from "../shell/brand-lockup";
import { TESTERS, whatsappLink, type TestersConfig } from "./testers-config";
import { COPY, LANGS, type Lang } from "./testers-copy";
import styles from "./testers.module.css";

const LANG_KEY = "sx.testers.lang";
const DONE_KEY = "sx.testers.done";
const quiet = () => () => undefined;

function isLang(value: string | null | undefined): value is Lang {
  return value === "en" || value === "hi" || value === "mr";
}

/** ?lang= first (a shared link), then this device's choice, then the phone's language. */
function preferredLang(): Lang {
  try {
    const asked = new URLSearchParams(window.location.search).get("lang");
    if (isLang(asked)) return asked;
    const kept = localStorage.getItem(LANG_KEY);
    if (isLang(kept)) return kept;
  } catch {
    // Storage blocked: the phone's language decides.
  }
  const phone = navigator.language?.slice(0, 2);
  return isLang(phone) ? phone : "en";
}

/** The product's name never breaks at its hyphen ("Sales X-" / "Ray" at 320 px). */
function keepName(text: string): ReactNode {
  const parts = text.split("Sales X-Ray");
  return parts.flatMap((part, index) =>
    index
      ? [
          <span key={index} className={styles.name}>
            Sales X-Ray
          </span>,
          part,
        ]
      : [part],
  );
}

function readDone(): number[] {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(DONE_KEY) ?? "[]");
    return Array.isArray(kept)
      ? kept.filter((n): n is number => n === 1 || n === 2 || n === 3)
      : [];
  } catch {
    return [];
  }
}

export function TestersPage({ config = TESTERS }: { config?: TestersConfig }) {
  // The server draws English; the phone's language follows once it is here.
  const here = useSyncExternalStore(
    quiet,
    () => true,
    () => false,
  );
  const [chosen, setChosen] = useState<Lang | null>(null);
  const [ticked, setTicked] = useState<number[] | null>(null);
  const lang: Lang = chosen ?? (here ? preferredLang() : "en");
  const done = ticked ?? (here ? readDone() : []);
  const t = COPY[lang];

  useEffect(() => {
    document.documentElement.lang = lang;
    // The rest of the app is in English.
    return () => {
      document.documentElement.lang = "en";
    };
  }, [lang]);

  const choose = (next: Lang) => {
    setChosen(next);
    try {
      localStorage.setItem(LANG_KEY, next);
      const url = new URL(window.location.href);
      url.searchParams.set("lang", next);
      window.history.replaceState(window.history.state, "", url);
    } catch {
      // A choice that isn't kept still shows.
    }
  };

  const toggle = (step: number) => {
    const next = done.includes(step)
      ? done.filter((n) => n !== step)
      : [...done, step].sort((a, b) => a - b);
    setTicked(next);
    try {
      localStorage.setItem(DONE_KEY, JSON.stringify(next));
    } catch {
      // Only a reminder.
    }
  };

  // Until the group is set up, step 1 can ask for the Gmail on WhatsApp.
  const whatsapp = config.route === "whatsapp" ? config.whatsappNumber : null;
  const steps = [
    whatsapp
      ? {
          n: 1,
          title: t.gmailTitle,
          line: t.gmailLine,
          button: t.gmailButton,
          href: whatsappLink(whatsapp, t.gmailMessage),
        }
      : {
          n: 1,
          title: t.groupTitle,
          line: t.groupLine,
          button: t.groupButton,
          href: config.groupUrl,
        },
    {
      n: 2,
      title: t.optInTitle,
      line: t.optInLine,
      button: t.optInButton,
      href: config.optInUrl,
    },
    {
      n: 3,
      title: t.installTitle,
      line: t.installLine,
      button: t.installButton,
      href: config.playUrl,
    },
  ];

  return (
    <main className={styles.page} lang={lang}>
      <header className={styles.top}>
        <span className={styles.brand}>
          <BrandMark markOnly />
          Sales X-Ray
        </span>
        <div className={styles.langs} role="group" aria-label={t.language}>
          {LANGS.map((item) => (
            <button
              key={item.key}
              type="button"
              lang={item.key}
              aria-pressed={item.key === lang}
              onClick={() => choose(item.key)}
            >
              {item.name}
            </button>
          ))}
        </div>
      </header>

      <section className={styles.hero}>
        <h1>{keepName(t.title)}</h1>
        <p>{t.lead}</p>
      </section>

      <ol className={styles.steps}>
        {steps.map((step) => {
          const isDone = done.includes(step.n);
          return (
            <li
              key={step.n}
              className={styles.step}
              data-done={isDone ? "" : undefined}
            >
              <span className={styles.number} aria-hidden="true">
                {isDone ? <Check size={18} strokeWidth={2.5} /> : step.n}
              </span>
              <div className={styles.stepBody}>
                <h2>{step.title}</h2>
                <p>{keepName(step.line)}</p>
                <div className={styles.stepActions}>
                  <a
                    className={styles.primary}
                    href={step.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-step={step.n}
                  >
                    {step.button}
                  </a>
                  <button
                    type="button"
                    className={styles.doneButton}
                    aria-pressed={isDone}
                    onClick={() => toggle(step.n)}
                  >
                    <Check size={16} strokeWidth={2.25} aria-hidden="true" />
                    {t.done}
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <section className={styles.box}>
        <h2>{t.stayTitle}</h2>
        <p>{t.stayText}</p>
      </section>

      <section className={styles.box}>
        <h2>{t.rewardsTitle}</h2>
        <p>{t.rewardsText}</p>
      </section>

      <section className={styles.stuck}>
        <h2>{t.stuckTitle}</h2>
        {t.stuck.map((item) => (
          <details key={item.q}>
            <summary>{item.q}</summary>
            <p>{item.a}</p>
          </details>
        ))}
        {config.helpUrl ? (
          <p className={styles.still}>
            {t.stillStuck}{" "}
            <a href={config.helpUrl} target="_blank" rel="noopener noreferrer">
              {t.askButton}
            </a>
          </p>
        ) : null}
      </section>

      <footer className={styles.footer}>
        <p>{t.footer}</p>
        <Link href="/privacy" prefetch={false}>
          {t.privacy}
        </Link>
      </footer>
    </main>
  );
}
