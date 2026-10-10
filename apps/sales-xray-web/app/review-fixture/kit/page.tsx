import { notFound } from "next/navigation";

import { KitGallery } from "./kit-gallery";

/** Local review of the page kit (app/ui/kit). Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <KitGallery />;
}
