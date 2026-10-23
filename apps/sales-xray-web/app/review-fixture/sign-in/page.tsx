import { notFound } from "next/navigation";

import { SignInPreview } from "./sign-in-preview";

/** The sign-in and first-run setup flow with fictional answers. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <SignInPreview />;
}
