import { LockKeyhole, UserRound } from "lucide-react";

const contexts = ["Sales", "Founder", "Customer success"];

export function OnboardingForm() {
  return (
    <form className="onboarding-form" aria-label="Disabled onboarding preview">
      <div className="form-step">
        <span className="form-step__number">01</span>
        <div>
          <h2>Give the work a name</h2>
          <p>
            This field is disabled. Profile creation is not connected to this
            preview.
          </p>
        </div>
      </div>
      <div className="field-group">
        <label htmlFor="learner-name">Name you want to see</label>
        <div className="input-with-icon">
          <UserRound size={17} aria-hidden="true" />
          <input
            id="learner-name"
            name="name"
            type="text"
            autoComplete="name"
            placeholder="Your name"
            disabled
            aria-describedby="learner-name-help"
          />
        </div>
        <p id="learner-name-help" className="field-help">
          No name is collected, stored, or applied here.
        </p>
      </div>

      <fieldset className="choice-fieldset">
        <legend>
          <span className="form-step__number">02</span>
          What kind of conversation are you practicing?
        </legend>
        <div className="choice-grid">
          {contexts.map((option) => (
            <button className="choice-card" key={option} type="button" disabled>
              <span>{option}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <p className="field-help">
        Profile personalization requires an authenticated, durable profile
        service.
      </p>
      <button
        className="button button--ink button--full"
        type="button"
        disabled
      >
        <LockKeyhole size={17} aria-hidden="true" /> Profile setup unavailable
        in preview
      </button>
    </form>
  );
}
