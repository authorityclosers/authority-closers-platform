import { Suspense } from "react";

import { ChatsRoute, ChatsSkeleton } from "./chats-page";

export default function Page() {
  return (
    <Suspense fallback={<ChatsSkeleton />}>
      <ChatsRoute />
    </Suspense>
  );
}
