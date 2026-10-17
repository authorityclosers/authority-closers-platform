"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Gauge, RefreshCw } from "lucide-react";

import {
  loadProviderControls,
  type ProviderControlsPayload,
} from "./provider-controls";
import { Button, Empty, Panel, Skeleton, kitStyles } from "../ui/kit";
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
      <div className={styles.page} role="status">
        <span className={kitStyles.srOnly}>
          Checking benchmark control access
        </span>
        <Skeleton height={160} />
      </div>
    );
  }
  if (state.status === "unauthenticated" || state.status === "forbidden") {
    return (
      <section className={styles.state} role="alert">
        <h2>
          {state.status === "forbidden"
            ? "Verified AC admin account required"
            : "AC admin sign-in required"}
        </h2>
        <p>{state.message}</p>
        <Link className={kitStyles.button} data-variant="primary" href="/login">
          {state.status === "forbidden" ? "Check admin sign-in" : "Sign in"}
        </Link>
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className={styles.state} role="alert">
        <h2>Benchmark readiness unavailable</h2>
        <p>{state.message}</p>
        <Button onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" /> Try again
        </Button>
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
      <Panel
        title="Benchmark and test runs"
        sub={`Provider revision ${current ? `#${current.revision}` : "none saved"} · paid spend ceiling ₹0`}
      >
        <Empty
          icon={Gauge}
          title="Prepare your first comparison"
          text="Test runs are not available from Admin yet. Configure providers and invite reviewers; run controls are being connected. Saved settings are configuration evidence only, not provider quality evidence."
          action={
            <span className={styles.actions}>
              <Link
                className={kitStyles.button}
                data-variant="primary"
                href="/sales-xray/providers?tab=providers"
              >
                Configure providers
              </Link>
              <Link
                className={kitStyles.button}
                data-variant="secondary"
                href="/reviewers"
              >
                Invite reviewers
              </Link>
            </span>
          }
        />
      </Panel>

      <Panel title="Technical notes">
        <details className={styles.details}>
          <summary>What the current service supports</summary>
          <dl className={styles.endpoints}>
            <dt>
              <span>GET / POST</span>
              <code>/v1/admin/conversation/providers</code>
            </dt>
            <dd>
              Read the safe catalog/current revision or save a new
              zero-paid-spend provider configuration revision.
            </dd>
            <dt>
              <span>POST</span>
              <code>/v1/admin/conversation/review-assignments</code>
            </dt>
            <dd>
              Create a server-authorized human reviewer handoff. Use Reviewers
              for this supported action.
            </dd>
            <dt>
              <span>POST</span>
              <code>/v1/conversation/recordings/:id/analysis</code>
            </dt>
            <dd>
              Start owner-consented recording analysis after a quote; this is
              not an admin benchmark runner and does not bypass consent or
              retention gates.
            </dd>
          </dl>
        </details>
        <details className={styles.details}>
          <summary>Why run controls are not shown</summary>
          <ul className={styles.list}>
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
              Model training, automatic scoring, paid external calls, and
              execution activation remain outside this workspace.
            </li>
          </ul>
        </details>
      </Panel>
    </div>
  );
}
