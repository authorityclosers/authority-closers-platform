import { Suspense } from "react";

import { ReviewFigures, ReviewFiguresSkeleton } from "../review-figures";

export default function Page() {
  return (
    <Suspense fallback={<ReviewFiguresSkeleton />}>
      <ReviewFigures />
    </Suspense>
  );
}
