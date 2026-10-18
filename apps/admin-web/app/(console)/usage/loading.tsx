import { Page, Skeleton, kitStyles } from "@/app/ui/kit";

/** Mirrors Usage & cost (header, tabs, filters, four tiles, one panel) so nothing moves. */
export default function UsageLoading() {
  return (
    <div role="status" aria-busy="true" aria-label="Loading">
      <Page wide>
        <div style={{ display: "grid", gap: 6 }}>
          <Skeleton width={160} height={24} />
          <Skeleton width={360} height={14} />
        </div>
        <Skeleton height={32} width="70%" />
        <Skeleton height={28} width="85%" />
        <section className={kitStyles.tiles} aria-hidden="true">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className={kitStyles.tile}>
              <Skeleton width={110} height={12} />
              <Skeleton width={90} height={28} />
              <Skeleton width={150} height={12} />
            </div>
          ))}
        </section>
        <div className={kitStyles.panel} style={{ padding: 14, gap: 12 }}>
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} height={20} width={`${92 - index * 8}%`} />
          ))}
        </div>
      </Page>
    </div>
  );
}
