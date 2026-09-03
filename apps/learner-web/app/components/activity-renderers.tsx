import {
  Check,
  ChevronRight,
  CircleHelp,
  FileText,
  Flag,
  LockKeyhole,
  Play,
} from "lucide-react";

import type { ActivityViewModel } from "../lib/view-models";

function ActivityFormFooter({ label }: { label: string }) {
  return (
    <div className="activity-form__footer">
      <span className="save-note">
        <span className="save-note__dot" aria-hidden="true" />
        Input is not stored in preview
      </span>
      <button className="button button--ink" type="button" disabled>
        <LockKeyhole size={16} aria-hidden="true" /> {label}
      </button>
    </div>
  );
}

function VideoActivity({ activity }: { activity: ActivityViewModel }) {
  return (
    <div className="renderer-stack">
      <div
        className="video-preview video-preview--inert"
        role="group"
        aria-label="Video integration preview; no media loaded"
      >
        <div className="video-preview__grid" aria-hidden="true" />
        <div className="video-preview__meta">
          <span className="video-preview__badge">VIDEO · INTEGRATION SEAM</span>
          <span>{activity.duration} lesson target</span>
        </div>
        <div className="video-preview__center">
          <span className="video-preview__play" aria-hidden="true">
            <Play size={24} />
          </span>
          <strong>Media not connected</strong>
          <span>
            No playback, timeline, or captions are available in this preview.
          </span>
        </div>
        <div className="video-preview__footer">
          <span>No media loaded</span>
          <span>Sample transcript copy below</span>
        </div>
      </div>
      <details className="transcript-card" open>
        <summary>
          <span>
            <FileText size={16} aria-hidden="true" /> Read sample transcript
            copy
          </span>
          <ChevronRight size={16} aria-hidden="true" />
        </summary>
        <p>
          Preview copy, not synchronized media: “When a buyer asks for one more
          detail, listen for the decision they are trying to make. A useful
          question gives that decision somewhere honest to go.”
        </p>
      </details>
      <div className="evidence-note">
        <CircleHelp size={16} aria-hidden="true" />
        <span>
          {activity.evidenceLabel}. No playback or completion evidence exists in
          this preview.
        </span>
      </div>
    </div>
  );
}

function ReflectionActivity({ activity }: { activity: ActivityViewModel }) {
  return (
    <form
      className="activity-form renderer-stack"
      aria-label="Disabled reflection preview"
    >
      <div className="prompt-card prompt-card--acid">
        <span className="prompt-card__label">Prompt preview</span>
        <p>{activity.prompt}</p>
      </div>
      <div className="field-group">
        <label htmlFor="reflection-response">Your reflection</label>
        <textarea
          id="reflection-response"
          name="reflection"
          rows={7}
          placeholder="Input becomes available after durable draft storage is connected."
          disabled
          aria-describedby="reflection-help"
        />
        <p id="reflection-help" className="field-help">
          Disabled preview seam. Nothing entered here can be stored or
          recovered.
        </p>
      </div>
      <ActivityFormFooter label="Draft saving unavailable" />
    </form>
  );
}

function ChallengeActivity({ activity }: { activity: ActivityViewModel }) {
  const options = [
    "Ask what changed since the last conversation.",
    "Add three more product details before asking again.",
    "Move directly to a close before the signal disappears.",
  ];

  return (
    <form
      className="activity-form renderer-stack"
      aria-label="Disabled implementation challenge preview"
    >
      <div className="scenario-card">
        <span className="scenario-card__label">
          Scenario preview · a buyer goes quiet
        </span>
        <p>
          “I need to think about it.” You have one thoughtful follow-up before
          the call ends.
        </p>
      </div>
      <fieldset className="choice-fieldset choice-fieldset--stacked" disabled>
        <legend>{activity.prompt}</legend>
        {options.map((option, index) => (
          <label className="radio-card" key={option}>
            <input type="radio" name="challenge-choice" value={option} />
            <span className="radio-card__index">0{index + 1}</span>
            <span>{option}</span>
          </label>
        ))}
      </fieldset>
      <div className="field-group">
        <label htmlFor="challenge-notes">
          What makes this response useful?
        </label>
        <textarea
          id="challenge-notes"
          name="notes"
          rows={4}
          placeholder="Submission input is unavailable in this preview."
          disabled
        />
      </div>
      <ActivityFormFooter label="Submission unavailable" />
    </form>
  );
}

function ReviewActivity({ activity }: { activity: ActivityViewModel }) {
  const reviewCriteria = [
    "The attempt names a specific conversation.",
    "The chosen move is observable by another person.",
    "The learner can explain why the move matters.",
  ];

  return (
    <form
      className="activity-form renderer-stack"
      aria-label="Disabled human review preview"
    >
      <div className="review-banner">
        <div className="review-banner__icon">
          <Flag size={18} aria-hidden="true" />
        </div>
        <div>
          <strong>Human-authored review</strong>
          <p>
            This preview shows the review contract. It does not route work or
            make an AI judgment.
          </p>
        </div>
      </div>
      <fieldset className="choice-fieldset choice-fieldset--stacked" disabled>
        <legend>{activity.prompt}</legend>
        {reviewCriteria.map((criterion) => (
          <label className="check-card" key={criterion}>
            <input type="checkbox" />
            <span className="check-card__box" aria-hidden="true">
              <Check size={14} />
            </span>
            <span>{criterion}</span>
          </label>
        ))}
      </fieldset>
      <div className="field-group">
        <label htmlFor="review-note">Reviewer context</label>
        <textarea
          id="review-note"
          name="review-note"
          rows={5}
          placeholder="Human review routing is unavailable in this preview."
          disabled
        />
      </div>
      <ActivityFormFooter label="Review routing unavailable" />
    </form>
  );
}

function ImproveActivity({ activity }: { activity: ActivityViewModel }) {
  return (
    <form
      className="activity-form renderer-stack"
      aria-label="Disabled improvement preview"
    >
      <div className="improve-grid">
        <div className="improve-cell improve-cell--before">
          <span>Before</span>
          <p>The old move I notice…</p>
        </div>
        <div className="improve-cell improve-cell--after">
          <span>Next rep</span>
          <p>The small change I will repeat…</p>
        </div>
      </div>
      <div className="field-group">
        <label htmlFor="improve-before">What happened before?</label>
        <textarea
          id="improve-before"
          name="before"
          rows={4}
          placeholder="Improvement input is unavailable in this preview."
          disabled
        />
      </div>
      <div className="field-group">
        <label htmlFor="improve-after">What will you try next?</label>
        <textarea
          id="improve-after"
          name="after"
          rows={4}
          placeholder={activity.prompt}
          disabled
        />
      </div>
      <ActivityFormFooter label="Improvement saving unavailable" />
    </form>
  );
}

export function ActivityRenderer({
  activity,
}: {
  activity: ActivityViewModel;
}) {
  switch (activity.kind) {
    case "VIDEO":
      return <VideoActivity activity={activity} />;
    case "REFLECTION":
      return <ReflectionActivity activity={activity} />;
    case "IMPLEMENTATION_CHALLENGE":
      return <ChallengeActivity activity={activity} />;
    case "REVIEW":
      return <ReviewActivity activity={activity} />;
    case "IMPROVE":
      return <ImproveActivity activity={activity} />;
  }
}
