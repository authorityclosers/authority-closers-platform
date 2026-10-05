import type { GuideDefinition } from "./guide-registry";

export type GuideProgress = Readonly<{
  stepId: string;
  status: "active" | "skipped" | "completed";
}>;

export function guideProgressKey(userId: string, guide: GuideDefinition) {
  return `sx.guide:${encodeURIComponent(userId)}:${encodeURIComponent(guide.id)}:${encodeURIComponent(guide.version)}`;
}

/** Version-free "closed" mark: a closed guide stays closed across versions. */
export function guideOffKey(userId: string, guide: GuideDefinition) {
  return `sx.guide.off:${encodeURIComponent(userId)}:${encodeURIComponent(guide.id)}`;
}

/** Same-tab change signal; `storage` events only reach other tabs. */
const PROGRESS_EVENT = "sales-xray:guide-progress";

/** Presentation preferences only. Stores no call, report, or access state. */
export class GuideProgressStore {
  readonly key: string;
  private readonly offKey: string | null;
  private value: GuideProgress;
  private listeners = new Set<() => void>();

  constructor(
    userId: string,
    private readonly guide: GuideDefinition,
  ) {
    this.key = guideProgressKey(userId, guide);
    this.offKey = guide.rememberOff ? guideOffKey(userId, guide) : null;
    this.value = this.read();
  }

  private read(): GuideProgress {
    const initial: GuideProgress = {
      stepId: this.guide.steps[0]?.id ?? "",
      status: "active",
    };
    let stored: GuideProgress | null = null;
    try {
      const parsed: unknown = JSON.parse(
        localStorage.getItem(this.key) ?? "null",
      );
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "stepId" in parsed &&
        "status" in parsed &&
        this.guide.steps.some((step) => step.id === parsed.stepId) &&
        (parsed.status === "active" ||
          parsed.status === "skipped" ||
          parsed.status === "completed")
      )
        stored = { stepId: parsed.stepId as string, status: parsed.status };
      // Owner, 5 Oct 2026: once closed, the guide returns only when the
      // person turns it back on from the account menu, in any later version.
      if (
        this.offKey &&
        localStorage.getItem(this.offKey) === "1" &&
        (!stored || stored.status === "active")
      )
        return { stepId: stored?.stepId ?? initial.stepId, status: "skipped" };
    } catch {
      // Storage may be disabled or corrupt; the guide still works in memory.
    }
    return stored ?? initial;
  }

  getSnapshot = () => this.value;
  getServerSnapshot = () => null;

  private refresh = () => {
    const next = this.read();
    if (next.stepId === this.value.stepId && next.status === this.value.status)
      return;
    this.value = next;
    this.listeners.forEach((listener) => listener());
  };

  private onStorage = (event: StorageEvent) => {
    if (
      event.key === this.key ||
      event.key === this.offKey ||
      event.key === null
    )
      this.refresh();
  };

  private onChange = (event: Event) => {
    if ((event as CustomEvent<string>).detail === this.key) this.refresh();
  };

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    if (this.listeners.size === 1) {
      window.addEventListener("storage", this.onStorage);
      window.addEventListener(PROGRESS_EVENT, this.onChange);
    }
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size) {
        window.removeEventListener("storage", this.onStorage);
        window.removeEventListener(PROGRESS_EVENT, this.onChange);
      }
    };
  };

  update(value: GuideProgress) {
    if (
      value.stepId === this.value.stepId &&
      value.status === this.value.status
    )
      return;
    this.value = value;
    try {
      localStorage.setItem(this.key, JSON.stringify(value));
      if (this.offKey) {
        if (value.status === "active") localStorage.removeItem(this.offKey);
        else localStorage.setItem(this.offKey, "1");
      }
    } catch {}
    this.listeners.forEach((listener) => listener());
    // Other stores for the same guide (the account menu switch) follow along.
    window.dispatchEvent(
      new CustomEvent<string>(PROGRESS_EVENT, { detail: this.key }),
    );
  }
}
