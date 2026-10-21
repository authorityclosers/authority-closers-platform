import { notFound } from "next/navigation";

import { AddSheetPreview } from "./add-sheet-preview";

/** Local visual review of the tab bar's + with fictional data. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <AddSheetPreview />;
}
