export function localReviewDate(epoch: number): string {
  const date = new Date(epoch * 1000);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function reviewDateEpoch(value: string): number {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return NaN;
  const epoch = Math.floor(new Date(value).getTime() / 1000);
  // Reject dates silently normalized by the platform, including DST gaps.
  return Number.isFinite(epoch) && localReviewDate(epoch) === value
    ? epoch
    : NaN;
}
