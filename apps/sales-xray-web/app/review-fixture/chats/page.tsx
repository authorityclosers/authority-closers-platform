import { notFound } from "next/navigation";

import { ChatsPreview } from "./chats-preview";

/** Local visual review of Chats with fictional leads. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <ChatsPreview />;
}
