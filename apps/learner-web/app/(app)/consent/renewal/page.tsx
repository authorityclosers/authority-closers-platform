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
  searchParams: Promise<{ course?: QueryValue }>;
}) {
  const query = await searchParams;
  const course = parseCourseIntent(query.course);
  return (
    <>
      <ScreenTitle title="Your consent" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container auth-page">
          <ConsentRenewalRuntime
            returnHref={courseIntentHref(ROUTES.learnerHome, course)}
            loginHref={courseIntentHref(ROUTES.login, course)}
          />
        </div>
      </main>
    </>
  );
}

export const metadata = { title: "Your consent" };
