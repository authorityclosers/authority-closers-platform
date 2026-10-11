import { notFound } from "next/navigation";
import { CoachingFixture } from "./preview";

/** Local and dev visual review only; never available in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <CoachingFixture />;
}
