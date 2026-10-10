import { Suspense } from "react";
import { CoachingRoute, CoachingSkeleton } from "./coaching-page";

export default function Page() {
  return (
    <Suspense fallback={<CoachingSkeleton />}>
      <CoachingRoute />
    </Suspense>
  );
}
