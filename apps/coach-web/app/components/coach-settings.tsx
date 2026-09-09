"use client";
import { useRef, useState } from "react";
import {
  Laptop,
  LogOut,
  Moon,
  ShieldCheck,
  Sparkles,
  Sun,
  UserRound,
} from "lucide-react";
import { StudioAccountAccess } from "@ac/operations-web/studio-workspace";
import { useAdminSession } from "@ac/operations-web/session";
import { useCoachPreferences } from "./coach-preferences";

export function CoachSettings() {
  const preferences = useCoachPreferences();
  const session = useAdminSession();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const signingOut = useRef(false);
  async function signOut() {
    if (signingOut.current) return;
    signingOut.current = true;
    setPending(true);
    setError("");
    try {
      const response = await fetch("/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error();
      window.location.assign("/login");
    } catch {
      setError("We couldn’t confirm sign-out. Please try again.");
    } finally {
      signingOut.current = false;
      setPending(false);
    }
  }
  return (
    <div className="coach-settings">
      <header className="coach-page-heading">
        <span className="section-eyebrow">MAKE STUDIO YOURS</span>
        <h1>Settings</h1>
        <p>Your account, workspace access and a comfortable place to create.</p>
      </header>
      <section
        className="coach-settings-card"
        aria-labelledby="appearance-title"
      >
        <div className="coach-card-heading">
          <span>
            <Sun size={21} aria-hidden="true" />
          </span>
          <div>
            <h2 id="appearance-title">Appearance</h2>
            <p>Choose the look that feels right for you.</p>
          </div>
        </div>
        <div
          className="coach-theme-options"
          role="group"
          aria-label="Colour theme"
        >
          {(
            [
              ["light", "Light", Sun],
              ["dark", "Dark", Moon],
              ["system", "System", Laptop],
            ] as const
          ).map(([value, label, Icon]) => (
            <button
              key={value}
              type="button"
              aria-pressed={preferences.theme === value}
              onClick={() =>
                preferences.save({
                  theme: value,
                  reduceMotion: preferences.reduceMotion,
                })
              }
            >
              <Icon size={23} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </div>
        <div className="coach-settings-row">
          <div>
            <h3>
              <Sparkles size={17} aria-hidden="true" /> Reduce animation
            </h3>
            <p>
              Keep movement minimal. Your device’s reduced-motion setting is
              always respected.
            </p>
          </div>
          <button
            className="coach-switch"
            type="button"
            role="switch"
            aria-checked={preferences.reduceMotion}
            aria-label="Reduce animation"
            onClick={() =>
              preferences.save({
                theme: preferences.theme,
                reduceMotion: !preferences.reduceMotion,
              })
            }
          >
            <span />
          </button>
        </div>
        <p className="coach-preference-note" role="status">
          {preferences.message ||
            "Appearance preferences apply to Studio in this browser."}
        </p>
      </section>
      <section className="coach-settings-card" aria-labelledby="account-title">
        <div className="coach-card-heading">
          <span>
            <UserRound size={21} aria-hidden="true" />
          </span>
          <div>
            <h2 id="account-title">Account & access</h2>
            <p>Know which parts of your academy you can manage.</p>
          </div>
        </div>
        {session.status === "error" ? (
          <div role="alert">
            <p>We couldn’t check your account. Reload to reconnect.</p>
            <button
              className="button button-secondary"
              onClick={() => window.location.reload()}
            >
              Reconnect
            </button>
          </div>
        ) : (
          <StudioAccountAccess />
        )}
        <p className="coach-access-note">
          <ShieldCheck size={18} aria-hidden="true" />
          <span>
            Your administrator manages course assignments and publishing access.
            Platform administration is a separate workspace.
          </span>
        </p>
      </section>
      <section
        className="coach-settings-card coach-settings-row"
        aria-label="Sign out"
      >
        <div>
          <h2>Done for now?</h2>
          <p>Sign out of this Studio session on this browser.</p>
          {error && (
            <p role="alert" className="coach-signout-error">
              {error}
            </p>
          )}
        </div>
        <button
          className="button button-secondary"
          onClick={signOut}
          disabled={pending}
        >
          <LogOut size={17} aria-hidden="true" />
          {pending ? "Signing out…" : "Sign out"}
        </button>
      </section>
    </div>
  );
}
