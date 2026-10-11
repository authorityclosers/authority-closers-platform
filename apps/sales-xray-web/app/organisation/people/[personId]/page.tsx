import { notFound } from "next/navigation";

import { UUID } from "../../../acquisition-client";
import { PersonView } from "../person-view";

// The static preview build needs one concrete path; real people render on
// demand and anything that isn't an id is not found.
export function generateStaticParams() {
  return [{ personId: "11111111-1111-4111-8111-111111111111" }];
}

/** One person in the organisation (owner, 11 Oct: people pages like Pulse). */
export default async function PersonPage({
  params,
}: {
  params: Promise<{ personId: string }>;
}) {
  const id = (await params).personId.toLowerCase();
  if (!UUID.test(id)) notFound();
  return <PersonView id={id} />;
}
