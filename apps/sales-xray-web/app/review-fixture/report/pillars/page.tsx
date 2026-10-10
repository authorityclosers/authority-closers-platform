import { notFound } from "next/navigation";
import { PillarsPreview } from "./pillars-preview";

export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <PillarsPreview />;
}
