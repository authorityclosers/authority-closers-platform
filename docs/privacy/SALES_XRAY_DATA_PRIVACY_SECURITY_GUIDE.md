# Sales X-Ray: data storage, privacy and security

**For:** Wise Life · **From:** Authority Closers (AC) · 19 Oct 2026 · **Covers:** Sales X-Ray as AC hosts it for you (production, release v0.66), read from the code and the live server configuration. These are facts about Sales X-Ray; your counsel confirms the legal reading (DPDP Act 2023).

## 1. Roles
- **Wise Life decides** which calls and leads go into Sales X-Ray and why.
- **AC processes them** to provide the service, on its own server and through the AI providers named in section 4.

## 2. What we store for each call, and where
All of it sits on one AC virtual server in **Mumbai, India**.

| Data | Where |
|---|---|
| Call audio | Private file store on the server. The folder is readable only by the Sales X-Ray service account. Each file is named by its SHA-256 fingerprint and checked against it on every read. |
| Voice measures (loudness, pitch, pauses) and the waveform | Worked out on our server from the audio and kept in the same store. They never leave the server. |
| Transcript, report, coaching, pointer review and prospect profile | PostgreSQL database on the same server. The database has no public port, and each service uses its own login. |
| Call data engine facts (from v0.66) | The same database. Each fact (for example "team size: 8 people") has a type, a confidence score, the quote and timestamps it came from, and the version that produced it. Corrections are added as new rows; old ones are never overwritten. |
| Lead Desk (if you use it) | The same database. Per lead: name, phone, email, company, city, language, interest, stage, owner, notes and the raw form answers, plus a history of changes. For the phone app's call log, only calls to numbers that match your leads are recorded: number, start time, duration and direction. Leads come in only from sources you connect: Meta Lead Ads, Google Ads lead forms, a webhook, a sheet or a CSV file. |
| Sign-in | The database. A session token is stored only as a keyed hash, along with the browser's user agent and IP address. |

Development, staging and production run on the same machine. Each has its own database, file store and secrets.

## 3. Who can see it
- **Sign-in:**
  - Methods: Google, a 6-digit email code (valid for 10 minutes, 5 tries) or a password.
  - A session lasts 30 days.
  - Cookies are Secure, HttpOnly and SameSite=Lax.
  - Two-step sign-in is not available yet.
- **Inside your organisation:**
  - A **member** sees only their own calls.
  - An **owner or admin** can open every member's calls (report, transcript and audio) and can start their analysis.
  - Only the person who uploaded a call can delete it.
- **AC staff:**
  - Only named staff on an allow-list, signed in to AC's own operations workspace through the Admin app.
  - They can see the call queue, reports, transcripts, audio and the call data engine's facts. Parts of a call marked sensitive (financial or legal) are hidden from them.
  - Each time staff open a report or a call review, an event is written to **your** audit log.
  - Staff audio playback and call-data views are not logged yet.
- **Audit log:**
  - Covers uploads, upload consent, processing runs, deletion requests and deletions, retention expiry, member and role changes, sign-in consent, and changes to call data settings.
  - Each workspace has its own hash chain. The database refuses any edit or deletion of an audit row.
  - Sign-ins themselves are not audit events. The session record keeps the time, user agent and IP address.

## 4. AI providers: what they receive
| Provider | Receives | Why |
|---|---|---|
| **ElevenLabs** (Scribe v2) | The call audio | Transcription. All production calls in the last 30 days used it. |
| **Google Gemini** (paid API) | Transcript text only, never audio | The report, coaching, pointer review and prospect profile. From v0.66, also the call data engine's facts and segment labels. |

- **Where they process:** both providers may process data outside India.
- **What they keep:** each provider keeps data under its own published API terms. ElevenLabs' zero-retention mode is not switched on for our account. Under Google's paid Gemini API terms, the data is not used to train Google's models.
- **The call data engine** never sends segments marked sensitive, never quotes them, and never extracts phone numbers or email addresses. It fills a lead field only when it is confident and the value is quoted from the call, and it never overwrites a value a person entered.
- **Never leaves our server:**
  - the voice measures and waveform;
  - the database, except the backups in section 6;
  - your Lead Desk details. Phone alerts go through Google Firebase but carry only a lead id; the app then fetches the details from us over your own session.
- **Your webhook (optional):** if you register one, each finished analysis is sent to it as a signed event. Sensitive words are left out, numbers in the summary are masked, and the summary is cut to 1,500 characters.
- **Live transcription** during a call is built but switched off. It stays off until a privacy and provider review passes.

## 5. Consent
- **Account:** before signing in, each person ticks a box confirming they are 18 or older and accept AC's Terms and Privacy notice (version `ac-learner-terms-privacy-2026-10-18-v2`). The acceptance is recorded with an audit event.
- **Each upload:** the person accepts that upload's terms. The terms name the AI providers (ElevenLabs and Google Gemini), say the call is kept until deleted, and give the deletion contact. We record a fingerprint of the exact terms, the audio's hash and the time.
- **The other party:** our Terms require the consent of everyone on the call. Your team is responsible for telling the other party that the call is recorded and analysed. Wise Life staff open each call with a recording line, which does this.

## 6. Retention, deletion and backups
- **How long calls are kept:** each call is kept until it is deleted, with a technical limit of 10 years. This has applied since 18 Oct 2026, and earlier calls were extended to match.
- **Deleting a call** (the uploader uses "Delete call" in the app):
  - The call becomes unreadable at once, and an erase job removes:
    - the audio (once no other call in your workspace uses the identical file);
    - transcripts, reports and their drafts;
    - AI inputs, reviews, labels and metrics;
    - the call data engine's facts (their content is emptied).
  - What stays: audit rows, and the emptied rows with their ids, hashes and times.
- **What deleting a call does not remove:**
  - the prospect profile built from it (only the link to the call ends);
  - lead details already filled in from it.

  Lead Desk has no delete button yet. Ask us to delete a lead or a prospect.
- **How a customer asks for deletion:**
  - Email **admin@authorityclosers.com** with "Delete my data" (a call, a lead, or a whole account).
  - Our data-deletion page commits to finishing within 2 days.
  - There is no in-app account deletion or "download my data" yet.
- **Backups:**

  | Backup | How often | Where | Kept for |
  |---|---|---|---|
  | Database dump | Every 5 minutes | On the server, plus an encrypted copy in Cloudflare R2 | About 27 hours |
  | Database copy | Hourly | On the server (newest 24), plus Google Drive | 14 days on Drive |
  | Whole-server backup, including the audio | Daily | Encrypted copy in Cloudflare R2 | 7 daily, 4 weekly, 6 monthly |

  - Deleted data stays in these backups until they age out, which takes up to about 6 months.
  - The hourly Google Drive copies are not encrypted. **Being fixed.**
  - The weekly restore drills exist but failed on their last run. **Being fixed.**

## 7. Encryption and security
- **In transit:**
  - All traffic reaches the server only over HTTPS through Cloudflare (a Cloudflare Tunnel). The server publishes no public web or database port.
  - Pages send these security headers: HSTS (1 year), a Content Security Policy, X-Frame-Options DENY, no-referrer, and no-store on private pages.
- **Server access:**
  - The firewall denies incoming traffic by default.
  - Administrator access goes through a Cloudflare Access login for one named AC admin account.
- **At rest:**
  - The server disk is not encrypted, so the database and audio files are protected by file permissions and the measures above. **Being fixed.**
  - Encrypted: the daily and 5-minute off-site backups (Restic) and Meta lead-page tokens (AES-GCM).
  - Stored only as hashes: email codes and session tokens.
- **Secrets:**
  - Provider keys live in Infisical and are handed to each service only while it runs, so the keys themselves are never written to the server disk.
  - The server holds only Infisical access credentials, readable only by root and the service that needs them. Each AI provider has its own narrowly scoped credential.
