"use client";

import { useEffect, useState } from "react";

import { liveBilling } from "./billing/billing-api";
import { count, money } from "./billing/money";
import { onSale, type Plan } from "./billing/contract";
import styles from "./pricing-catalogue.module.css";

const PUBLIC_PLAN_KEYS = new Set(["personal", "organisation", "enterprise"]);

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
              {monthly !== null ? (
                <div>
                  <dt>Monthly</dt>
                  <dd>
                    {money(monthly)}
                    {perSeat ? " per seat" : ""} / month
                  </dd>
                </div>
              ) : null}
              {yearly !== null ? (
                <div>
                  <dt>Yearly</dt>
                  <dd>
                    {money(yearly)}
                    {perSeat ? " per seat" : ""} / year
                  </dd>
                </div>
              ) : null}
            </dl>
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
                <li>
                  Seats:{" "}
                  {plan.seatMin === null ? "not listed" : count(plan.seatMin)}
                  {"–"}
                  {plan.seatMax === null ? "not listed" : count(plan.seatMax)}
                </li>
              ) : null}
            </ul>

            <div className={styles.topups}>
              <h3>Top-up packs</h3>
              {plan.topUpPacks.length > 0 ? (
                <ul className={styles.facts}>
                  {plan.topUpPacks.map((pack) => (
                    <li key={pack.key}>
                      {count(pack.minutes)} minutes
                      {pack.pricePaise === null
                        ? " · price not listed in the catalogue"
                        : " · " + money(pack.pricePaise)}
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
