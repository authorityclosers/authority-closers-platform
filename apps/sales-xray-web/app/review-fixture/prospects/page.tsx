import { notFound } from "next/navigation";
import { ProspectsPreview } from "./prospects-preview";
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <ProspectsPreview />;
}
