"use client";

import { ArrowRight, BookOpen, Compass } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createLearnerApi,
  isAbortError,
  type LearnerApi,
  type LearningResponse,
  type ProgramSummaryResponse,
} from "../lib/learner-api";
import {
  getEarliestOfflineReadMetadata,
  offlineReadNotice,
  type OfflineReadMetadata,
} from "../lib/offline-read-cache";
import { ROUTES } from "../lib/routes";
import { userFacingRequestError } from "../lib/user-facing-error";
import { hasMembershipRole } from "./membership-availability";
import { DiscoverSkeleton } from "./skeletons";

const defaultApi = createLearnerApi();
export const FREE_COURSE_SLUG = "authority-closers-free-course";

type LoadResult = "loaded" | "error" | "aborted";

function publishedDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Published date unavailable"
    : `Published ${date.toLocaleDateString()}`;
}

export async function loadDiscoverData(
  api: LearnerApi,
  signal?: AbortSignal,
  publicCatalogPreview = false,
): Promise<{
  programs: ProgramSummaryResponse[];
  learning: LearningResponse | null;
  publicCatalogPreview: boolean;
  offlineRead?: OfflineReadMetadata;
}> {
  if (publicCatalogPreview) {
    const programs = await api.listPrograms(50, { signal });
    return {
      programs: programs.items,
      learning: null,
      publicCatalogPreview: true,
      offlineRead: getEarliestOfflineReadMetadata(programs) ?? undefined,
    };
  }
  const me = await api.me({ signal });
  const programs = await api.listPrograms(50, { signal });
  let learning: LearningResponse | null = null;
  if (hasMembershipRole(me)) {
    const freeCourse = programs.items.find((p) => p.slug === FREE_COURSE_SLUG);
    if (freeCourse) {
      try {
        learning = await api.learning(freeCourse.id, undefined, { signal });
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      }
    }
  }
  return {
    programs: programs.items,
    learning,
    publicCatalogPreview: false,
    offlineRead:
      getEarliestOfflineReadMetadata(me, programs, learning) ?? undefined,
  };
}

export function DiscoverRuntime({
  api = defaultApi,
  publicCatalogPreview = false,
}: {
  api?: LearnerApi;
  publicCatalogPreview?: boolean;
}) {
  const [programs, setPrograms] = useState<ProgramSummaryResponse[]>([]);
  const [learning, setLearning] = useState<LearningResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [offlineRead, setOfflineRead] = useState<
    OfflineReadMetadata | undefined
  >();
  const generationRef = useRef(0);
  const mountedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (): Promise<LoadResult> => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const generation = ++generationRef.current;
    const isCurrent = () =>
      mountedRef.current &&
      generationRef.current === generation &&
      !controller.signal.aborted;

    setLoading(true);
    setError(null);
    setLearning(null);
    setOfflineRead(undefined);
    try {
      const result = await loadDiscoverData(
        api,
        controller.signal,
        publicCatalogPreview,
      );
      if (!isCurrent()) return "aborted";
      setPrograms(result.programs);
      setLearning(result.learning);
      setOfflineRead(result.offlineRead);
      if (!isCurrent()) return "aborted";
      return "loaded";
    } catch (err) {
      if (isAbortError(err) || !isCurrent()) return "aborted";
      setError(err);
      return "error";
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [api, publicCatalogPreview]);

  useEffect(() => {
    mountedRef.current = true;
    void Promise.resolve().then(() => {
      if (mountedRef.current) void load();
    });
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
    };
  }, [load]);

  async function handleEnroll(programVersionId: string) {
    setEnrolling(true);
    setEnrollError(null);
    try {
      await api.enrollFree(programVersionId);
      if (!mountedRef.current) return;
      const refreshResult = await load();
      if (refreshResult === "error" && mountedRef.current) {
        setError(null);
        setEnrollError(
          "Enrollment completed, but the catalog could not refresh. Your enrollment was not lost; retry the catalog read.",
        );
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setEnrollError(
        userFacingRequestError(
          err,
          "Could not enroll in the published program at this time. Please retry.",
        ),
      );
    } finally {
      if (mountedRef.current) setEnrolling(false);
    }
  }

  if (loading) return <DiscoverSkeleton />;

  if (error) {
    const is401 = error instanceof ApiError && error.status === 401;
    const is403 = error instanceof ApiError && error.status === 403;
    return (
      <div className="surface-state surface-state--error-terminal" role="alert">
        <h1>
          {is401
            ? "Sign in to view Discover"
            : is403
              ? "Catalog access is unavailable"
              : "Discover could not load"}
        </h1>
        <p>
          {is401
            ? "Your session has expired. Sign in again to view published programs."
            : is403
              ? "This account is not authorized to view the published catalog."
              : userFacingRequestError(
                  error,
                  "The catalog service is temporarily unreachable.",
                )}
        </p>
        {is401 ? (
          <Link className="button button--ink" href={ROUTES.sessionExpired}>
            Sign in again
          </Link>
        ) : (
          <button
            className="button button--outline"
            type="button"
            onClick={() => void load()}
          >
            Retry catalog
          </button>
        )}
      </div>
    );
  }

  const isEnrolled = !!learning;

  return (
    <div className="discover-view">
      <header className="discover-header" aria-labelledby="discover-title">
        <div className="learning-breadcrumbs" aria-label="Breadcrumb">
          <Link href={ROUTES.dashboard}>Dashboard</Link>
          <span aria-hidden="true">/</span>
          <span>Discover</span>
        </div>
        <h1 id="discover-title" className="discover-title">
          Discover Programs
        </h1>
        <p className="discover-subhead">
          Published programs in the Authority Closers catalog.
        </p>
      </header>

      {enrollError ? (
        <div className="alert-box alert-box--error" role="alert">
          <p>{enrollError}</p>
        </div>
      ) : null}

      {publicCatalogPreview ? (
        <div className="alert-box" role="status">
          <p>
            Local preview is showing the published staging catalog. Sign in on
            deployed staging to test enrollment, profile, and progress with
            protected data.
          </p>
        </div>
      ) : null}

      {offlineRead ? (
        <div
          className="offline-read-notice"
          id="discover-offline-read"
          role="status"
        >
          {offlineReadNotice(offlineRead)}
        </div>
      ) : null}

      {programs.length === 0 ? (
        <section
          className="card empty-notifications-card"
          aria-labelledby="empty-programs-title"
        >
          <div className="empty-icon-circle" aria-hidden="true">
            <Compass size={28} />
          </div>
          <h2 id="empty-programs-title" className="empty-title">
            No published programs are available
          </h2>
          <p className="empty-description">
            This catalog currently has no published program data.
          </p>
          <div className="empty-actions">
            <button
              className="button button--outline"
              type="button"
              onClick={() => void load()}
            >
              Retry catalog
            </button>
          </div>
        </section>
      ) : (
        <section
          className="discover-section"
          aria-labelledby="published-programs-title"
        >
          <h2 id="published-programs-title" className="section-title">
            Published Programs
          </h2>
          <div className="discover-cards-grid">
            {programs.map((program) => {
              const isFreeCourse = program.slug === FREE_COURSE_SLUG;
              const isCurrentEnrollment = isFreeCourse && isEnrolled;
              return (
                <article
                  className="card discover-program-card"
                  key={program.id}
                >
                  <div className="discover-program-card__media">
                    <div className="discover-media-badge">
                      {isFreeCourse ? "Free enrollment" : "Published program"}
                    </div>
                    <div className="discover-media-inner">
                      <strong>{program.title}</strong>
                      <span>Version {program.version_number}</span>
                    </div>
                  </div>

                  <div className="discover-program-card__body">
                    <div className="discover-card-tags">
                      <span className="card-badge card-badge--primary">
                        Published
                      </span>
                      {isFreeCourse ? (
                        <span className="card-badge card-badge--success">
                          Free
                        </span>
                      ) : null}
                    </div>
                    <h3 className="discover-card-title">{program.title}</h3>
                    <p className="discover-card-description">
                      {publishedDate(program.published_at)} · Version{" "}
                      {program.version_number}
                    </p>
                    <div className="discover-card-footer">
                      {isCurrentEnrollment && !offlineRead ? (
                        <Link
                          className="button button--cobalt button--full"
                          href={ROUTES.learning}
                        >
                          <BookOpen size={16} aria-hidden="true" /> Continue
                          learning
                        </Link>
                      ) : isCurrentEnrollment && offlineRead ? (
                        <span
                          className="button button--cobalt button--full is-disabled"
                          aria-disabled="true"
                        >
                          Reconnect to continue
                        </span>
                      ) : isFreeCourse && !publicCatalogPreview ? (
                        <button
                          className="button button--cobalt button--full"
                          type="button"
                          disabled={enrolling || Boolean(offlineRead)}
                          aria-describedby={
                            offlineRead ? "discover-offline-read" : undefined
                          }
                          onClick={() =>
                            void handleEnroll(program.program_version_id)
                          }
                        >
                          {enrolling ? "Enrolling…" : "Enroll free"}
                          <ArrowRight size={16} aria-hidden="true" />
                        </button>
                      ) : publicCatalogPreview ? (
                        <a
                          className="button button--outline button--full"
                          href="https://staging.authorityclosers.com"
                        >
                          Open staging{" "}
                          <ArrowRight size={16} aria-hidden="true" />
                        </a>
                      ) : (
                        <Link
                          className="button button--outline button--full"
                          href={ROUTES.programDetail(program.slug)}
                        >
                          View program{" "}
                          <ArrowRight size={16} aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
