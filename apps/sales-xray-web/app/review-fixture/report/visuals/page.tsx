import { notFound } from "next/navigation";

import { VisualsGallery } from "./visuals-gallery";

/** Local review of the Report's building blocks. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <VisualsGallery />;
}
