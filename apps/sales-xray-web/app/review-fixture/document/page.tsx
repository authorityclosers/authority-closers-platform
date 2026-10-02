import { notFound } from "next/navigation";
import { DocumentPreview } from "./document-preview";

/** Fictional document QA only; this route is absent from production. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <DocumentPreview />;
}
