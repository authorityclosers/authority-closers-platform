import { notFound } from "next/navigation";

import { NotificationsPreview } from "./notifications-preview";

/** Local visual review of Notifications with fictional entries. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <NotificationsPreview />;
}
