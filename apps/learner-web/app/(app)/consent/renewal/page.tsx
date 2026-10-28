import { isHandoffReturnPath } from "../../../lib/cross-app-handoff";
import { ScreenTitle } from "../../../shell/screen-title";
import { ConsentRenewalRuntime } from "../../../components/consent-renewal-runtime";
import {
  courseIntentHref,
  parseCourseIntent,
} from "../../../lib/course-intent";
import { ROUTES } from "../../../lib/routes";
import type { QueryValue } from "../../../lib/surface-state";

export default async function ConsentRenewalPage({
  searchParams,
}: {
  searchParams: Promise<{ course?: QueryValue; return?: QueryValue }>;
}) {
  const query = await searchParams;
  const course = parseCourseIntent(query.course);
  const returnHref = isHandoffReturnPath(query.return)
    ? query.return
    : courseIntentHref(ROUTES.learnerHome, course);
  return (
    <>
      <ScreenTitle title="Your consent" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container auth-page">
          <ConsentRenewalRuntime
            returnHref={returnHref}
            loginHref={courseIntentHref(ROUTES.login, course)}
          />
        </div>
      </main>
    </>
  );
}

export const metadata = { title: "Your consent" };
