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

  return (
    <div className={styles.page}>
      <SalesXrayNavigation active="overview" />
      <section className={styles.statusPanel} role="status">
        <div>
          <h2>Control plane ready; execution remains off.</h2>
          <p>
            This status comes from the existing provider registry adapter.
            Saving settings creates an immutable revision; it does not contact a
            provider, spend money, or publish an official result.
          </p>
        </div>
        <span className={styles.statusValue}>execution_activated false</span>
      </section>

      <div
        className={styles.summaryGrid}
        aria-label="Sales Xray control status"
      >
        <div className={styles.summaryCard}>
          <span>Current provider revision</span>
          <strong>{current ? `#${current.revision}` : "None"}</strong>
          <small>{current ? current.created_at : "No saved revision"}</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Configured bindings</span>
          <strong>{configuredProviders}</strong>
          <small>server-held references only</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Analysis routes</span>
          <strong>{configuredRoutes}</strong>
          <small>task / recipe / profile / prompt revisions</small>
        </div>
        <div className={styles.summaryCard}>
          <span>Provider catalog</span>
          <strong>{implementedProviders} ready labels</strong>
          <small>{plannedProviders} planned labels · ₹0 ceiling</small>
        </div>
      </div>

      <div className={styles.capabilityGrid}>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Provider configuration</span>
          <h2>Manage approved references and routes</h2>
          <p>
            Select catalog providers, retain opaque approval references, and
            save a revision guarded by the server and an idempotency key.
          </p>
          <Link href="/sales-xray/settings">Open provider settings →</Link>
        </article>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Analysis parameters</span>
          <h2>Use revision identifiers safely</h2>
          <p>
            Recipe, profile, and prompt revisions choose a future approved
            configuration. They are calibration metadata, not model training
            controls.
          </p>
          <Link href="/sales-xray/settings#task-routes-title">
            Open analysis routes →
          </Link>
        </article>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Reviewer entrypoint</span>
          <h2>Assign and revoke human review</h2>
          <p>
            The existing reviewer queue uses server-authorized assignment APIs
            and keeps reviewer identity and evidence scoped to the handoff.
          </p>
          <Link href="/sales-xray/review">Open reviewer queue →</Link>
        </article>
        <article className={styles.capabilityCard}>
          <span className={styles.eyebrow}>Benchmark / test runs</span>
          <h2>Run status is intentionally unavailable</h2>
          <p>
            No hosted admin benchmark or provider-test endpoint exists, so this
            surface does not render a start-test button or invent run history.
          </p>
          <Link href="/sales-xray/benchmark">See benchmark readiness →</Link>
        </article>
      </div>

      <section className={styles.gapPanel}>
        <span className={styles.eyebrow}>Safe operating boundary</span>
        <h2>What this workspace can and cannot do</h2>
        <ul>
          <li>
            Can load and save provider configuration revisions through the
            existing admin adapter.
          </li>
          <li>
            Can select task routing and revision identifiers; it cannot change
            model weights or train a provider.
          </li>
          <li>
            Cannot accept credentials, call an external provider, auto-purchase
            credits, or activate execution.
          </li>
          <li>
            Cannot start benchmark/test runs until a separately authorized
            server-side API and evidence contract exist.
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
      description="See the server-authorized operating state, manage dormant configuration, and enter human review."
    >
      <ControlCenterPanel />
    </AdminShell>
  );
}
