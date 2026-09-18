import { ConsentRenewalRuntime } from "../../components/consent-renewal-runtime";
import { LearnerShell } from "../../components/site-shell";
import { courseIntentHref, parseCourseIntent } from "../../lib/course-intent";
import { ROUTES } from "../../lib/routes";
import type { QueryValue } from "../../lib/surface-state";

export default async function ConsentRenewalPage({
  searchParams,
}: {
  searchParams: Promise<{ course?: QueryValue }>;
}) {
  const query = await searchParams;
  const course = parseCourseIntent(query.course);
  return (
    <LearnerShell current="none">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container auth-page">
          <ConsentRenewalRuntime
            returnHref={courseIntentHref(ROUTES.learnerHome, course)}
            loginHref={courseIntentHref(ROUTES.login, course)}
          />
        </div>
      </main>
    </LearnerShell>
  );
}
