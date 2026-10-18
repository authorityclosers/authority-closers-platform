import { Suspense } from "react";

import { ReviewRoute, ReviewSkeleton } from "./review-home";

export default function Page() {
  return (
    <Suspense fallback={<ReviewSkeleton />}>
      <ReviewRoute />
    </Suspense>
  );
}
