# Sales X-Ray tutorials pipeline

Short how-to videos for Sales X-Ray (Android app and web, phone and desktop) in English, Hinglish and
Marathi-English. One run produces all three delivery options, and re-running after a UI change re-captures the
screens and reuses every voice line that did not change.

| Option | What | Who uses it |
| --- | --- | --- |
| A, narrated | MP4 per tutorial per language, ElevenLabs voice, captions burned in and as SRT | publish as is |
| B, voice-over kit | silent cut of each video, per-language script with timecodes, cue sheet | Dipak or the owner records their own voice |
| C, editor pack | raw phone and desktop clips, labelled stills, SRTs, FCPXML and Premiere XML timelines, shot list, README | a video editor |

## Steps

```
tutorials.json (list, from the Feature catalogue)
  -> scripts/<id>.json (storyboard: one segment = one shot + the line in en/hi/mr)
  -> capture  (Playwright on ac against dev review fixtures, fictional data only)
  -> voice    (ElevenLabs Eleven v4 per line, cached; character timings; speech-to-text check)
  -> build    (ffmpeg: clips timed to the voice, device frame, titles, captions, loudness)
  -> pack     (A, B and C folders) -> Google Drive "Sales X-Ray Tutorials/<date>/"
```

1. **List.** `tutorials.json` names, per tutorial, the catalogue features it teaches, the fixture screens, the
   devices and the length. Tests check that every feature id is still in `scripts/catalogue/feature_seed.json`.
2. **Storyboard.** `scripts/<id>.json` holds one segment per shot: the device, the screen, the actions (tap, type,
   scroll, open a sheet), what to highlight, and the line in each language as `say` (what the voice reads:
   Devanagari Hindi/Marathi with English product words in Latin) and `caption` (Roman script, how Pune sellers
   type). The shot list CSV is generated from it.
3. **Capture.** `capture.mjs` drives headless Chromium on ac against the dev server's loopback review fixtures
   (`/review-fixture/...`, made-up names and numbers, no sign-in). Desktop 1440x900 at 2x, phone 390x844 at 3x.
   Each shot is a short real-time recording (CDP screencast frames to H.264) plus labelled PNG stills; taps show
   as a soft ring. Steps only the native app can show (Play Store, the phone's dialler, recordings attaching) come
   from the real Redmi via `adb screenrecord`, booked through the orchestrator (one phone driver at a time).
4. **Voice.** `sxtut/tts.py` sends each line to ElevenLabs `with-timestamps` (Eleven v4, voices in
   `voices.json`), caches it by a hash of text + voice + model + settings, and keeps the character timings for
   captions. `pronounce.json` sets how product names are said ("Brain 4.0" -> "Brain four point oh"); a Scribe
   speech-to-text pass checks every line says "Sales X-Ray" and "Brain 4.0" so they are heard right.
5. **Build.** Each shot is timed to its line (held or trimmed, never sped up), phone shots sit in a device frame on
   a 1920x1080 stage, with a title card and an end card. Audio is normalised to -16 LUFS. Captions come from the
   character timings, split at punctuation, at most two lines of 42 characters.
6. **Pack.** A, B and C folders as above, uploaded with rclone to the AC Drive (`acdrive:`, admin@) under
   `Sales X-Ray Tutorials/<date>/`. Nothing is stored as a GitHub artifact.

## Rules every script line follows

- No prices, costs or minutes; no real customer names, phone numbers or e-mail addresses (`tutorials.py lint`).
- UI labels in English exactly as they appear on screen ("Leads", "Start calling", "Taking leads").
- The product is "Sales X-Ray"; the score is "Brain 4.0".
- Spoken the way Pune sellers talk: short sentences, English words for app things, Hindi/Marathi for the rest.

## Voice

The key is the dev ElevenLabs key in Infisical (`/sales-xray-test/elevenlabs`), read only at run time:
`scripts/tutorials/with-elevenlabs <command>` injects it into one process run as acdev, under
`nice -n 19 ionice -c3`. Never print it. Check characters left with `tutorials.py quota` before a full render;
if they run short, stop and ask (never buy credits). Voices are ElevenLabs library voices on the AC account; no
real person is cloned unless the owner asks.

## Running on ac

```bash
cd /home/acdev/src/dev-live/authority-closers-platform
python3 scripts/tutorials/tutorials.py lint
scripts/tutorials/with-elevenlabs python3 scripts/tutorials/tutorials.py samples
```

Heavy steps (capture, build) run one at a time under `nice -n 19 ionice -c3`, ffmpeg with `-threads 2`, and pause
while the load average is above 4. Outputs go to `$SXTUT_OUT` (default `~/sx-tutorials`); keep it under 5 GB.
Tests: `ssh ac wb-ci --py --py-tests tests/unit/tutorials/test_tutorial_pipeline.py`.
