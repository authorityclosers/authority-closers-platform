import { AcademyLeaderboard } from "../components/academy-leaderboard";
import { LearnerShell } from "../components/site-shell";

export default function LeaderboardPage() {
  return (
    <LearnerShell current="none">
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container">
          <AcademyLeaderboard />
        </div>
      </main>
    </LearnerShell>
  );
}
