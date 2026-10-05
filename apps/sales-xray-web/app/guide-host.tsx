"use client";

import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { GuideOverlay, type CoachTarget } from "./guide-overlay";
import { GuideProgressStore } from "./guide-progress";
import {
  eligibleGuideSteps,
  FIRST_CALL_GUIDE,
  type GuideDefinition,
} from "./guide-registry";
import { useWorkspaceAccess } from "./workspace-access";

function visibleTarget(selector: string) {
  return (
    [...document.querySelectorAll<HTMLElement>(selector)].find((element) => {
      const rect = element.getBoundingClientRect();
      return (
        !element.closest("[hidden], [inert]") &&
        getComputedStyle(element).visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0
      );
    }) ?? null
  );
}

/** E9 can supply a versioned definition to this same engine. */
export function GuideEngine({
  userId,
  isOrgOwner = false,
  guide = FIRST_CALL_GUIDE,
}: {
  userId: string;
  isOrgOwner?: boolean;
  guide?: GuideDefinition;
}) {
  return (
    <GuideSession
      key={JSON.stringify([userId, guide.id, guide.version])}
      userId={userId}
      isOrgOwner={isOrgOwner}
      guide={guide}
    />
  );
}

function GuideSession({
  userId,
  isOrgOwner,
  guide,
}: {
  userId: string;
  isOrgOwner: boolean;
  guide: GuideDefinition;
}) {
  const [store] = useState(() => new GuideProgressStore(userId, guide));
  const progress = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getServerSnapshot,
  );
  const steps = useMemo(
    () => eligibleGuideSteps(guide, isOrgOwner),
    [guide, isOrgOwner],
  );
  const index = Math.max(
    0,
    steps.findIndex((step) => step.id === progress?.stepId),
  );
  const step = steps[index];
  const [target, setTarget] = useState<CoachTarget | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const active = progress?.status === "active";

  useEffect(() => {
    if (!active || !step) return;
    let frame = 0;
    const inspect = () => {
      setModalOpen(
        Boolean(document.querySelector("dialog[open], [aria-modal='true']")),
      );
      const destination = step.advanceWhen?.find((rule) =>
        visibleTarget(rule.selector),
      );
      if (
        destination &&
        steps.some((candidate) => candidate.id === destination.stepId)
      ) {
        store.update({ stepId: destination.stepId, status: "active" });
        return;
      }
      const element = step.target ? visibleTarget(step.target) : null;
      const rect = element?.getBoundingClientRect();
      const left = rect ? Math.max(4, rect.left) : 0;
      const top = rect ? Math.max(4, rect.top) : 0;
      const right = rect ? Math.min(window.innerWidth - 4, rect.right) : 0;
      const bottom = rect ? Math.min(window.innerHeight - 4, rect.bottom) : 0;
      const next =
        rect && right > left && bottom > top
          ? { left, top, width: right - left, height: bottom - top }
          : null;
      setTarget((previous) =>
        JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
      );
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(inspect);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["hidden", "open", "aria-modal", "style", "class"],
    });
    const resize =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(schedule)
        : null;
    if (step.target) {
      const element = visibleTarget(step.target);
      if (element) resize?.observe(element);
    }
    window.addEventListener("resize", schedule);
    document.addEventListener("scroll", schedule, true);
    inspect();
    return () => {
      observer.disconnect();
      resize?.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("scroll", schedule, true);
    };
    // The registry is immutable. Eligibility is recalculated on workspace changes.
  }, [active, step, store, steps]);

  // Owner, 5 Oct 2026: no floating launcher, and closing is not "for now".
  // A closed or finished guide stays away until the account menu turns it on.
  if (!progress || !step || !active || modalOpen) return null;
  const move = (nextIndex: number) =>
    store.update({ stepId: steps[nextIndex].id, status: "active" });
  const skip = () => store.update({ stepId: step.id, status: "skipped" });
  const finish = () => store.update({ stepId: step.id, status: "completed" });
  return (
    <GuideOverlay
      step={step}
      label={guide.label}
      index={index}
      count={steps.length}
      target={target}
      onNext={() => (index === steps.length - 1 ? finish() : move(index + 1))}
      onBack={() => move(index - 1)}
      onSkip={skip}
      onClose={skip}
    />
  );
}

export function FirstCallGuide() {
  const access = useWorkspaceAccess();
  const pathname = usePathname();
  const workspace = access?.workspaces?.find(
    (item) => item.tenant_id === access.context?.tenantId,
  );
  if (
    access?.status !== "ready" ||
    access.authenticated !== true ||
    !access.context ||
    workspace?.sales_xray_enabled === false ||
    pathname === "/account" ||
    pathname === "/organisation"
  )
    return null;
  return (
    <GuideEngine
      key={`${access.context.personId}:${FIRST_CALL_GUIDE.version}`}
      userId={access.context.personId}
      isOrgOwner={
        workspace?.kind === "organisation" && workspace.role === "owner"
      }
    />
  );
}
