export function FeatureLoading({ label }: { label: string }) {
  return (
    <p role="status" aria-live="polite" aria-busy="true">
      {label}
    </p>
  );
}
