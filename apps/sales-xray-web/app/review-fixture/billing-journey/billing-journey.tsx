"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { PlansPurchase } from "../../plans/plans-purchase";
import {
  fixtureBilling,
  fixtureRecording,
  seedFixtureBilling,
  setFixtureRecording,
  type FixtureSeed,
} from "../plans/fixture-billing";
import {
  FixtureBilling,
  FixtureWorkspace,
  PayPage,
  ReturnPage,
} from "../plans/plans-fixture";
import styles from "./billing-journey.module.css";

type Step = {
  key: string;
  title: string;
  shows: string;
  seed: FixtureSeed;
  screen: "plans" | "pay" | "return" | "billing" | "settings";
};

/**
 * The whole buying journey on the fictional billing server, step by step, for
 * review and for the tutorial recordings (owner, 23 Oct 2026). No money moves.
 */
export const JOURNEY: readonly Step[] = [
  {
    key: "plans",
    title: "Choose a plan",
    shows: "The plan picker. Tap Get Personal, then Review total and Pay.",
    seed: "trial",
    screen: "plans",
  },
  {
    key: "pay",
    title: "Pay on the test payment page",
    shows:
      "Stands in for the payment partner's secure page. Tap Pay (test) or simulate a failure.",
    seed: "pending",
    screen: "pay",
  },
  {
    key: "confirmed",
    title: "Payment confirmed",
    shows: "The seal, the new minutes, the receipt and the refund note.",
    seed: "paid",
    screen: "return",
  },
  {
    key: "billing",
    title: "Billing & Subscription",
    shows: "The plan, analysis time, renewal and the invoice.",
    seed: "paid",
    screen: "billing",
  },
  {
    key: "refund",
    title: "Request a refund",
    shows: "Tap Request refund, then Refund ₹2,499 in the sheet.",
    seed: "paid",
    screen: "billing",
  },
  {
    key: "refunded",
    title: "Refunded",
    shows: "The confirmation once the refund is asked for.",
    seed: "refunded",
    screen: "return",
  },
  {
    key: "refunded-billing",
    title: "Billing after the refund",
    shows: "Back on the trial; the invoice reads Refunded.",
    seed: "refunded",
    screen: "billing",
  },
  {
    key: "cancel",
    title: "Cancel renewal",
    shows: "Tap Cancel renewal, then Yes, cancel renewal.",
    seed: "paid",
    screen: "billing",
  },
  {
    key: "cancelled",
    title: "Renewal cancelled",
    shows: "Access runs to the end of the period; no renewal.",
    seed: "cancelled",
    screen: "billing",
  },
  {
    key: "plan-usage",
    title: "Settings: Plan & usage",
    shows: "The same plan, minutes and invoice inside Settings.",
    seed: "paid",
    screen: "settings",
  },
];

const SETTINGS_PATH = "/review-fixture/settings?section=plan";

// One seed per step per page load: a remount (React's development double run)
// reuses it instead of seeding twice into the same store.
let seeding: { key: string; done: Promise<string | null> } | null = null;
function seedOnce(step: Step): Promise<string | null> {
  if (seeding?.key !== step.key)
    seeding = { key: step.key, done: seedFixtureBilling(step.seed) };
  return seeding.done;
}

const noSubscription = () => () => {};

export function BillingJourney() {
  const params = useSearchParams();
  const step = JOURNEY.find((item) => item.key === params.get("step"));
  const record = params.get("recording") === "1";
  useEffect(() => {
    if (record) setFixtureRecording(true);
  }, [record]);
  return step ? <StepScreen step={step} /> : <JourneyIndex />;
}

function StepScreen({ step }: { step: Step }) {
  const router = useRouter();
  // undefined while the fictional server is being set up.
  const [orderId, setOrderId] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    void seedOnce(step).then((id) => {
      if (!live) return;
      if (step.screen === "settings") router.replace(SETTINGS_PATH);
      else setOrderId(id);
    });
    return () => {
      live = false;
    };
  }, [router, step]);
  if (orderId === undefined)
    return (
      <p className={styles.seeding} role="status">
        Setting up the fictional account…
      </p>
    );
  // data-journey-step: the step is set up and on screen (for recordings).
  return (
    <div data-journey-step={step.key} style={{ display: "contents" }}>
      {step.screen === "pay" ? (
        <PayPage orderId={orderId ?? ""} />
      ) : step.screen === "return" ? (
        <ReturnPage orderId={orderId} />
      ) : (
        <FixtureWorkspace>
          {step.screen === "plans" ? (
            <PlansPurchase client={fixtureBilling} />
          ) : (
            <FixtureBilling />
          )}
        </FixtureWorkspace>
      )}
    </div>
  );
}

function JourneyIndex() {
  const router = useRouter();
  const recording = useSyncExternalStore(
    noSubscription,
    fixtureRecording,
    () => false,
  );
  const [, rerender] = useState(0);
  // Opening a step again from here sets its account up afresh.
  useEffect(() => {
    seeding = null;
  }, []);
  return (
    <main className={styles.index}>
      <header className={styles.head}>
        <h1>Billing journey</h1>
        <p>
          Development fixture: fictional plans, orders and payments on a
          fictional server. Nothing here can take money. Each step sets the
          account up, then opens the screen.
        </p>
        <label className={styles.recording}>
          <input
            type="checkbox"
            checked={recording}
            onChange={(event) => {
              setFixtureRecording(event.target.checked);
              rerender((value) => value + 1);
            }}
          />
          Recording mode: hide the development banner
        </label>
      </header>
      <ol className={styles.steps}>
        {JOURNEY.map((step, index) => (
          <li key={step.key} className={styles.step}>
            <span className={styles.number} aria-hidden="true">
              {index + 1}
            </span>
            <div className={styles.copy}>
              <h2>{step.title}</h2>
              <p>{step.shows}</p>
              <code>/review-fixture/billing-journey?step={step.key}</code>
            </div>
            <button
              type="button"
              className={styles.open}
              onClick={() =>
                router.push(`/review-fixture/billing-journey?step=${step.key}`)
              }
            >
              Open
            </button>
          </li>
        ))}
      </ol>
    </main>
  );
}
