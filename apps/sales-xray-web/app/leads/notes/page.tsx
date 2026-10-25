import { Suspense } from "react";

import { NotesRoute, NotesSkeleton } from "./notes-page";

export default function Page() {
  return (
    <Suspense fallback={<NotesSkeleton />}>
      <NotesRoute />
    </Suspense>
  );
}
