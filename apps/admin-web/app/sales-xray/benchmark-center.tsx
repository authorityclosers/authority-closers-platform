"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { AdminShell } from "../components/admin-shell";
import {
  loadProviderControls,
  type ProviderControlsPayload,
} from "./provider-controls";
import { SalesXrayNavigation } from "./sales-xray-navigation";
import styles from "./benchmark-center.module.css";

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
        <h2>Checking benchmark control access</h2>
        <p>
          The server returns readiness after it verifies this admin session.
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
        <Link className="button button-primary" href="/login">
          {state.status === "forbidden" ? "Check admin sign-in" : "Sign in"}
        </Link>
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className={styles.error} role="alert">
        <h2>Benchmark readiness unavailable</h2>
        <p>{state.message}</p>
        <button
          className="button button-primary"
          type="button"
          onClick={onRetry}
        >
          Try again
        </button>
      </section>
    );
  }
  return null;
}

export function BenchmarkCenterPanel() {
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
            message: "Sign in to view benchmark readiness.",
          });
        } else if (reason === "forbidden") {
          setState({
            status: "forbidden",
            message:
              "Verify your AC admin account to view benchmark readiness.",
          });
        } else {
          setState({
            status: "error",
            message: "Benchmark readiness could not be loaded. Try again.",
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
  return (
    <div className={styles.page}>
      <SalesXrayNavigation active="benchmark" />
      <section className={styles.hero}>
        <span className={styles.eyebrow}>Benchmark / test runs</span>
        <h2>
          Readiness is visible; starting a run is not yet a supported admin
          action.
        </h2>
        <p>
          The current server adapter exposes provider catalog and immutable
          configuration revisions. It does not expose a hosted benchmark-run,
          provider-probe, or test-run endpoint. This page keeps that gap
          explicit instead of presenting a button that cannot create an
          authoritative run.
        </p>
      </section>

      <section className={styles.notice} role="status">
        <h2>Current server state</h2>
        <p>
          Provider revision: {current ? `#${current.revision}` : "none saved"}.
          Paid spend ceiling: ₹0. Execution activated: false. A saved revision
          is configuration evidence only, not provider quality evidence.
        </p>
      </section>

      <section className={styles.panel}>
        <span className={styles.eyebrow}>Existing routes</span>
        <h2>What the backend actually supports</h2>
        <div className={styles.endpointList}>
          <article className={styles.endpoint}>
            <span className={styles.method}>GET / POST</span>
            <div>
              <h3>
                <code>/v1/admin/conversation/providers</code>
              </h3>
              <p>
                Read the safe catalog/current revision or save a new
                zero-paid-spend provider configuration revision.
              </p>
            </div>
          </article>
          <article className={styles.endpoint}>
            <span className={styles.method}>POST</span>
            <div>
              <h3>
                <code>/v1/admin/conversation/review-assignments</code>
              </h3>
              <p>
                Create a server-authorized human reviewer handoff. Use the
                reviewer queue for this supported action.
              </p>
            </div>
          </article>
          <article className={styles.endpoint}>
            <span className={styles.method}>POST</span>
            <div>
              <h3>
                <code>/v1/conversation/recordings/:id/analysis</code>
              </h3>
              <p>
                Start owner-consented recording analysis after a quote; this is
                not an admin benchmark runner and does not bypass consent or
                retention gates.
              </p>
            </div>
          </article>
        </div>
      </section>

      <section className={styles.panel}>
        <span className={styles.eyebrow}>
          Deferred until separately authorized
        </span>
        <h2>Absent APIs and why no control is rendered</h2>
        <ul>
          <li>
            <code>/v1/admin/conversation/benchmarks</code>,{" "}
            <code>/test-runs</code>, and <code>/providers/:id/probe</code> do
            not exist in the current HTTP composition.
          </li>
          <li>
            There is no admin CRUD API for prompt/profile parameter objects;
            route fields remain revision references in provider configuration.
          </li>
          <li>
            The private <code>approved_call_test</code> module is a supervised
            local proof runner, not a hosted worker or browser-safe endpoint.
          </li>
          <li>
            Model training, automatic scoring, paid external calls, and
            execution activation remain outside this workspace.
          </li>
        </ul>
        <div className={styles.buttonRow}>
          <Link className="button button-secondary" href="/sales-xray/settings">
            Review configuration
          </Link>
          <Link className="button button-secondary" href="/sales-xray/review">
            Open reviewer queue
          </Link>
        </div>
      </section>
    </div>
  );
}

export function BenchmarkCenter() {
  return (
    <AdminShell
      active="sales-xray"
      surface="operations"
      eyebrow="Conversation intelligence / benchmark readiness"
      title="Benchmark readiness"
      description="Inspect the exact available APIs and the boundary before any provider or test run is authorized."
    >
      <BenchmarkCenterPanel />
    </AdminShell>
  );
}
