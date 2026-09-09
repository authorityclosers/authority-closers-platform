import { notFound } from "next/navigation";
import { isPracticeUiEnabled } from "../lib/practice-availability";
import { LearnerShell } from "../components/site-shell";
import { PracticeArcade } from "../components/practice-arcade";
import {
  PracticeEngine,
  PracticeRecognition,
} from "../components/practice-engine";

// Evaluate the deployment opt-in at request time, never while building the shared image.
export const dynamic = "force-dynamic";

export default async function PracticePage({
  searchParams,
}: {
  searchParams: Promise<{
    set?: string | string[];
    attempt?: string | string[];
  }>;
}) {
  if (!isPracticeUiEnabled(process.env)) notFound();
  const { set, attempt } = await searchParams;
  if (
    (set !== undefined &&
      (typeof set !== "string" || !/^[a-z0-9-]{1,64}$/.test(set))) ||
    (attempt !== undefined &&
      (typeof attempt !== "string" ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          attempt,
        ))) ||
    (attempt !== undefined && set === undefined)
  )
    notFound();
  // Admission remains in the authenticated practice API; focused rounds do not
  // mount navigation, search or account overlays over the task.
  if (set)
    return (
      <PracticeEngine
        key={`${set}:${attempt ?? "new"}`}
        setId={set}
        attemptId={attempt}
      />
    );
  return (
    <LearnerShell current="practice">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container">
          <PracticeArcade durable recognition={<PracticeRecognition />} />
        </div>
      </main>
    </LearnerShell>
  );
}
