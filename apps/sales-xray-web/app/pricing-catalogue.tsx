"use client";

import { useEffect, useState } from "react";

import { liveBilling } from "./billing/billing-api";
import { count, money } from "./billing/money";
import { onSale, type Plan } from "./billing/contract";
import styles from "./pricing-catalogue.module.css";

const PUBLIC_PLAN_KEYS = new Set(["personal", "organisation", "enterprise"]);

// Owner pricing decision, 3 Oct (AUT-723): Personal prices include GST;
// Organisation and Enterprise prices are per seat, plus GST.
const GST_NOTE: Record<string, string> = {
  personal: " (GST included)",
  organisation: " + GST",
  enterprise: " + GST",
};

// CEO decision on AUT-723: features beyond the catalogue facts that work today.
const PLAN_INCLUDES: Record<string, string> = {
  enterprise:
    "Everything in Organisation, plus priority support and an onboarding session for your team.",
};

function seatRange(min: number | null, max: number | null): string {
  if (min !== null && max === null) return count(min) + " or more";
  if (min !== null && min === max) return count(min);
  return (
    (min === null ? "not listed" : count(min)) +
    "–" +
    (max === null ? "not listed" : count(max))
  );
}

type CatalogueState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; plans: Plan[] };

export function PricingCatalogue({ initialPlans }: { initialPlans?: Plan[] }) {
  const [state, setState] = useState<CatalogueState>(() =>
    initialPlans === undefined
      ? { status: "loading" }
      : { status: "ready", plans: initialPlans },
  );

  useEffect(() => {
    if (initialPlans !== undefined) return;
    const controller = new AbortController();
    liveBilling
      .readPlans(controller.signal)
      .then((plans) => setState({ status: "ready", plans }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    return () => controller.abort();
  }, [initialPlans]);

  if (state.status === "loading")
    return (
      <p className={styles.notice} role="status">
        Loading plans.
      </p>
    );
  if (state.status === "error")
    return (
      <p className={styles.notice} role="status">
        The plan catalogue is unavailable right now.
      </p>
    );

  const plans = state.plans
    .filter((plan) => PUBLIC_PLAN_KEYS.has(plan.key))
    .sort((left, right) => left.sortOrder - right.sortOrder);

  if (plans.length === 0)
    return (
      <p className={styles.notice} role="status">
        No plans are listed in the catalogue right now.
      </p>
    );

  return (
    <div className={styles.catalogue} aria-label="Plans from the catalogue">
      {plans.map((plan) => {
        const monthly = plan.prices?.monthlyPaise ?? null;
        const yearly = plan.prices?.yearlyPaise ?? null;
        const available = onSale(plan) && (monthly !== null || yearly !== null);
        const perSeat =
          plan.key === "organisation" || plan.key === "enterprise";
        const gst = GST_NOTE[plan.key] ?? "";

        return (
          <section
            className={styles.plan}
            data-plan={plan.key}
            key={plan.key}
            aria-labelledby={"plan-" + plan.key}
          >
            <header className={styles.planHeader}>
              <div>
                <h2 id={"plan-" + plan.key}>{plan.name}</h2>
                {plan.audience ? <p>{plan.audience}</p> : null}
              </div>
              <span className={styles.status}>
                {available ? "Available" : "Not currently on sale"}
              </span>
            </header>

            <dl className={styles.prices}>
              {available && monthly !== null ? (
                <div>
                  <dt>Monthly</dt>
                  <dd>
                    {money(monthly)}
                    {perSeat ? " per seat" : ""} / month{gst}
                  </dd>
                </div>
              ) : null}
              {available && yearly !== null ? (
                <div>
                  <dt>Yearly</dt>
                  <dd>
                    {money(yearly)}
                    {perSeat ? " per seat" : ""} / year{gst}
                  </dd>
                </div>
              ) : null}
            </dl>
            {PLAN_INCLUDES[plan.key] ? (
              <p className={styles.fact}>{PLAN_INCLUDES[plan.key]}</p>
            ) : null}
            {monthly === null && yearly === null ? (
              <p className={styles.fact}>
                Price is not listed in the catalogue.
              </p>
            ) : null}

            <ul className={styles.facts}>
              <li>
                Analysis minutes:{" "}
                {plan.includedMinutes === null
                  ? "not listed in the catalogue"
                  : count(plan.includedMinutes)}
                {plan.includedMinutes !== null && perSeat ? " per seat" : ""}
              </li>
              <li>
                Longest call:{" "}
                {plan.longestCallMinutes === null
                  ? "not listed in the catalogue"
                  : count(plan.longestCallMinutes) + " minutes"}
              </li>
              <li>
                Recording and report retention:{" "}
                {plan.retentionDays === null
                  ? "not listed in the catalogue"
                  : count(plan.retentionDays) + " days"}
              </li>
              {plan.seatMin !== null || plan.seatMax !== null ? (
                <li>Seats: {seatRange(plan.seatMin, plan.seatMax)}</li>
              ) : null}
            </ul>

            <div className={styles.topups}>
              <h3>Top-up packs</h3>
              {plan.topUpPacks.length > 0 ? (
                <ul className={styles.facts}>
                  {plan.topUpPacks.map((pack) => (
                    <li key={pack.key}>
                      {count(pack.minutes)} minutes
                      {!available
                        ? ""
                        : pack.pricePaise === null
                          ? " · price not listed in the catalogue"
                          : " · " + money(pack.pricePaise) + gst}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.fact}>
                  No top-up packs are listed in the catalogue.
                </p>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
