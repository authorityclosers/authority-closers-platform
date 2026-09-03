import { Eye } from "lucide-react";

export function PreviewNotice() {
  return (
    <aside className="preview-notice" aria-label="Preview data notice">
      <div className="preview-notice__icon">
        <Eye size={17} aria-hidden="true" />
      </div>
      <div>
        <strong>Preview workspace</strong>
        <p>
          Demo course copy and sample learner state only. No account,
          enrollment, progress, evidence, email, or certificate is changed here.
        </p>
      </div>
    </aside>
  );
}
