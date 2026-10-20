import { Suspense } from "react";

import { ChatsRoute } from "./chats-page";
import { ChatsSkeleton } from "./chats-skeleton";

export default function Page() {
  return (
    <Suspense fallback={<ChatsSkeleton />}>
      <ChatsRoute />
    </Suspense>
  );
}
