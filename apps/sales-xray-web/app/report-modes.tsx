"use client";

import {
  AudioLines,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  FileText,
  Lightbulb,
  PanelsTopLeft,
  Undo2,
  UserRound,
  X,
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
/** `view: null` means nobody chose yet: the viewport default applies. */
type Address = { view: View | null; section: string };
/** Desktop report width where Sections (tabbed) is the better first view. */
const TABBED_DEFAULT_QUERY = "(min-width: 1100px)";
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
  // No explicit view: the caller applies its preferred default.
  const view: View | null =
    views.length === 1 && (views[0] === "reading" || views[0] === "tabs")
      ? views[0]
      : null;
  const section =
    sections.length === 1 && panels.some((panel) => panel.id === sections[0])
      ? sections[0]
      : panels[0]?.id;
  return section ? { view, section } : null;
}

function browserSearch() {
  return window.location.search;
}

function scrollBehavior(): ScrollBehavior {
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
}

/** Moves to a destination with motion (unless reduced) and a brief arrival cue. */
function arriveAt(destination: HTMLElement | null | undefined) {
  if (!destination) return;
  // Focus must land on the real target, even a plain container.
  if (!destination.hasAttribute("tabindex") && destination.tabIndex < 0)
    destination.setAttribute("tabindex", "-1");
  destination.focus({ preventScroll: true });
  destination.scrollIntoView?.({ block: "start", behavior: scrollBehavior() });
  destination.setAttribute("data-arrived", "true");
  window.setTimeout(() => destination.removeAttribute("data-arrived"), 1600);
}

/** Where an in-report jump started: the control, its section and its URL. */
type ReturnPoint = {
  label: string;
  element: HTMLElement;
  href: string;
  /** History entries this component pushed since the jump started. */
  pushes: number;
};

/** Brings the reader back to the exact control that started a jump. */
function restoreOrigin(point: ReturnPoint) {
  if (!point.element.isConnected) return;
  // Two frames: let a restored tab/section render and any bookmark scroll run first.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      point.element.focus({ preventScroll: true });
      point.element.scrollIntoView?.({
        block: "center",
        behavior: scrollBehavior(),
      });
    }),
  );
}

function serverSearch() {
  return "";
}

function subscribeViewport(notify: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(TABBED_DEFAULT_QUERY);
  query.addEventListener?.("change", notify);
  return () => query.removeEventListener?.("change", notify);
}

function desktopSnapshot() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(TABBED_DEFAULT_QUERY).matches
  );
}

function serverDesktopSnapshot() {
  return false;
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
    view: null,
    section: panels[0]?.id ?? "",
  });
  // Server render and hydration read "reading"; a desktop viewport then
  // prefers Tabbed unless the URL or the reader already chose a view.
  const desktop = useSyncExternalStore(
    subscribeViewport,
    desktopSnapshot,
    serverDesktopSnapshot,
  );
  const preferredView: View = desktop ? "tabs" : "reading";
  const [readingSection, setReadingSection] = useState(panels[0]?.id ?? "");
  const [returnPoint, setReturnPointState] = useState<ReturnPoint | null>(null);
  const returnRef = useRef<ReturnPoint | null>(null);
  const setReturnPoint = (point: ReturnPoint | null) => {
    returnRef.current = point;
    setReturnPointState(point);
  };
  const search = useSyncExternalStore(subscribe, browserSearch, serverSearch);

  // Browser Back to the URL where a jump started restores that exact place,
  // including an original URL that had no section at all.
  useEffect(() => {
    const onPopState = () => {
      const point = returnRef.current;
      if (!point || window.location.href !== point.href) return;
      returnRef.current = null;
      setReturnPointState(null);
      restoreOrigin(point);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const linked = boundCallId
    ? addressFromSearch(search, boundCallId, panels)
    : null;
  const address = linked ?? local;
  const selected = panels.some((panel) => panel.id === address.section)
    ? address.section
    : panels[0]?.id;
  const view: View = linked
    ? (linked.view ?? preferredView)
    : (local.view ?? preferredView);
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
        ?.scrollIntoView?.({ block: "start", behavior: scrollBehavior() });
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
      // Section jumps and tab changes are history entries, so browser Back
      // returns to the previous section; view toggles only replace the entry.
      const sectionChanges =
        current.searchParams.get("section") !==
        new URLSearchParams(window.location.search).get("section");
      if (changesLocation && sectionChanges) {
        window.history.pushState(window.history.state, "", target);
        if (returnRef.current) returnRef.current.pushes += 1;
      } else if (changesLocation)
        window.history.replaceState(window.history.state, "", target);
      skipBookmarkScroll.current = changesLocation;
      window.dispatchEvent(new Event(CHANGE));
    } else setLocal({ view: nextView, section });
    setReadingSection(section);
    if (focus) {
      requestAnimationFrame(() =>
        arriveAt(document.getElementById(`${id}-heading-${section}`)),
      );
    }
  }

  /** Remembers where a jump started so the reader can return to it. */
  function rememberOrigin() {
    const origin =
      document.activeElement instanceof HTMLElement &&
      document.activeElement !== document.body
        ? document.activeElement
        : document.getElementById(`${id}-heading-${currentSection}`);
    const originSection =
      origin
        ?.closest<HTMLElement>("[data-report-mode-section]")
        ?.getAttribute("data-report-mode-section") ?? currentSection;
    const originLabel = panels.find(
      (panel) => panel.id === originSection,
    )?.label;
    if (origin && originLabel)
      setReturnPoint({
        label: originLabel,
        element: origin,
        href: window.location.href,
        pushes: 0,
      });
  }

  function navigateToReport(section: string, reviewPoint?: string) {
    rememberOrigin();
    navigate(section);
    requestAnimationFrame(() => {
      const target = reviewPoint
        ? Array.from(
            document.querySelectorAll<HTMLElement>("[data-review-point]"),
          ).find((element) => element.dataset.reviewPoint === reviewPoint)
        : null;
      if (target instanceof HTMLDetailsElement) target.open = true;
      arriveAt(target ?? document.getElementById(`${id}-heading-${section}`));
    });
  }

  function returnToOrigin() {
    const point = returnRef.current;
    if (!point) return;
    // Exactly one entry was pushed for this jump: undo it, so the origin URL
    // (even one without a section) and browser history stay truthful. The
    // popstate listener restores focus and position.
    if (
      boundCallId &&
      point.pushes === 1 &&
      window.location.href !== point.href
    ) {
      window.history.back();
      return;
    }
    setReturnPoint(null);
    if (!point.element.isConnected) return;
    if (boundCallId && window.location.href !== point.href) {
      window.history.replaceState(window.history.state, "", point.href);
      window.dispatchEvent(new Event(CHANGE));
    } else {
      const section = point.element
        .closest<HTMLElement>("[data-report-mode-section]")
        ?.getAttribute("data-report-mode-section");
      if (section) setLocal((previous) => ({ ...previous, section }));
    }
    restoreOrigin(point);
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
      data-lx-surface="light"
      data-view={view}
      data-report-section={currentSection}
    >
      {/* One horizontal row: section tabs (Tabbed) or section links (Reading),
          with the view choice at its trailing edge. No second report sidebar. */}
      <div className={styles.navRow}>
        {view === "tabs" && (
          <nav
            className={styles.tabNavigation}
            role="tablist"
            aria-label={label}
          >
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
        <div
          className={styles.toolbar}
          role="group"
          aria-label={`${label} view`}
        >
          <button
            type="button"
            aria-pressed={view === "reading"}
            onClick={() => changeView("reading")}
          >
            <BookOpen aria-hidden="true" /> Reading view
          </button>
          <button
            type="button"
            aria-pressed={view === "tabs"}
            onClick={() => changeView("tabs")}
          >
            <PanelsTopLeft aria-hidden="true" /> Tabbed view
          </button>
        </div>
      </div>
      <div className={styles.layout}>
        <ReportReadingProvider
          reading={view === "reading"}
          inline
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
                {/* In Tabbed view the selected tab already names the section;
                    the heading stays for assistive tech and focus targets. */}
                <h2
                  id={`${id}-heading-${panel.id}`}
                  tabIndex={-1}
                  className={
                    view === "tabs" ? styles.visuallyHiddenHeading : undefined
                  }
                >
                  {panel.label}
                </h2>
                {panel.content}
              </section>
            ))}
          </div>
        </ReportReadingProvider>
      </div>
      {returnPoint && (
        <div className={styles.returnBar} data-report-return>
          <button
            type="button"
            className={styles.returnButton}
            onClick={returnToOrigin}
          >
            <Undo2 aria-hidden="true" />
            Back to {returnPoint.label}
          </button>
          <button
            type="button"
            className={styles.returnDismiss}
            aria-label="Dismiss return shortcut"
            onClick={() => setReturnPoint(null)}
          >
            <X aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
