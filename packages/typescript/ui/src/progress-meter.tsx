export type ProgressMeterProps = {
  value: number;
  label: string;
  detail: string;
};

/**
 * Direction A progress primitive. The caller supplies the server-backed
 * value and human-readable detail; this component only presents it.
 */
export function ProgressMeter({ value, label, detail }: ProgressMeterProps) {
  const safeValue = Math.min(100, Math.max(0, value));

  return (
    <div className="progress-meter">
      <div className="progress-meter__labels">
        <span>{label}</span>
        <span>{detail}</span>
      </div>
      <div
        className="progress-meter__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={safeValue}
      >
        <span style={{ width: `${safeValue}%` }} />
      </div>
    </div>
  );
}
