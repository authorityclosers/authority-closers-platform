# Sales X-Ray tutorials: editor pack

Everything to cut your own version of each tutorial. One folder per tutorial.

## In each tutorial folder

| File                        | What it is                                                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `<id>.fcpxml`               | Timeline for Final Cut Pro or DaVinci Resolve (File > Import > Timeline). 1920x1080, 30 fps.                                   |
| `<id>-premiere.xml`         | The same timeline for Premiere Pro (File > Import).                                                                            |
| `<id>-reference-silent.mp4` | Our framed cut (phone in a bezel, step titles), no sound. Match it or ignore it.                                               |
| `<id>-shot-list.csv`        | One row per shot: in-point, length, device, what is on screen, the fixture screen, the English line.                           |
| `media/clips/`              | Raw screen recordings. Phone: 1170x2532 (390x844 at 3x). Computer: 2880x1800 (1440x900 at 2x). H.264, 30 fps.                  |
| `media/stills/`             | Lossless PNG stills, named `<tutorial>--<shot>--<moment>.png`.                                                                 |
| `media/cards/`              | Our title and end cards (PNG, 1920x1080).                                                                                      |
| `media/voice/<lang>/`       | The AI voice line for each shot, per language (en, hi, mr), MP3.                                                               |
| `captions/`                 | SRT per language. Hinglish and Marathi-English come in Roman script (`-hi.srt`, `-mr.srt`) and Devanagari (`-devanagari.srt`). |

## Timeline layout

- Video track: title card, then one raw clip per shot at its slot, then the end card. The clips are set to "fit";
  phone clips are portrait, so place them in a frame or crop as you like.
- Three audio lanes/tracks: English (`dialogue.en`), Hinglish (`dialogue.hi`), Marathi-English (`dialogue.mr`).
  Keep one, mute the others. Each slot is long enough for the longest of the three lines.
- If a clip ends before its slot, hold its last frame (freeze frame) to the end of the slot.
- Media paths are relative to the tutorial folder. If your editor asks, relink to the `media` folder.

## Rules for the final cut

- Keep every UI word in English, exactly as on screen ("Leads", "Start calling", "Taking leads").
- The product is "Sales X-Ray" (capital S, X and R, with the hyphen). The score is "Brain 4.0".
- Never add prices, costs, plan names or minutes, and never real customer names or phone numbers. All names and
  numbers in these recordings are made up (Asha Fictional, Ravi Sample, and so on).
- Screens may change after this date; the pipeline re-records them, so ask for a fresh pack rather than patching.
