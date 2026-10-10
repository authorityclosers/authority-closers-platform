"use client";

import { RefreshCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

import styles from "./section-boundary.module.css";

type Props = {
  /** What the section shows, for the line it leaves: "Team calls". */
  name: string;
  children: ReactNode;
  /** The reassurance after the name; defaults to the rest being up to date. */
  note?: string;
  /** Remounts the section after a failure when this changes. */
  resetKey?: string | number | null;
};

type State = { error: Error | null; resetKey: Props["resetKey"] };

/**
 * One section that fails to render leaves one quiet line with "Try again";
 * the rest of the screen keeps working. A screen never falls over because a
 * server sent data a section did not expect.
 */
export class SectionBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  static getDerivedStateFromProps(props: Props, state: State) {
    return props.resetKey === state.resetKey
      ? null
      : { error: null, resetKey: props.resetKey };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error(`[${this.props.name}] could not be shown`, error, info);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        className={styles.failed}
        role="status"
        data-section-error={this.props.name}
      >
        <p>
          <b>{this.props.name} couldn&apos;t be shown.</b>{" "}
          {this.props.note ?? "The rest of this page is up to date."}
        </p>
        <button
          type="button"
          className={styles.retry}
          onClick={() => this.setState({ error: null })}
        >
          <RefreshCw size={13} aria-hidden="true" />
          Try again
        </button>
        {/* The dev site names the fault so it can be fixed, never in production. */}
        {process.env.NODE_ENV !== "production" ? (
          <code className={styles.detail}>
            {`${error.name}: ${error.message}`.slice(0, 240)}
          </code>
        ) : null}
      </div>
    );
  }
}
