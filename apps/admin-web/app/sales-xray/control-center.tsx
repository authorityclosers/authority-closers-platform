"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { AdminShell } from "../components/admin-shell";
import {
  loadProviderControls,
  type ProviderControlsPayload,
} from "./provider-controls";
import { SalesXrayNavigation } from "./sales-xray-navigation";
import styles from "./control-center.module.css";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; payload: ProviderControlsPayload }
  | { status: "unauthenticated" | "forbidden" | "error"; message: string };

function AccessState({
  state,
  onRetry,
}: {
  state: LoadState;
  onRetry: () => void;
}) {
  if (state.status === "loading") {
    return (
      <section className={styles.loading} role="status">
        <h2>Checking Sales Xray control access</h2>
        <p>
          The server returns control status after it verifies this admin
          session.
        </p>
      </section>
    );
  }
  if (state.status === "unauthenticated" || state.status === "forbidden") {
    return (
      <section className={styles.forbidden} role="alert">
        <h2>
          {state.status === "forbidden"
            ? "Verified AC admin account required"
            : "AC admin sign-in required"}
        </h2>
        <p>{state.message}</p>
        <div className={styles.buttonRow}>
          <Link className="button button-primary" href="/login">
            {state.status === "forbidden" ? "Check admin sign-in" : "Sign in"}
          </Link>
        </div>
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className={styles.error} role="alert">
        <h2>Sales Xray controls unavailable</h2>
        <p>{state.message}</p>
        <div className={styles.buttonRow}>
          <button
            className="button button-primary"
            type="button"
            onClick={onRetry}
          >
            Try again
          </button>
        </div>
      </section>
    );
  }
  return null;
}

export function ControlCenterPanel() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void loadProviderControls(controller.signal)
      .then((payload) => setState({ status: "ready", payload }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const reason = error instanceof Error ? error.message : "error";
        if (reason === "unauthenticated") {
          setState({
            status: "unauthenticated",
            message:
              "Sign in to your AC admin account to view Sales Xray controls.",
          });
        } else if (reason === "forbidden") {
          setState({
            status: "forbidden",
            message:
              "Verify your AC admin account to view Sales Xray controls.",
          });
        } else {
          setState({
            status: "error",
            message: "The control status could not be loaded. Try again.",
          });
        }
      });
    return () => controller.abort();
  }, [retry]);

  const accessState = (
    <AccessState state={state} onRetry={() => setRetry((value) => value + 1)} />
  );
  if (state.status !== "ready") return accessState;

  const current = state.payload.current;
  const implementedProviders = state.payload.catalog.filter(
    (provider) => provider.status === "implemented",
  ).length;
  const plannedProviders = state.payload.catalog.length - implementedProviders;
  const configuredRoutes = current?.configuration.routes.length ?? 0;
  const configuredProviders = current?.configuration.providers.length ?? 0;
  const activation = current?.activation;
  const approvedChoices = current?.activation_options.length ?? 0;
  const budgetCeiling = state.payload.approved_budget_cap_paise;
  const testerPolicy = state.payload.internal_tester_policy ?? {
    enabled: false,
    accounts: [],
    scopes: [],
    source: "hash_pinned_hosted_approval" as const,
    bundle_digest: null,
    limits_remaining_bounded: [],
  };

  return (
    <div className={styles.page}>
      <SalesXrayNavigation active="overview" />
      <section className={styles.statusPanel} role="status">
        <div>
          <h2>Your calls, coaching and provider settings.</h2>
          <p>
            Open a recording, review its report, or choose the approved setup
            for future analyses. Each call keeps its own processing history.
          </p>
          <div className={styles.buttonRow}>
            <Link className="button button-primary" href="/sales-xray/review">
              Open call inventory
            </Link>
            <Link
              className="button button-secondary"
              href="/sales-xray/settings"
            >
              Providers and models
            </Link>
          </div>
        </div>
        <span className={styles.statusValue}>
          {activation
            ? `Selected revision #${activation.revision}`
            : approvedChoices > 0
              ? "Approved setup available"
              : "Setup approval pending"}
        </span>
      </section>

      <div
        className={styles.summaryGrid}
        aria-label="Sales Xray control status"
      >
        <div className={styles.summaryCard}>
          <span>Latest saved revision</span>
          <strong>{current ? `#${current.revision}` : "None"}</strong>
          <small>{current ? current.created_at : "No saved revision"}</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Saved provider models</span>
          <strong>{configuredProviders}</strong>
          <small>in the latest saved revision</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Selected for future plans</span>
          <strong>
            {activation ? `#${activation.revision}` : "Release default"}
          </strong>
          <small>{configuredRoutes} routes in the saved configuration</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Approved budget ceiling</span>
          <strong>
            {budgetCeiling == null
              ? "Not available"
              : new Intl.NumberFormat("en-IN", {
                  style: "currency",
                  currency: "INR",
                  maximumFractionDigits: 2,
                }).format(budgetCeiling / 100)}
          </strong>
          <small>
            Shared processing limit · not spend or remaining balance
          </small>
        </div>
        <div className={styles.summaryCard}>
          <span>Internal tester access</span>
          <strong>{testerPolicy.enabled ? "Enabled" : "Disabled"}</strong>
          <small>
            {testerPolicy.enabled
              ? `${testerPolicy.accounts.length} named account${testerPolicy.accounts.length === 1 ? "" : "s"} · ${testerPolicy.scopes.length} scope${testerPolicy.scopes.length === 1 ? "" : "s"}`
              : "No hash-pinned tester exemptions"}
          </small>
        </div>
      </div>

      <div className={styles.capabilityGrid}>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Provider configuration</span>
          <h2>Choose your analysis setup</h2>
          <p>
            Save model and task settings, then select an approved revision for
            new plans. Calls already in progress keep their original setup.
          </p>
          <Link href="/sales-xray/settings">Open provider settings →</Link>
        </article>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Reports and usage</span>
          <h2>See every retained call</h2>
          <p>
            Find learner and guest recordings, check processing status and
            inspect usage. Estimates and reserved amounts remain separate from
            confirmed provider charges.
          </p>
          <Link href="/sales-xray/review#recordings-title">
            Browse calls and costs →
          </Link>
        </article>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Reviewer entrypoint</span>
          <h2>Bring your team into the review</h2>
          <p>
            Choose a saved report, invite a reviewer and collect feedback from
            sales, development or user-experience perspectives.
          </p>
          <Link href="/sales-xray/review">Open reviewer queue →</Link>
        </article>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Benchmark / test runs</span>
          <h2>Prepare your first comparison</h2>
          <p>
            Test runs are not available from Admin yet. Configure providers and
            invite reviewers while run controls are connected.
          </p>
          <Link href="/sales-xray/benchmark">See benchmark readiness →</Link>
        </article>
      </div>

      <section className={styles.gapPanel}>
        <span className={styles.eyebrow}>Configuration details</span>
        <h2>Clear settings, traceable changes</h2>
        <ul>
          <li>
            {implementedProviders} implemented catalog entries and{" "}
            {plannedProviders} planned entries. Only approved configurations can
            be selected for processing.
          </li>
          <li>
            Recipe, profile and prompt revisions select analysis behavior. They
            do not train the provider model.
          </li>
          <li>
            Secrets stay on the server. Selecting a configuration does not start
            a paid run or buy credits.
          </li>
          <li>
            Test runs are not available from Admin yet; configure providers and
            invite reviewers while run controls are connected.
          </li>
        </ul>
      </section>
    </div>
  );
}

export function SalesXrayControlCenter() {
  return (
    <AdminShell
      active="sales-xray"
      surface="operations"
      eyebrow="Conversation intelligence / control center"
      title="Sales Xray control center"
      description="Review setup, manage provider settings, and enter human review."
    >
      <ControlCenterPanel />
    </AdminShell>
  );
}
