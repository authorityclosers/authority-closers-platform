"use client";

import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  Flag,
  PenLine,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type ProgramCollectionResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";

const defaultApi = createLearnerApi();

type CatalogState =
  | { status: "loading" }
  | { status: "ready"; value: ProgramCollectionResponse }
  | { status: "empty" }
  | { status: "error"; error: unknown };

const METHOD_STEPS = [
  { label: "Watch", detail: "See the move", icon: Play },
  { label: "Reflect", detail: "Name the shift", icon: PenLine },
  { label: "Implement", detail: "Use it for real", icon: Wrench },
  { label: "Review", detail: "Inspect the evidence", icon: Flag },
  { label: "Improve", detail: "Make the next move", icon: Sparkles },
] as const;

function catalogErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return userFacingRequestError(
      error,
      "The published catalog could not load. Try again.",
    );
  }
  if (error instanceof TypeError) {
    return "The published catalog could not be reached. Check your connection and try again.";
  }
  return "The published catalog could not load. Try again.";
}

export function PublicCatalogHome({ api = defaultApi }: { api?: LearnerApi }) {
  const [state, setState] = useState<CatalogState>({ status: "loading" });
  const requestGenerationRef = useRef(0);

  const load = useCallback(
    (signal?: AbortSignal) => {
      const requestGeneration = ++requestGenerationRef.current;
      setState({ status: "loading" });
      void api
        .listPrograms(50, signal ? { signal } : {})
        .then((value) => {
          if (requestGeneration !== requestGenerationRef.current) return;
          setState(
            value.items.length > 0
              ? { status: "ready", value }
              : { status: "empty" },
          );
        })
        .catch((error: unknown) => {
          if (
            requestGeneration === requestGenerationRef.current &&
            !isAbortError(error)
          ) {
            setState({ status: "error", error });
          }
        });
    },
    [api],
  );
  const invalidateCurrentLoad = useCallback(() => {
    ++requestGenerationRef.current;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (!controller.signal.aborted) load(controller.signal);
    });
    return () => {
      invalidateCurrentLoad();
      controller.abort();
    };
  }, [invalidateCurrentLoad, load]);

  const offlineRead =
    state.status === "ready"
      ? getEarliestOfflineReadMetadata(state.value, state.value.items)
      : null;

  return (
    <div className="ac-public-home">
      <section className="ac-public-hero" aria-labelledby="catalog-title">
        <div className="ac-public-hero__copy">
          <div className="ac-public-kicker">
            <span aria-hidden="true" />
            Authority Closers learning
          </div>
          <h1 id="catalog-title">
            Practice what changes your <span>next conversation.</span>
          </h1>
          <p>
            A focused learning loop for sales professionals who want useful
            behavior—not another library of content they never apply.
          </p>
          <div className="ac-public-hero__actions">
            <a
              className="ac-public-button ac-public-button--primary"
              href="#published-programs"
            >
              Explore published learning
              <ArrowRight size={18} aria-hidden="true" />
            </a>
            <Link
              className="ac-public-button ac-public-button--secondary"
              href={ROUTES.login}
            >
              Sign in
            </Link>
          </div>
          <div className="ac-public-proof" aria-label="Product principles">
            <span>
              <CheckCircle2 size={17} aria-hidden="true" />
              Evidence-led practice
            </span>
            <span>
              <ShieldCheck size={17} aria-hidden="true" />
              Progress you control
            </span>
          </div>
        </div>

        <div
          className="ac-public-hero__visual"
          aria-label="Authority Closers learning experience"
        >
          <Image
            src="/media/dipak-learning-hero-v1.png"
            alt=""
            width={1672}
            height={941}
            priority
            sizes="(max-width: 760px) 100vw, 46vw"
          />
          <div className="ac-public-hero__overlay">
            <span>Core Method</span>
            <strong>Evidence-led practice</strong>
          </div>
          <div className="ac-public-hero__status">
            <span
              className="ac-public-hero__status-indicator"
              aria-hidden="true"
            />
            <span>
              <strong>Built for action</strong>
              <small>One useful move at a time</small>
            </span>
          </div>
        </div>
      </section>

      <section
        className="ac-public-method"
        id="method"
        aria-labelledby="method-title"
      >
        <div className="ac-public-section-heading">
          <div>
            <p>One repeatable learning loop</p>
            <h2 id="method-title">From insight to evidence.</h2>
          </div>
          <p className="ac-public-section-heading__copy">
            Each published module turns an idea into a concrete move you can
            inspect and improve.
          </p>
        </div>
        <ol className="ac-public-method__steps">
          {METHOD_STEPS.map((step, index) => {
            const Icon = step.icon;
            return (
              <li key={step.label}>
                <span className="ac-public-method__number">{index + 1}</span>
                <span className="ac-public-method__icon">
                  <Icon size={19} aria-hidden="true" />
                </span>
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
              </li>
            );
          })}
        </ol>
      </section>

      <section
        className="ac-public-catalog"
        id="published-programs"
        aria-labelledby="catalog-list-title"
      >
        <div className="ac-public-section-heading">
          <div>
            <p>Published now</p>
            <h2 id="catalog-list-title">Start with what is available.</h2>
          </div>
          <p className="ac-public-section-heading__copy">
            This list comes directly from the published catalog API. Nothing
            here is invented for the page.
          </p>
        </div>

        {offlineRead ? (
          <div className="offline-read-notice" role="status">
            {offlineReadNotice(offlineRead)}
          </div>
        ) : null}

        {state.status === "loading" ? (
          <div
            className="ac-public-catalog-state"
            role="status"
            aria-live="polite"
          >
            <RefreshCw
              className="ac-public-spin"
              size={20}
              aria-hidden="true"
            />
            Loading published programs…
          </div>
        ) : null}

        {state.status === "empty" ? (
          <div className="ac-public-catalog-state" role="status">
            <Eye size={22} aria-hidden="true" />
            <div>
              <strong>No program is published yet.</strong>
              <p>Return when the catalog has approved learning to show.</p>
            </div>
          </div>
        ) : null}

        {state.status === "error" ? (
          <div
            className="ac-public-catalog-state ac-public-catalog-state--error"
            role="alert"
          >
            <div>
              <strong>The catalog is temporarily unavailable.</strong>
              <p>{catalogErrorMessage(state.error)}</p>
            </div>
            <button
              className="ac-public-button ac-public-button--secondary"
              type="button"
              onClick={() => load()}
            >
              Try again
            </button>
          </div>
        ) : null}

        {state.status === "ready" ? (
          <div
            className={`ac-public-program-grid${
              state.value.items.length === 1
                ? " ac-public-program-grid--single"
                : ""
            }`}
          >
            {state.value.items.map((program, index) => {
              const isFeatured = state.value.items.length === 1;
              return (
                <article
                  className={`ac-public-program-card${
                    isFeatured ? " ac-public-program-card--featured" : ""
                  }`}
                  key={program.id}
                >
                  <div className="ac-public-program-card__image">
                    <Image
                      src={
                        index % 2 === 0
                          ? "/media/ac-module-conversation-v1.png"
                          : "/media/ac-module-presentation-v1.png"
                      }
                      alt=""
                      width={1536}
                      height={1024}
                      sizes={
                        isFeatured
                          ? "(max-width: 760px) 100vw, 380px"
                          : "(max-width: 760px) 100vw, 44vw"
                      }
                    />
                    <span>Published · Version {program.version_number}</span>
                  </div>
                  <div className="ac-public-program-card__body">
                    <p>Authority Closers program</p>
                    <h3>{program.title}</h3>
                    <div className="ac-public-program-card__meta">
                      <span className="ac-public-program-card__version">
                        Version {program.version_number}
                      </span>
                      <span className="ac-public-program-card__date">
                        Published{" "}
                        {new Date(program.published_at).toLocaleDateString()}
                      </span>
                    </div>
                    <Link
                      className="ac-public-program-card__cta"
                      href={ROUTES.programDetail(program.slug)}
                    >
                      View program <ArrowRight size={17} aria-hidden="true" />
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
    </div>
  );
}
