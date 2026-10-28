import { notFound } from "next/navigation";
import { PersonPreview } from "../../organisation/people/person-preview";

export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <PersonPreview />;
}
