import type { ReactNode } from "react";

export function SkeletonLine({
  className = "",
  width,
}: {
  className?: string;
  width?: string;
}) {
  return (
    <span
      className={`skeleton-shimmer skeleton-line ${className}`}
      style={width ? { width } : undefined}
      aria-hidden="true"
    />
  );
}

export function SkeletonCard({
  children,
  className = "",
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`skeleton-card ${className}`} aria-hidden="true">
      {children}
    </div>
  );
}

export function DashboardSkeleton() {
  return (
    <div
      className="dashboard-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading dashboard"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="160px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Learning Command Center</h1>
        <SkeletonLine width="320px" className="skeleton-line--title" />
        <SkeletonLine width="420px" className="skeleton-line--subhead" />
      </div>

      <div className="dashboard-grid dashboard-grid--command">
        <SkeletonCard className="skeleton-hero-continue">
          <div className="skeleton-hero-content">
            <SkeletonLine width="120px" className="skeleton-line--tag" />
            <SkeletonLine width="75%" className="skeleton-line--heading" />
            <SkeletonLine width="90%" className="skeleton-line--text" />
            <div className="skeleton-progress-bar">
              <SkeletonLine width="100%" className="skeleton-line--bar" />
            </div>
            <div className="skeleton-actions">
              <SkeletonLine width="150px" className="skeleton-line--btn" />
              <SkeletonLine
                width="110px"
                className="skeleton-line--btn-outline"
              />
            </div>
          </div>
          <div className="skeleton-hero-media" />
        </SkeletonCard>

        <SkeletonCard className="skeleton-todays-plan">
          <SkeletonLine width="130px" className="skeleton-line--heading" />
          <div className="skeleton-plan-rows">
            {[1, 2, 3].map((item) => (
              <div key={item} className="skeleton-plan-row">
                <span className="skeleton-circle" />
                <div className="skeleton-plan-copy">
                  <SkeletonLine width="60%" className="skeleton-line--item" />
                  <SkeletonLine width="40%" className="skeleton-line--meta" />
                </div>
              </div>
            ))}
          </div>
        </SkeletonCard>
      </div>

      <div className="dashboard-skeleton__lower-grid" aria-hidden="true">
        {[1, 2, 3].map((card) => (
          <SkeletonCard
            key={card}
            className="dashboard-skeleton__practice-card"
          >
            <div className="dashboard-skeleton__practice-heading">
              <span className="skeleton-circle" />
              <SkeletonLine width="42%" className="skeleton-line--heading" />
            </div>
            <SkeletonLine width="86%" className="skeleton-line--text" />
            <SkeletonLine width="64%" className="skeleton-line--text" />
            <SkeletonLine width="96px" className="skeleton-line--btn" />
          </SkeletonCard>
        ))}
      </div>
      <p className="sr-only">Your learning dashboard is loading.</p>
    </div>
  );
}

export function LearningSkeleton() {
  return (
    <div
      className="learning-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading curriculum"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="140px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">My Learning</h1>
        <SkeletonLine width="360px" className="skeleton-line--title" />
        <SkeletonLine width="480px" className="skeleton-line--subhead" />
      </div>

      <div className="learning-collection-skeleton__toolbar" aria-hidden="true">
        {[1, 2, 3, 4].map((tab) => (
          <SkeletonLine
            key={tab}
            width={tab === 1 ? "92px" : "78px"}
            className="skeleton-line--tab"
          />
        ))}
      </div>

      <div className="learning-collection-skeleton__grid">
        {[1, 2, 3].map((course) => (
          <SkeletonCard
            key={course}
            className="learning-collection-skeleton__card"
          >
            <div className="learning-collection-skeleton__media" />
            <div className="learning-collection-skeleton__body">
              <SkeletonLine width="72px" className="skeleton-line--tag" />
              <SkeletonLine width="88%" className="skeleton-line--heading" />
              <SkeletonLine width="96%" className="skeleton-line--text" />
              <SkeletonLine width="78%" className="skeleton-line--text" />
              <div className="skeleton-progress-bar">
                <SkeletonLine width="100%" className="skeleton-line--bar" />
              </div>
              <SkeletonLine width="100%" className="skeleton-line--btn" />
            </div>
          </SkeletonCard>
        ))}
      </div>
      <p className="sr-only">Your learning journey is loading.</p>
    </div>
  );
}

export function DiscoverSkeleton() {
  return (
    <div
      className="discover-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading catalog"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="140px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Discover Programs</h1>
        <SkeletonLine width="280px" className="skeleton-line--title" />
        <SkeletonLine width="400px" className="skeleton-line--subhead" />
      </div>

      <div className="discover-grid">
        {[1, 2, 3].map((card) => (
          <SkeletonCard key={card} className="skeleton-discover-card">
            <div className="skeleton-card-media" />
            <div className="skeleton-card-body">
              <SkeletonLine width="80px" className="skeleton-line--tag" />
              <SkeletonLine width="85%" className="skeleton-line--heading" />
              <SkeletonLine width="95%" className="skeleton-line--text" />
              <SkeletonLine width="120px" className="skeleton-line--btn" />
            </div>
          </SkeletonCard>
        ))}
      </div>
      <p className="sr-only">The course catalog is loading.</p>
    </div>
  );
}

export function ProfileSkeleton() {
  return (
    <div
      className="profile-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading profile"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="120px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Learner Profile</h1>
        <SkeletonLine width="240px" className="skeleton-line--title" />
      </div>

      <div className="profile-grid">
        <SkeletonCard className="skeleton-profile-card">
          <div className="skeleton-avatar-row">
            <span className="skeleton-avatar-circle" />
            <div>
              <SkeletonLine width="180px" className="skeleton-line--heading" />
              <SkeletonLine width="140px" className="skeleton-line--subhead" />
            </div>
          </div>
          <div className="skeleton-fact-rows">
            <SkeletonLine width="100%" className="skeleton-line--text" />
            <SkeletonLine width="100%" className="skeleton-line--text" />
          </div>
        </SkeletonCard>

        <SkeletonCard className="skeleton-setup-card">
          <SkeletonLine width="160px" className="skeleton-line--heading" />
          <div className="skeleton-fact-rows">
            <SkeletonLine width="90%" className="skeleton-line--text" />
            <SkeletonLine width="85%" className="skeleton-line--text" />
            <SkeletonLine width="75%" className="skeleton-line--text" />
          </div>
        </SkeletonCard>
      </div>
      <p className="sr-only">Your profile is loading.</p>
    </div>
  );
}

export function NotificationsSkeleton() {
  return (
    <div
      className="notifications-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading notifications"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="140px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Notifications</h1>
        <SkeletonLine width="260px" className="skeleton-line--title" />
      </div>

      <div className="skeleton-notification-list">
        {[1, 2, 3, 4].map((item) => (
          <SkeletonCard key={item} className="skeleton-notification-row">
            <span className="skeleton-circle skeleton-circle--notif" />
            <div className="skeleton-notif-copy">
              <SkeletonLine width="50%" className="skeleton-line--heading" />
              <SkeletonLine width="80%" className="skeleton-line--text" />
              <SkeletonLine width="25%" className="skeleton-line--meta" />
            </div>
          </SkeletonCard>
        ))}
      </div>
      <p className="sr-only">Your notifications are loading.</p>
    </div>
  );
}

export function ProgressSkeleton() {
  return (
    <div
      className="progress-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading progress"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="130px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Learning Progress</h1>
        <SkeletonLine width="300px" className="skeleton-line--title" />
        <SkeletonLine width="440px" className="skeleton-line--subhead" />
      </div>

      <SkeletonCard className="skeleton-progress-summary">
        <div className="skeleton-metric-row">
          <SkeletonLine width="100px" className="skeleton-line--heading" />
          <SkeletonLine width="60px" className="skeleton-line--title" />
        </div>
        <SkeletonLine width="100%" className="skeleton-line--bar" />
        <div className="skeleton-fact-rows">
          <SkeletonLine width="40%" className="skeleton-line--text" />
          <SkeletonLine width="30%" className="skeleton-line--text" />
        </div>
      </SkeletonCard>

      <div className="skeleton-module-list">
        {[1, 2].map((item) => (
          <SkeletonCard key={item} className="skeleton-module-card">
            <SkeletonLine width="140px" className="skeleton-line--tag" />
            <SkeletonLine width="65%" className="skeleton-line--heading" />
            <SkeletonLine width="80%" className="skeleton-line--text" />
          </SkeletonCard>
        ))}
      </div>
      <p className="sr-only">Your progress is loading.</p>
    </div>
  );
}

export function CalendarSkeleton() {
  return (
    <div
      className="calendar-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading calendar"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="150px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Calendar</h1>
        <SkeletonLine width="220px" className="skeleton-line--title" />
        <SkeletonLine width="440px" className="skeleton-line--subhead" />
      </div>
      <div className="calendar-period-grid">
        {[1, 2, 3].map((item) => (
          <SkeletonCard key={item} className="calendar-period-card">
            <SkeletonLine width="120px" className="skeleton-line--tag" />
            <SkeletonLine width="70%" className="skeleton-line--heading" />
            <SkeletonLine width="92%" className="skeleton-line--text" />
            <SkeletonLine width="82%" className="skeleton-line--text" />
          </SkeletonCard>
        ))}
      </div>
      <p className="sr-only">Your calendar is loading.</p>
    </div>
  );
}

export function SettingsSkeleton() {
  return (
    <div
      className="settings-route-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Loading settings"
    >
      <div className="skeleton-hero-header">
        <SkeletonLine width="120px" className="skeleton-line--eyebrow" />
        <h1 className="sr-only">Account Settings</h1>
        <SkeletonLine width="260px" className="skeleton-line--title" />
        <SkeletonLine width="430px" className="skeleton-line--subhead" />
      </div>
      <div className="settings-route-skeleton__grid">
        <SkeletonCard className="settings-route-skeleton__card">
          <SkeletonLine width="150px" className="skeleton-line--heading" />
          <div className="skeleton-fact-rows">
            <SkeletonLine width="100%" className="skeleton-line--text" />
            <SkeletonLine width="92%" className="skeleton-line--text" />
            <SkeletonLine width="74%" className="skeleton-line--text" />
          </div>
        </SkeletonCard>
        <SkeletonCard className="settings-route-skeleton__card">
          <SkeletonLine width="180px" className="skeleton-line--heading" />
          <div className="skeleton-fact-rows">
            <SkeletonLine width="100%" className="skeleton-line--text" />
            <SkeletonLine width="86%" className="skeleton-line--text" />
            <SkeletonLine width="68%" className="skeleton-line--text" />
          </div>
        </SkeletonCard>
      </div>
      <p className="sr-only">Your account settings are loading.</p>
    </div>
  );
}
