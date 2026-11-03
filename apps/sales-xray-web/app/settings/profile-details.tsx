"use client";

/**
 * Settings → Profile, part one (owner, 25 Oct 2026: a photo, a user id and the details,
 * "so the business owner can identify who did what work"; docs/product/
 * roles-owner-profile-pulse.md, section 3). The photo is cropped square on the device;
 * the user id changes once a month. Name, email and phone are in the same card, with one
 * status: "Profile complete", or "2 of 6" and Finish (owner, 3 Nov 2026).
 * ProfileCompletionCard is the nudge for Home, shown until the profile is complete.
 */
import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Camera, PawPrint, Trash2 } from "lucide-react";

import {
  readAccountProfile,
  type AccountProfileRecord,
} from "../account-profile-client";
import { displayName } from "../display-name";
import { notify } from "../notice-center";
import { useCharacters } from "../people/characters";
import { openSettings } from "../settings-open";
import {
  invalidateShellProfile,
  PROFILE_UPDATED_EVENT,
  useShellProfile,
} from "../shell/profile-store";
import { Avatar, Button, Field, Meter, Panel, SkeletonRow } from "../ui/kit";
import {
  DETAIL_MAX,
  missingWords,
  normalizeHandle,
  profileDetails,
  ProfileDetailsError,
  removeProfilePhoto,
  saveProfileDetails,
  squarePhoto,
  uploadProfilePhoto,
  type ProfileCompletion,
  type ProfileDetails,
} from "./profile-details-client";
import { CharacterSheet } from "./character-sheet";
import styles from "./profile-details.module.css";

// The name and phone editor loads only when opened: Home shows this file's
// completion card and never needs the account screen's code.
const ProfileForm = dynamic(() =>
  import("../account-settings").then((module) => module.ProfileForm),
);

type Draft = { handle: string; title: string; team: string };
type Problems = Partial<Record<keyof Draft, string>>;

const HANDLE_RULE =
  "Use 3 to 30 letters, digits, dots, dashes or underscores, starting with a letter or digit.";

const draftOf = (details: ProfileDetails): Draft => ({
  handle: details.handle ?? "",
  title: details.title ?? "",
  team: details.team ?? "",
});

/** The shell, the menu and the Home card read the profile again. */
function announce() {
  invalidateShellProfile();
  window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT));
}

function Progress({ completion }: { completion: ProfileCompletion }) {
  return (
    <div className={styles.progress}>
      <Meter
        value={completion.done}
        max={completion.total}
        label={`Profile ${completion.done} of ${completion.total} done`}
      />
      <small>
        Add {missingWords(completion.missing)}, so your team knows who did what.
      </small>
    </div>
  );
}

export function ProfileDetailsPanel() {
  const formId = useId();
  const picker = useRef<HTMLInputElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const [contact, setContact] = useState(false);
  const [profile, setProfile] = useState<AccountProfileRecord | null>(null);
  const [draft, setDraft] = useState<Draft>({
    handle: "",
    title: "",
    team: "",
  });
  const [problems, setProblems] = useState<Problems>({});
  const [busy, setBusy] = useState<"save" | "photo" | null>(null);
  // Choose your character (owner #32, 26 Oct 2026); none until they ship.
  const characters = useCharacters();
  const [choosing, setChoosing] = useState(false);

  const apply = useCallback((next: AccountProfileRecord) => {
    setProfile(next);
    setDraft(draftOf(profileDetails(next)));
  }, []);
  useEffect(() => {
    const control = new AbortController();
    readAccountProfile(control.signal).then(apply, () => {
      if (control.signal.aborted) return;
      notify({
        id: "profile-details",
        tone: "error",
        title: "Your profile did not load",
        message: "Open this page again in a moment.",
      });
    });
    return () => control.abort();
  }, [apply]);

  if (!profile) {
    // As tall as the profile it waits for, so the cards under it never move
    // when it arrives (robot b7b700e0: 0.13; 0.38 at 390 on a slow network).
    return (
      <Panel title="Your profile">
        <div aria-busy="true" className={styles.loading}>
          <SkeletonRow />
          <SkeletonRow />
        </div>
      </Panel>
    );
  }
  const details = profileDetails(profile);
  const saved = draftOf(details);
  const dirty =
    draft.handle !== saved.handle ||
    draft.title !== saved.title ||
    draft.team !== saved.team;
  const name = displayName(profile.name?.trim() ?? "") || profile.email;
  const completion = details.completion;
  // Without a photo, the character picked for this person.
  const avatarUrl =
    details.avatarUrl ??
    characters.find((item) => item.key === details.defaultCharacter)?.url ??
    null;

  const edit = (key: keyof Draft, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setProblems((current) => ({ ...current, [key]: undefined }));
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || !dirty) return;
    const handle = draft.handle.trim() ? normalizeHandle(draft.handle) : null;
    if (draft.handle.trim() && !handle)
      return setProblems({ handle: HANDLE_RULE });
    setBusy("save");
    setProblems({});
    try {
      await saveProfileDetails({
        handle,
        title: draft.title,
        team: draft.team,
        expected_revision: details.revision,
      });
      apply(await readAccountProfile());
      announce();
      notify({
        id: "profile-details",
        tone: "success",
        title: "Profile saved",
        message: "Your team sees it on the work you do.",
      });
    } catch (error) {
      const status = error instanceof ProfileDetailsError ? error.status : 0;
      const words = error instanceof Error ? error.message : "";
      if (status === 409) {
        // Taken, too soon, or the profile changed elsewhere: the revision tells which.
        const latest = await readAccountProfile().catch(() => null);
        if (latest && profileDetails(latest).revision !== details.revision) {
          setProfile(latest);
          notify({
            id: "profile-details",
            tone: "error",
            title: "Your profile changed elsewhere",
            message: "Your changes are still here. Check them and save again.",
          });
        } else {
          setProblems({
            handle: words || "That user id is taken. Try another.",
          });
        }
      } else if (status === 422 && words.includes("user id")) {
        setProblems({ handle: words });
      } else {
        notify({
          id: "profile-details",
          tone: "error",
          title: "Not saved",
          message:
            status === 401
              ? "Your session ended. Sign in again to save."
              : "Your changes are still here. Save again in a moment.",
        });
      }
    } finally {
      setBusy(null);
    }
  };

  const photoDone = async (title: string) => {
    setProfile(await readAccountProfile());
    announce();
    notify({ id: "profile-photo", tone: "success", title });
  };
  const choosePhoto = async (file: File | undefined) => {
    if (!file || busy) return;
    setBusy("photo");
    try {
      const photo = await squarePhoto(file).catch(() => {
        throw new ProfileDetailsError(0, "unreadable");
      });
      await uploadProfilePhoto(photo);
      await photoDone("Photo saved");
    } catch (error) {
      const status = error instanceof ProfileDetailsError ? error.status : -1;
      notify({
        id: "profile-photo",
        tone: "error",
        title: "Photo not saved",
        message:
          status === 0
            ? "This photo could not be read. Choose a JPEG, PNG or WebP photo."
            : status === 413
              ? "Choose a photo up to 2 MB."
              : status === 422 && error instanceof Error && error.message
                ? error.message
                : "Try again in a moment.",
      });
    } finally {
      setBusy(null);
    }
  };
  const removePhoto = async () => {
    if (busy) return;
    setBusy("photo");
    try {
      await removeProfilePhoto();
      await photoDone("Photo removed");
    } catch {
      notify({
        id: "profile-photo",
        tone: "error",
        title: "Photo not removed",
        message: "Try again in a moment.",
      });
    } finally {
      setBusy(null);
    }
  };

  const complete = !!completion && completion.done >= completion.total;
  // Finish goes to the first thing still missing.
  const finish = () => {
    const first = completion?.missing[0];
    if (first === "photo") picker.current?.click();
    else if (first === "name" || first === "phone") setContact(true);
    else if (first) {
      const field = form.current?.elements.namedItem(first);
      if (field instanceof HTMLInputElement) field.focus();
    }
  };

  return (
    <Panel
      title="Your profile"
      sub={
        completion
          ? complete
            ? "Profile complete"
            : `${completion.done} of ${completion.total}`
          : undefined
      }
      tools={
        completion && !complete ? (
          <Button variant="secondary" onClick={finish}>
            Finish
          </Button>
        ) : undefined
      }
      foot={
        <Button
          variant="primary"
          type="submit"
          form={formId}
          disabled={!dirty || busy !== null}
        >
          {busy === "save" ? "Saving…" : "Save profile"}
        </Button>
      }
    >
      {/* The standard card padding (builder, 26 Oct 2026). */}
      <div className={styles.body}>
        <div className={styles.photoRow}>
          {/* Tap the avatar to add or change it (owner, 26 Oct 2026); the gallery only, no
            camera, so the app needs no camera permission. */}
          <button
            type="button"
            className={styles.avatarButton}
            aria-label={details.avatarUrl ? "Change your photo" : "Add a photo"}
            disabled={busy !== null}
            onClick={() => picker.current?.click()}
          >
            <Avatar name={name} photoUrl={avatarUrl} size={72} />
            <span className={styles.avatarBadge} aria-hidden="true">
              <Camera size={13} />
            </span>
          </button>
          <div className={styles.photoText}>
            <strong>{name}</strong>
            {details.handle ? <span>@{details.handle}</span> : null}
            <span className={styles.photoActions}>
              <Button
                variant="secondary"
                disabled={busy !== null}
                onClick={() => picker.current?.click()}
              >
                <Camera size={15} aria-hidden="true" />
                {busy === "photo"
                  ? "Saving…"
                  : details.avatarUrl
                    ? "Change photo"
                    : "Add photo"}
              </Button>
              {characters.length ? (
                <Button
                  variant="secondary"
                  disabled={busy !== null}
                  onClick={() => setChoosing(true)}
                >
                  <PawPrint size={15} aria-hidden="true" />
                  Choose a character
                </Button>
              ) : null}
              {details.ownPhoto ? (
                <Button
                  variant="ghost"
                  disabled={busy !== null}
                  onClick={() => void removePhoto()}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  Remove
                </Button>
              ) : null}
            </span>
            <input
              ref={picker}
              className={styles.picker}
              type="file"
              accept="image/*"
              aria-label="Choose a photo"
              tabIndex={-1}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                void choosePhoto(file);
              }}
            />
          </div>
        </div>
        <CharacterSheet
          open={choosing}
          current={
            details.character ??
            (details.avatarUrl ? null : details.defaultCharacter)
          }
          replacesPhoto={details.avatarUrl !== null && !details.character}
          onClose={() => setChoosing(false)}
          onChosen={() => {
            setChoosing(false);
            void photoDone("Character saved");
          }}
        />
        {contact ? (
          <ProfileForm
            profile={profile}
            onCancel={() => setContact(false)}
            onNeedsRefresh={() => void readAccountProfile().then(apply)}
            onSaved={(next) => {
              apply(next);
              setContact(false);
              announce();
            }}
          />
        ) : (
          <div className={styles.contact}>
            <dl>
              <div>
                <dt>Email</dt>
                <dd>{profile.email}</dd>
              </div>
              <div>
                <dt>Phone</dt>
                <dd>
                  {profile.phone_number_e164 ?? "Not added yet"}
                  {profile.phone_number_e164 ? (
                    <span
                      className={styles.badge}
                      data-tone={profile.phone_verified ? "ok" : "pending"}
                    >
                      {profile.phone_verified ? "Verified" : "Not verified"}
                    </span>
                  ) : null}
                </dd>
              </div>
            </dl>
            <Button variant="ghost" onClick={() => setContact(true)}>
              Edit name and phone
            </Button>
          </div>
        )}
        {completion && !complete ? <Progress completion={completion} /> : null}
        {profile.phone_number_e164 && !profile.phone_verified ? (
          <p className={styles.phoneNote}>
            Your phone number isn&apos;t verified yet. Verifying it by text
            message is coming: it lets Sales X-Ray match your calls to you.
            Until then your team sees the number as you entered it.
          </p>
        ) : null}
        <form
          ref={form}
          id={formId}
          className={styles.form}
          onSubmit={(event) => void save(event)}
          noValidate
        >
          <Field
            label="User id"
            hint="3 to 30 letters, digits, dots, dashes or underscores. You can change it once a month."
            error={problems.handle}
          >
            <input
              name="handle"
              value={draft.handle}
              maxLength={31}
              autoCapitalize="none"
              autoComplete="off"
              spellCheck={false}
              placeholder="For example, priya.s"
              onChange={(event) => edit("handle", event.target.value)}
            />
          </Field>
          <Field
            label="Job title"
            hint="For example, Sales manager."
            error={problems.title}
          >
            <input
              name="title"
              value={draft.title}
              maxLength={DETAIL_MAX}
              autoComplete="organization-title"
              onChange={(event) => edit("title", event.target.value)}
            />
          </Field>
          <Field
            label="Team"
            hint="For example, Inside sales."
            error={problems.team}
          >
            <input
              name="team"
              value={draft.team}
              maxLength={DETAIL_MAX}
              autoComplete="off"
              onChange={(event) => edit("team", event.target.value)}
            />
          </Field>
        </form>
      </div>
    </Panel>
  );
}

/** For Home: how much of the profile is done, until all of it is. */
export function ProfileCompletionCard() {
  const profile = useShellProfile(true);
  const completion = profile ? profileDetails(profile).completion : null;
  if (!completion || completion.done >= completion.total) return null;
  return (
    <Panel
      title="Your profile"
      sub={`${completion.done} of ${completion.total}`}
      tools={
        <Button variant="secondary" onClick={() => openSettings("profile")}>
          Finish profile
        </Button>
      }
    >
      <Progress completion={completion} />
    </Panel>
  );
}
