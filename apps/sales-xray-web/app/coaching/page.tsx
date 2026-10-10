import { CoachingRoute } from "./coaching-page";
import { requestedSkill } from "./focus-request";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string | string[] }>;
}) {
  const query = await searchParams;
  return <CoachingRoute requestedFocus={requestedSkill(query.focus)} />;
}
