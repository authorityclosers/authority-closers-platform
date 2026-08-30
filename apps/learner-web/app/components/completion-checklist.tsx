import { Check, CircleDashed, LockKeyhole } from "lucide-react";

const checklist = [
  {
    label: "Required activities complete",
    detail: "The server will verify the versioned activity predicate.",
    complete: false,
  },
  {
    label: "Evidence is present and explainable",
    detail: "Drafts alone do not become official completion evidence.",
    complete: false,
  },
  {
    label: "Certificate issuance is authorized",
    detail:
      "A course-completion certificate is separate from competency certification.",
    complete: false,
  },
];

export function CompletionChecklist() {
  return (
    <div className="completion-layout">
      <section
        className="checklist-card"
        aria-labelledby="completion-checklist-title"
      >
        <div className="checklist-card__header">
          <p className="kicker">Server-authoritative gate · preview</p>
          <h2 id="completion-checklist-title">What completion must prove</h2>
          <p>
            This list makes the handoff visible. The UI cannot mark a course
            complete or issue a credential by itself.
          </p>
        </div>
        <ol className="completion-list">
          {checklist.map((item, index) => (
            <li
              key={item.label}
              className={item.complete ? "is-complete" : "is-pending"}
            >
              <span className="completion-list__icon" aria-hidden="true">
                {item.complete ? (
                  <Check size={15} />
                ) : (
                  <CircleDashed size={15} />
                )}
              </span>
              <span>
                <strong>
                  {String(index + 1).padStart(2, "0")} · {item.label}
                </strong>
                <span>{item.detail}</span>
              </span>
            </li>
          ))}
        </ol>
        <div className="locked-callout" role="note">
          <LockKeyhole size={17} aria-hidden="true" />
          <p>
            <strong>Certificate issuance is locked in this preview.</strong>{" "}
            There is no official completion result to display.
          </p>
        </div>
      </section>
      <aside className="completion-next">
        <p className="kicker">Keep going</p>
        <h2>Return to the practice path.</h2>
        <p>
          Pick up the next activity when the connected learner session is ready.
        </p>
        <span
          className="button button--ink button--full is-disabled"
          aria-disabled="true"
        >
          Return when an enrollment is available{" "}
          <span aria-hidden="true">↗</span>
        </span>
      </aside>
    </div>
  );
}
