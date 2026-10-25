#!/usr/bin/env python3
"""Sales X-Ray tutorial pipeline (see README.md in this folder).

    tutorials.py lint             check every script line and title against the owner rules
    tutorials.py quota            ElevenLabs plan and characters left (needs the key)
    tutorials.py samples          voice samples: each language x both cast voices, hearing check
    tutorials.py voice   <which>  voice lines (cached; only new lines cost characters; needs key)
    tutorials.py capture <which>  screen clips and stills from the dev review fixtures
    tutorials.py build   <which>  A (narrated), B (voice-over kit) and C (editor pack)
    tutorials.py fonts            caption font for burned-in subtitles (once per output folder)
    tutorials.py pack             READMEs into the A, B and C folders (then upload-to-drive)
    tutorials.py v2 <step> <which>  v2, brand B: take|voice|build|all|index|pack (v2/*.json)

<which> is a tutorial id, a comma-separated list, batch1, batch2 or all. `--langs en,hi,mr` limits
languages. Outputs go to $SXTUT_OUT (default ~/sx-tutorials)/<date>. Only quota, samples and voice
call ElevenLabs; run those through scripts/tutorials/with-elevenlabs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from sxtut import textprep  # noqa: E402

OUT = Path(os.environ.get("SXTUT_OUT") or str(Path.home() / "sx-tutorials"))
LANGS = ("en", "hi", "mr")


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def boards(which: str) -> list[tuple[Path, dict]]:
    listed = load("tutorials.json")["tutorials"]
    if which == "all":
        ids = [t["id"] for t in listed]
    elif which.startswith("batch"):
        ids = [t["id"] for t in listed if str(t.get("batch")) == which[5:]]
    else:
        ids = which.split(",")
    out = []
    for i in ids:
        f = HERE / "scripts" / f"{i}.json"
        if f.exists():
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        else:
            print(f"{i}: no storyboard yet, skipped")
    return out


def day_dir(args: argparse.Namespace) -> Path:
    return OUT / (args.date or dt.date.today().isoformat())


def cmd_quota(_: argparse.Namespace) -> int:
    from sxtut import tts

    print(json.dumps(tts.quota(), indent=1))
    return 0


def cmd_samples(args: argparse.Namespace) -> int:
    from sxtut import tts

    cast = load("voices.json")
    samples = load("samples.json")["lines"]
    pronounce = load("pronounce.json")
    rules = textprep.load_pronounce()
    out = OUT / "voice-samples"
    out.mkdir(parents=True, exist_ok=True)
    q = tts.quota()
    need = sum(
        len(textprep.spoken(samples[lang]["say"], lang, rules)) for lang in args.langs
    ) * len(args.voices)
    print(f"characters needed ~{need}; left {q['left']}")
    if need > q["left"]:
        print("not enough characters left; stopping (never buy credits without the owner)")
        return 2
    report = []
    for lang in args.langs:
        for which in args.voices:
            say = textprep.spoken(samples[lang]["say"], lang, rules)
            line = tts.line_from_cast(say, lang, cast, which)
            audio, info = tts.synthesize(line, OUT / "cache" / "tts")
            name = cast["languages"][lang][which]["name"]
            slug = name.split(" ")[0].lower()
            dest = out / f"sample-{lang}-{which}-{slug}.mp3"
            dest.write_bytes(audio.read_bytes())
            hearing = tts.transcribe(audio, cast["languages"][lang]["language_code"])
            got = tts.heard(hearing.get("text", ""), pronounce)
            dur = (
                info["alignment"]["character_end_times_seconds"][-1]
                if info.get("alignment")
                else None
            )
            report.append(
                {
                    "file": dest.name,
                    "lang": lang,
                    "voice": name,
                    "model": line.model_id,
                    "seconds": round(dur, 1) if dur else None,
                    "heard": got,
                    "transcript": hearing.get("text", ""),
                }
            )
            print(f"{dest.name}: {report[-1]['seconds']} s, heard {got}")
    (out / "samples-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


NOT_PROSE = {
    "id",
    "url",
    "do",
    "chapter",
    "beat",
    "css",
    "role",
    "name",
    "placeholder",
    "label",
    "device",
    "names",
    "sync",
    "key",
    "theme",
    "footage",
    "phone",
}


def lint_v2(board: dict) -> list[str]:
    """Owner rules on every word a v2 storyboard puts on screen or in a voice, and every spoken
    line present in all three languages (Roman-script captions for Hinglish and Marathi)."""
    problems: list[str] = []

    def walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in NOT_PROSE:
                    walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")
        elif isinstance(node, str):
            problems.extend(f"{where}: {p}" for p in textprep.lint(node))

    walk(board, board.get("id", "?"))
    from sxtut import v2

    for o in v2.spoken_lines(board):
        for lang in LANGS:
            if not (o.get("say") or {}).get(lang):
                problems.append(f"{o.get('id', 'line')}: no {lang} line")
            if lang != "en" and not (o.get("latn") or {}).get(lang):
                problems.append(f"{o.get('id', 'line')}: no Roman-script {lang} caption")
    return problems


def cmd_lint(_: argparse.Namespace) -> int:
    problems = []
    for t in load("tutorials.json")["tutorials"]:
        problems += [f"tutorials.json {t['id']} title: {p}" for p in textprep.lint(t["title"])]
    samples = load("samples.json")["lines"]
    for lang, s in samples.items():
        for field in ("say", "caption"):
            problems += [f"samples.{lang}.{field}: {p}" for p in textprep.lint(s[field])]
    for path in sorted((HERE / "scripts").glob("*.json")):
        t = json.loads(path.read_text(encoding="utf-8"))
        for key in ("title", "end_headline", "next"):
            problems += [f"{path.stem}.{key}: {p}" for p in textprep.lint(t.get(key, ""))]
        for seg in t["segments"]:
            problems += [
                f"{path.stem}.{seg['id']}.label: {p}" for p in textprep.lint(seg.get("label", ""))
            ]
            for lang in LANGS:
                block = seg.get(lang) or {}
                for field in ("say", "caption"):
                    for text in block.get(field, []):
                        problems += [
                            f"{path.stem}.{seg['id']}.{lang}.{field}: {p}"
                            for p in textprep.lint(text)
                        ]
                if (
                    lang != "en"
                    and block
                    and len(block.get("say", [])) != len(block.get("caption", []))
                ):
                    where = f"{path.stem}.{seg['id']}.{lang}"
                    problems.append(f"{where}: say and caption need the same number of phrases")
    for path in sorted((HERE / "v2").glob("*.json")):
        problems += [f"v2/{path.name}: {p}" for p in lint_v2(json.loads(path.read_text("utf-8")))]
    for p in problems:
        print(p)
    print("lint:", "clean" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_voice(args: argparse.Namespace) -> int:
    from sxtut import build, tts

    cast = load("voices.json")
    todo = boards(args.which)
    need = sum(build.characters(b, args.langs) for _, b in todo)
    q = tts.quota()
    print(f"characters in these scripts ~{need} (cached lines cost nothing); left {q['left']}")
    if need > q["left"]:
        print("not enough characters left; stopping (never buy credits without the owner)")
        return 2
    for _, b in todo:
        v = build.voice(b, cast, args.langs, OUT / "cache" / "tts")
        print(f"{b['id']}: {sum(len(x) for x in v.values())} voice lines ready")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from sxtut import build

    for f, _ in boards(args.which):
        build.capture(REPO, f, day_dir(args) / "capture", args.device, args.only)
    return 0


def cmd_fonts(args: argparse.Namespace) -> int:
    """A static bold TTF of the brand face for libass (the app ships it only as a variable
    woff2)."""
    import glob

    fonts = OUT / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    target = fonts / "PlusJakartaSans-Bold.ttf"
    if target.exists():
        print(f"fonts: {target} already there")
        return 0
    hits = sorted(
        glob.glob(
            str(
                REPO
                / "apps/sales-xray-web/.next/**/media/plus-jakarta-sans-latin-wght-normal*.woff2"
            ),
            recursive=True,
        )
    )
    if not hits:
        print("fonts: brand woff2 not found in the dev build; captions fall back to DejaVu Sans")
        return 1
    code = (
        "import sys;from fontTools.ttLib import TTFont;from fontTools.varLib import instancer;"
        "f=TTFont(sys.argv[1]);f=instancer.instantiateVariableFont(f,{'wght':700});"
        "f.flavor=None;f.save(sys.argv[2])"
    )
    uv = str(Path.home() / ".local/bin/uv")
    subprocess.run(  # noqa: S603 - fixed uv/fontTools argument list
        [
            uv,
            "run",
            "--no-project",
            "--with",
            "fonttools",
            "--with",
            "brotli",
            "python",
            "-c",
            code,
            hits[0],
            str(target),
        ],
        check=True,
    )
    print(f"fonts: wrote {target}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from sxtut import build

    cast = load("voices.json")
    out = day_dir(args)
    if not (OUT / "fonts" / "PlusJakartaSans-Bold.ttf").exists():
        cmd_fonts(args)
    failed = []
    for _, b in boards(args.which):
        # One tutorial with a missing shot must not stop the others from rebuilding.
        try:
            voices = build.voice(b, cast, args.langs, OUT / "cache" / "tts")
            r = build.build(REPO, b, cast, args.langs, out / "capture", out, OUT / "fonts", voices)
            print(json.dumps(r), flush=True)
        except (KeyError, FileNotFoundError, subprocess.CalledProcessError) as e:
            failed.append(b["id"])
            print(f"{b['id']}: build FAILED ({type(e).__name__}: {e})", flush=True)
    if failed:
        print("failed:", ", ".join(failed))
    return 1 if failed else 0


def v2_boards(which: str) -> list[tuple[Path, dict]]:
    files = sorted((HERE / "v2").glob("*.json"))
    ids = None if which == "all" else set(which.split(","))
    return [
        (f, json.loads(f.read_text(encoding="utf-8")))
        for f in files
        if ids is None or f.stem in ids
    ]


def cmd_v2(args: argparse.Namespace) -> int:
    """Tutorials v2 (brand B reels and YouTube tutorials): take, voice, build, all, index."""
    from sxtut import render, tts, v2

    root = OUT / "v2"
    take_dir = root / "take"
    if args.step == "index":
        index = v2.library_index(root)
        print(f"index: {len(index['videos'])} video(s)")
        return 0
    if args.step == "pack":
        from sxtut import pack

        day = day_dir(args)
        rows = pack.export(REPO, root, day, [b for _, b in v2_boards(args.which)], args.langs)
        print(f"pack: {len(rows)} video file(s) in {day}")
        return 0
    cast = load("voices-v2.json")
    todo = v2_boards(args.which)
    if not todo:
        print(f"no v2 storyboard matches {args.which}")
        return 1
    if args.step in ("take", "all"):
        import play_listing

        for _, b in todo:
            spec = root / "work" / b["id"] / "take.json"
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(json.dumps(v2.resolved(b, play_listing.NAMES)), encoding="utf-8")
            cmd = ["node", str(HERE / "capture.mjs"), "take", str(spec), str(take_dir)]
            if args.only:
                cmd += ["--only", args.only]
            render.wait_for_headroom()
            subprocess.run(  # noqa: S603 - fixed node argument list
                [*render.NICE, *cmd],
                check=True,
                cwd=REPO,
                env=render.safe_env(),
                stdin=subprocess.DEVNULL,
            )
    if args.step not in ("voice", "build", "all"):
        return 0
    if os.environ.get("ELEVENLABS_API_KEY"):
        need = sum(v2.characters(b, args.langs) for _, b in todo)
        q = tts.quota()
        print(f"characters in these scripts ~{need} (cached lines cost nothing); left {q['left']}")
        if need > q["left"]:
            print("not enough characters left; stopping (never buy credits without the owner)")
            return 2
    music = None if args.no_music else OUT / "music" / "bed-warm-30s.mp3"
    failed = []
    for _, b in todo:
        try:
            voices = v2.voice_all(b, cast, args.langs, OUT / "cache" / "tts")
            print(f"{b['id']}: {len(voices)} voice lines ready", flush=True)
            if args.step == "voice":
                continue
            v2.build(
                REPO,
                b,
                cast,
                args.langs,
                args.formats,
                take_dir,
                root,
                OUT / "fonts",
                root / "brand" / "logo" / "svg",
                music,
                voices,
            )
        except (
            KeyError,
            ValueError,
            FileNotFoundError,
            subprocess.CalledProcessError,
            tts.TtsError,
        ) as e:
            failed.append(b["id"])
            print(f"{b['id']}: FAILED ({type(e).__name__}: {e})", flush=True)
    v2.library_index(root)
    return 1 if failed else 0


def cmd_pack(args: argparse.Namespace) -> int:
    import shutil

    out = day_dir(args)
    for part, readme in (
        ("A-narrated", "A-narrated-README.md"),
        ("B-voiceover-kit", "B-voiceover-README.md"),
        ("C-editor-pack", "C-editor-README.md"),
    ):
        if (out / part).is_dir():
            shutil.copyfile(HERE / "pack" / readme, out / part / "README.md")
    listed = {t["id"]: t for t in load("tutorials.json")["tutorials"]}
    done = sorted(p.name for p in (out / "A-narrated").glob("*") if p.is_dir())
    lines = ["# Sales X-Ray tutorials, " + out.name, ""]
    lines += [f"- {listed[i]['title'] if i in listed else i} (`{i}`)" for i in done]
    (out / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"pack: {len(done)} tutorial(s) in {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("quota").set_defaults(fn=cmd_quota)
    sub.add_parser("lint").set_defaults(fn=cmd_lint)
    s = sub.add_parser("samples")
    s.add_argument("--langs", type=lambda v: v.split(","), default=list(LANGS))
    s.add_argument("--voices", type=lambda v: v.split(","), default=["pick", "alt"])
    s.set_defaults(fn=cmd_samples)
    for name, fn in (("voice", cmd_voice), ("capture", cmd_capture), ("build", cmd_build)):
        c = sub.add_parser(name)
        c.add_argument("which")
        c.add_argument("--langs", type=lambda v: v.split(","), default=list(LANGS))
        c.add_argument("--device", choices=["phone", "desktop"])
        c.add_argument("--only", help="capture: comma-separated segment ids to re-shoot")
        c.add_argument("--date")
        c.set_defaults(fn=fn)
    w = sub.add_parser("v2", help="brand B reels and YouTube tutorials (see README, v2)")
    w.add_argument("step", choices=["take", "voice", "build", "all", "index", "pack"])
    w.add_argument("which", nargs="?", default="all")
    w.add_argument("--langs", type=lambda v: v.split(","), default=list(LANGS))
    w.add_argument("--formats", type=lambda v: v.split(","), default=["reel", "youtube"])
    w.add_argument("--only", help="take: comma-separated shot ids to re-record")
    w.add_argument("--no-music", action="store_true")
    w.add_argument("--date", help="pack: the dated delivery folder (default today)")
    w.set_defaults(fn=cmd_v2)
    f = sub.add_parser("fonts")
    f.set_defaults(fn=cmd_fonts)
    k = sub.add_parser("pack")
    k.add_argument("--date")
    k.set_defaults(fn=cmd_pack)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
