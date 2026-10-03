import type { GuideDefinition } from "./guide-registry";

export type GuideProgress = Readonly<{
  stepId: string;
  status: "active" | "skipped" | "completed";
}>;

export function guideProgressKey(userId: string, guide: GuideDefinition) {
  return `sx.guide:${encodeURIComponent(userId)}:${encodeURIComponent(guide.id)}:${encodeURIComponent(guide.version)}`;
}

/** Presentation preferences only. Stores no call, report, or access state. */
export class GuideProgressStore {
  readonly key: string;
  private value: GuideProgress;
  private listeners = new Set<() => void>();

  constructor(
    userId: string,
    private readonly guide: GuideDefinition,
  ) {
    this.key = guideProgressKey(userId, guide);
    this.value = this.read();
  }

  private read(): GuideProgress {
    const initial: GuideProgress = {
      stepId: this.guide.steps[0]?.id ?? "",
      status: "active",
    };
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
        return { stepId: parsed.stepId as string, status: parsed.status };
    } catch {
      // Storage may be disabled or corrupt; the guide still works in memory.
    }
    return initial;
  }

  getSnapshot = () => this.value;
  getServerSnapshot = () => null;

  private onStorage = (event: StorageEvent) => {
    if (event.key !== this.key && event.key !== null) return;
    const next = this.read();
    if (next.stepId === this.value.stepId && next.status === this.value.status)
      return;
    this.value = next;
    this.listeners.forEach((listener) => listener());
  };

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    if (this.listeners.size === 1)
      window.addEventListener("storage", this.onStorage);
    return () => {
      this.listeners.delete(listener);
      if (!this.listeners.size)
        window.removeEventListener("storage", this.onStorage);
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
    } catch {}
    this.listeners.forEach((listener) => listener());
  }
}
