"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Gauge,
  ListChecks,
  RefreshCw,
  SlidersHorizontal,
  UsersRound,
} from "lucide-react";

import {
  loadProviderControls,
  type ProviderControlsPayload,
} from "./provider-controls";
import {
  Badge,
  Button,
  Kpi,
  List,
  Panel,
  Row,
  Skeleton,
  Tiles,
  kitStyles,
} from "../ui/kit";
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
      <div className={styles.page} role="status">
        <span className={kitStyles.srOnly}>
          Checking Sales Xray control access
        </span>
        <Tiles label="Sales Xray control status">
          {[0, 1, 2, 3].map((tile) => (
            <Skeleton key={tile} height={96} />
          ))}
        </Tiles>
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
        <h2>Sales Xray controls unavailable</h2>
        <p>{state.message}</p>
        <Button onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" /> Try again
        </Button>
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

  const money = (paise: number) =>
    new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2,
    }).format(paise / 100);

  return (
    <div className={styles.page}>
      <section className={styles.lead} role="status">
        <span>
          <strong>Analysis setup for future calls</strong>
          <small>
            Choose the approved setup new analyses use. Each call keeps its own
            processing history.
          </small>
        </span>
        <Badge
          tone={activation ? "good" : approvedChoices > 0 ? "accent" : "warn"}
        >
          {activation
            ? `Selected revision #${activation.revision}`
            : approvedChoices > 0
              ? "Approved setup available"
              : "Setup approval pending"}
        </Badge>
      </section>

      <Tiles label="Sales Xray control status">
        <Kpi
          label="Latest saved revision"
          value={current ? `#${current.revision}` : "None"}
          note={current ? current.created_at : "No saved revision"}
        />
        <Kpi
          label="Saved provider models"
          value={configuredProviders}
          note="in the latest saved revision"
        />
        <Kpi
          label="Selected for future plans"
          value={activation ? `#${activation.revision}` : "Release default"}
          note={`${configuredRoutes} routes in the saved configuration`}
        />
        <Kpi
          label="Approved budget ceiling"
          value={budgetCeiling == null ? "Not available" : money(budgetCeiling)}
          note="Shared processing limit · not spend or remaining balance"
        />
        <Kpi
          label="Internal tester access"
          value={testerPolicy.enabled ? "Enabled" : "Disabled"}
          note={
            testerPolicy.enabled
              ? `${testerPolicy.accounts.length} named account${testerPolicy.accounts.length === 1 ? "" : "s"} · ${testerPolicy.scopes.length} scope${testerPolicy.scopes.length === 1 ? "" : "s"}`
              : "No hash-pinned tester exemptions"
          }
        />
      </Tiles>

      <div className={styles.columns}>
        <Panel title="Where to go">
          <List label="Sales Xray setup">
            <Row
              icon={<SlidersHorizontal size={16} aria-hidden="true" />}
              href="/sales-xray/providers?tab=providers"
              title="Providers and models"
              meta={[
                "Save model and task settings, then select an approved revision for new plans. Calls in progress keep their setup.",
              ]}
            />
            <Row
              icon={<ListChecks size={16} aria-hidden="true" />}
              href="/calls"
              title="Calls and reports"
              meta={[
                "Every retained call with its status, report and runs. Estimates stay separate from confirmed provider charges.",
              ]}
            />
            <Row
              icon={<UsersRound size={16} aria-hidden="true" />}
              href="/reviewers"
              title="Reviewers"
              meta={[
                "Invite a reviewer to a saved report for sales, developer or experience feedback.",
              ]}
            />
            <Row
              icon={<Gauge size={16} aria-hidden="true" />}
              href="/sales-xray/providers?tab=benchmark"
              title="Benchmark readiness"
              meta={["Test runs aren't available from Admin yet."]}
            />
          </List>
        </Panel>

        <Panel title="How settings work">
          <ul className={styles.facts}>
            <li>
              {implementedProviders} implemented catalog entries and{" "}
              {plannedProviders} planned entries. Only approved configurations
              can be selected for processing.
            </li>
            <li>
              Recipe, profile and prompt revisions select analysis behavior.
              They do not train the provider model.
            </li>
            <li>
              Secrets stay on the server. Selecting a configuration does not
              start a paid run or buy credits.
            </li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
