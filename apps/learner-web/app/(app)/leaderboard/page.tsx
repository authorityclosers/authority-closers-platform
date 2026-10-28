import { ScreenTitle } from "../../shell/screen-title";
import { AcademyLeaderboard } from "../../components/academy-leaderboard";

export default function LeaderboardPage() {
  return (
    <>
      <ScreenTitle title="Leaderboard" />
      <main id="main-content" className="learner-main" tabIndex={-1}>
        <div className="page-container">
          <AcademyLeaderboard />
        </div>
      </main>
    </>
  );
}

export const metadata = { title: "Leaderboard" };
