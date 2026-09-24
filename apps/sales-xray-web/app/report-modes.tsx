"use client";

import {
  AudioLines,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  FileText,
  Lightbulb,
  PanelsTopLeft,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { ReportReadingProvider } from "./report-reading-context";
import styles from "./report-modes.module.css";

export type ReportPanel = {
  id: string;
  label: string;
  compactLabel?: string;
  content: ReactNode;
};

type View = "reading" | "tabs";
type Address = { view: View; section: string };
const CHANGE = "ac:report-mode-change";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const sectionIcons: Record<string, LucideIcon> = {
  overview: FileText,
  prospect: UserRound,
  moments: AudioLines,
  skills: ChartNoAxesColumnIncreasing,
  "next-call-plan": Lightbulb,
  transcript: BookOpen,
};

function SectionIcon({ id }: { id: string }) {
  const Icon = sectionIcons[id] ?? FileText;
  return <Icon className={styles.sectionIcon} aria-hidden="true" />;
}

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener(CHANGE, notify);
  return () => {
    window.removeEventListener("popstate", notify);
    window.removeEventListener(CHANGE, notify);
  };
}

function addressFromSearch(
  search: string,
  boundCallId: string,
  panels: ReportPanel[],
): Address | null {
  const query = new URLSearchParams(search);
  const calls = query.getAll("call");
  const sections = query.getAll("section");
  const views = query.getAll("view");
  if (!UUID.test(boundCallId) || calls.length !== 1 || calls[0] !== boundCallId)
    return null;
  const view: View =
    views.length === 1 && (views[0] === "reading" || views[0] === "tabs")
      ? views[0]
      : "reading";
  const section =
    sections.length === 1 && panels.some((panel) => panel.id === sections[0])
      ? sections[0]
      : panels[0]?.id;
  return section ? { view, section } : null;
}

function browserSearch() {
  return window.location.search;
}

function serverSearch() {
  return "";
}

/** Keeps all real report sections available in a bookmarkable reading or tabbed view. */
export function ReportModes({
  label = "Report sections",
  panels,
  boundCallId,
}: {
  label?: string;
  panels: ReportPanel[];
  /** Enables view and section bookmarks for this already-bound report. */
  boundCallId?: string;
}) {
  const id = useId();
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const skipBookmarkScroll = useRef(false);
  const [local, setLocal] = useState<Address>({
    view: "reading",
    section: panels[0]?.id ?? "",
  });
  const [readingSection, setReadingSection] = useState(panels[0]?.id ?? "");
  const search = useSyncExternalStore(subscribe, browserSearch, serverSearch);

  const linked = boundCallId
    ? addressFromSearch(search, boundCallId, panels)
    : null;
  const address = linked ?? local;
  const selected = panels.some((panel) => panel.id === address.section)
    ? address.section
    : panels[0]?.id;
  const view = linked?.view ?? local.view;
  const currentSection = panels.some((panel) => panel.id === readingSection)
    ? view === "tabs"
      ? selected
      : readingSection
    : selected;

  useEffect(() => {
    if (!selected) return;
    const update = () => {
      const readingLine = Math.min(180, window.innerHeight * 0.4);
      let current = panels[0]?.id ?? "";
      let foundHeading = false;
      for (const panel of panels) {
        const heading = document.getElementById(`${id}-heading-${panel.id}`);
        const bounds = heading?.getBoundingClientRect();
        if (bounds && bounds.height > 0) foundHeading = true;
        if (bounds && bounds.height > 0 && bounds.top <= readingLine)
          current = panel.id;
      }
      if (!foundHeading) return;
      setReadingSection((previous) =>
        previous === current ? previous : current,
      );
    };
    update();
    document.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [id, panels, selected]);

  useEffect(() => {
    if (!linked?.section || !new URLSearchParams(search).has("section")) return;
    if (skipBookmarkScroll.current) {
      skipBookmarkScroll.current = false;
      return;
    }
    const frame = requestAnimationFrame(() => {
      setReadingSection(linked.section);
      document
        .getElementById(`${id}-heading-${linked.section}`)
        ?.scrollIntoView?.({ block: "start" });
    });
    return () => cancelAnimationFrame(frame);
  }, [id, linked?.section, search]);

  if (!panels.length) return null;

  function navigate(section: string, nextView: View = view, focus = false) {
    if (!panels.some((panel) => panel.id === section)) return;
    if (boundCallId) {
      if (!UUID.test(boundCallId)) return;
      const current = new URL(window.location.href);
      const calls = current.searchParams.getAll("call");
      if (calls.length > 1 || (calls.length === 1 && calls[0] !== boundCallId))
        return;
      current.searchParams.set("call", boundCallId);
      current.searchParams.delete("new");
      current.searchParams.set("view", nextView);
      current.searchParams.set("section", section);
      const target = `${current.pathname}?${current.searchParams.toString()}${current.hash}`;
      const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      const changesLocation = target !== here;
      if (changesLocation)
        window.history.replaceState(window.history.state, "", target);
      skipBookmarkScroll.current = changesLocation;
      window.dispatchEvent(new Event(CHANGE));
    } else setLocal({ view: nextView, section });
    setReadingSection(section);
    if (focus) {
      requestAnimationFrame(() => {
        const heading = document.getElementById(`${id}-heading-${section}`);
        heading?.focus({ preventScroll: true });
        heading?.scrollIntoView?.({ block: "start" });
      });
    }
  }

  function navigateToReport(section: string, reviewPoint?: string) {
    navigate(section, "reading");
    requestAnimationFrame(() => {
      const target = reviewPoint
        ? Array.from(
            document.querySelectorAll<HTMLElement>("[data-review-point]"),
          ).find((element) => element.dataset.reviewPoint === reviewPoint)
        : null;
      if (target instanceof HTMLDetailsElement) target.open = true;
      const destination =
        target ?? document.getElementById(`${id}-heading-${section}`);
      destination?.focus({ preventScroll: true });
      destination?.scrollIntoView?.({ block: "start" });
    });
  }

  function changeView(nextView: View) {
    const section =
      view === "reading" && nextView === "tabs"
        ? currentSection
        : (selected ?? panels[0]?.id);
    if (section) navigate(section, nextView);
  }

  return (
    <div
      className={styles.workspace}
      data-report-modes
      data-view={view}
      data-report-section={currentSection}
    >
      <div className={styles.toolbar} role="group" aria-label={`${label} view`}>
        <button
          type="button"
          aria-pressed={view === "reading"}
          onClick={() => changeView("reading")}
        >
          <BookOpen aria-hidden="true" /> Reading
        </button>
        <button
          type="button"
          aria-pressed={view === "tabs"}
          onClick={() => changeView("tabs")}
        >
          <PanelsTopLeft aria-hidden="true" /> Tabs
        </button>
      </div>
      {view === "tabs" && (
        <nav className={styles.tabNavigation} role="tablist" aria-label={label}>
          {panels.map((panel, index) => (
            <button
              key={panel.id}
              ref={(element) => {
                tabButtons.current[index] = element;
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${panel.id}`}
              aria-controls={`${id}-section-${panel.id}`}
              aria-label={panel.label}
              aria-selected={selected === panel.id}
              tabIndex={selected === panel.id ? 0 : -1}
              onClick={() => navigate(panel.id, "tabs")}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % panels.length
                    : event.key === "ArrowLeft"
                      ? (index + panels.length - 1) % panels.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? panels.length - 1
                          : null;
                if (next === null) return;
                event.preventDefault();
                navigate(panels[next].id, "tabs");
                tabButtons.current[next]?.focus();
              }}
            >
              <SectionIcon id={panel.id} />
              <span>{panel.compactLabel ?? panel.label}</span>
            </button>
          ))}
        </nav>
      )}
      <div className={styles.layout}>
        {view === "reading" && (
          <nav className={styles.contents} aria-label={label}>
            {panels.map((panel) => (
              <a
                key={panel.id}
                href={
                  boundCallId
                    ? `?call=${encodeURIComponent(boundCallId)}&view=reading&section=${encodeURIComponent(panel.id)}`
                    : `#${id}-section-${panel.id}`
                }
                aria-current={
                  currentSection === panel.id ? "location" : undefined
                }
                aria-label={panel.label}
                title={panel.label}
                onClick={(event) => {
                  if (
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return;
                  event.preventDefault();
                  navigate(panel.id, "reading", true);
                }}
              >
                <SectionIcon id={panel.id} />
                <span className={styles.fullLabel}>{panel.label}</span>
                <span className={styles.compactLabel}>
                  {panel.compactLabel ?? panel.label}
                </span>
              </a>
            ))}
          </nav>
        )}

        <ReportReadingProvider
          reading={view === "reading"}
          navigate={navigateToReport}
        >
          <div className={styles.sections}>
            {panels.map((panel) => (
              <section
                key={panel.id}
                id={`${id}-section-${panel.id}`}
                className={styles.section}
                data-report-mode-section={panel.id}
                role={view === "tabs" ? "tabpanel" : "region"}
                aria-labelledby={
                  view === "tabs"
                    ? `${id}-tab-${panel.id}`
                    : `${id}-heading-${panel.id}`
                }
                hidden={view === "tabs" && selected !== panel.id}
                tabIndex={view === "tabs" ? 0 : -1}
              >
                <h2 id={`${id}-heading-${panel.id}`} tabIndex={-1}>
                  {panel.label}
                </h2>
                {panel.content}
              </section>
            ))}
          </div>
        </ReportReadingProvider>
      </div>
    </div>
  );
}
