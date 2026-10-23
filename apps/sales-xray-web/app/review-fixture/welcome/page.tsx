import { notFound } from "next/navigation";

import { WelcomePreview } from "./welcome-preview";

/** Local visual review of /welcome with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <WelcomePreview />;
}
