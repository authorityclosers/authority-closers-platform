"use client";

import { FileSearch, GraduationCap } from "lucide-react";
import { useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { StandaloneStudio } from "../../standalone-studio";
import { Empty, PageHeader, Panel } from "../../ui/kit";
import { useWorkspaceAccess } from "../../workspace-access";
import { PAGE } from "../coaching-copy";
import {
  guideShown,
  loadGuide,
  questionCount,
  type Guide,
} from "./guide-content";
import { GUIDE, GuideSkeleton, GuideView } from "./guide-view";
import styles from "./guide.module.css";

/** Dipak's answers inside the app frame, under Coaching (it lights Growth). */
export function GuidePage({
  load = loadGuide,
}: {
  load?: () => Promise<Guide | null>;
} = {}) {
  const access = useWorkspaceAccess();
  const [guide, setGuide] = useState<Guide | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    load().then(
      (loaded) => live && setGuide(loaded),
      () => live && setGuide(null),
    );
    return () => {
      live = false;
    };
  }, [load]);

  const ready =
    access?.status === "ready" && access.authenticated && access.context;
  const awaitingAccess = !access || access.status === "loading";
  const shown = guideShown(guide ?? null) ? guide : null;
  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      loading={awaitingAccess}
      active="coaching"
    >
      <div className={styles.root}>
        <PageHeader
          title={GUIDE.title}
          context={shown ? [questionCount(shown.questions.size)] : undefined}
          back={{ href: "/coaching", label: GUIDE.back }}
        />
        {!ready ? (
          awaitingAccess ? (
            <GuideSkeleton />
          ) : (
            <Panel title={GUIDE.title}>
              <Empty
                icon={FileSearch}
                title={
                  access.authenticated === false
                    ? PAGE.signIn
                    : PAGE.chooseWorkspace
                }
                text={PAGE.signInText}
                action={
                  access.authenticated === false
                    ? { href: "/login", label: PAGE.signInAction }
                    : undefined
                }
              />
            </Panel>
          )
        ) : guide === undefined ? (
          <GuideSkeleton />
        ) : shown ? (
          <GuideView guide={shown} />
        ) : (
          <Panel title={GUIDE.title}>
            <Empty
              icon={GraduationCap}
              title={GUIDE.waiting}
              text={GUIDE.waitingText}
              action={{ href: "/coaching", label: GUIDE.openCoaching }}
            />
          </Panel>
        )}
      </div>
    </AcquisitionShell>
  );
}

export function GuideRoute() {
  const access = useWorkspaceAccess();
  return access ? (
    <GuidePage />
  ) : (
    <StandaloneStudio>
      <GuidePage />
    </StandaloneStudio>
  );
}
